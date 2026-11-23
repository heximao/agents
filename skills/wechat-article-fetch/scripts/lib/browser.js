'use strict';

/**
 * 浏览器兜底路径。
 *
 * 为什么需要：微信对「不带 chksm 的完整链接」和异常 IP 会 302 到
 * /mp/wappoc_appmsgcaptcha 人机验证页，纯 HTTP 请求无法完成验证；
 * 真实浏览器执行页面 JS 后会自动带着验证结果跳回文章页。
 *
 * 同时，浏览器上下文是唯一能让留言接口继承登录态的地方
 * （若该 profile 里登录过微信文章页 / 公众号后台）。
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');
const { sleep } = require('./http');

let cached = null;

function loadPlaywright() {
  if (cached !== null) return cached;

  const candidates = ['playwright', 'playwright-core'];
  for (const name of candidates) {
    try {
      cached = require(name);
      return cached;
    } catch {
      /* 继续尝试全局路径 */
    }
  }

  try {
    const globalRoot = execSync('npm root -g', { encoding: 'utf8' }).trim();
    const extra = [
      path.join(globalRoot, 'playwright'),
      path.join(globalRoot, 'playwright-core'),
      // @playwright/cli 自带一份 playwright 运行时
      path.join(globalRoot, '@playwright/cli/node_modules/playwright'),
      path.join(globalRoot, '@playwright/cli/node_modules/playwright-core'),
    ];
    for (const p of extra) {
      if (fs.existsSync(p)) {
        cached = require(p);
        return cached;
      }
    }
  } catch {
    /* ignore */
  }

  cached = false;
  return cached;
}

function defaultProfileDir() {
  return path.join(os.homedir(), '.workbuddy', 'skills', 'wechat-article-fetch', '.profile');
}

/** 列出本机 ms-playwright 缓存里可用的 chromium 可执行文件 */
function findLocalChromium() {
  const cacheDirs = [
    path.join(os.homedir(), 'Library', 'Caches', 'ms-playwright'),
    path.join(os.homedir(), '.cache', 'ms-playwright'),
  ];
  const found = [];
  for (const base of cacheDirs) {
    if (!fs.existsSync(base)) continue;
    const entries = fs.readdirSync(base).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse();
    for (const dir of entries) {
      const candidates = [
        path.join(base, dir, 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
        path.join(base, dir, 'chrome-mac-arm64', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
        path.join(base, dir, 'chrome-linux', 'chrome'),
      ];
      for (const c of candidates) {
        if (fs.existsSync(c)) found.push(c);
      }
    }
  }
  return found;
}

/**
 * 启动浏览器：优先系统 Chrome（不受 playwright 版本与浏览器缓存错配影响），
 * 再退回 playwright 自带 chromium，最后显式指定本机缓存里的可执行文件。
 * 返回 { ctx } 或 { error }
 */
async function launchContext(pw, { headless, profileDir }) {
  const common = {
    headless,
    viewport: { width: 1280, height: 900 },
    locale: 'zh-CN',
    args: ['--disable-blink-features=AutomationControlled'],
  };

  const strategies = [
    { label: 'chrome', options: { ...common, channel: 'chrome' } },
    { label: 'chromium', options: { ...common } },
    ...findLocalChromium().map((exe, i) => ({ label: `local-chromium-${i}`, options: { ...common, executablePath: exe } })),
  ];

  const errors = [];
  for (const s of strategies) {
    try {
      const ctx = await pw.chromium.launchPersistentContext(profileDir, s.options);
      return { ctx, via: s.label };
    } catch (e) {
      errors.push(`${s.label}: ${String(e.message).split('\n')[0]}`);
    }
  }
  return { error: errors.join(' | ') };
}

async function waitForArticle(page, { headed, manualWaitMs = 90000 }) {
  const started = Date.now();
  // 无人值守时不必久等：验证页的 JS 通常 1~3 秒内自动跳回，过不去就是过不去
  const limit = headed ? manualWaitMs : Math.min(manualWaitMs, 15000);
  let announced = false;

  while (Date.now() - started < limit) {
    const state = await page
      .evaluate(() => ({
        href: location.href,
        hasContent: !!document.querySelector('#js_content'),
        isCaptcha: /wappoc_appmsgcaptcha|\/mp\/verify/.test(location.href),
      }))
      .catch(() => ({ href: '', hasContent: false, isCaptcha: false }));

    if (state.hasContent) return { ok: true, href: state.href };
    if (!state.isCaptcha && !headed) return { ok: false, reason: 'no_content', href: state.href };

    if (state.isCaptcha && headed && !announced) {
      announced = true;
      process.stderr.write('[browser] 已打开浏览器窗口，若出现人机验证请手动完成，最多等待 ' + Math.round(manualWaitMs / 1000) + ' 秒…\n');
    }
    await sleep(headed ? 1500 : 800);
  }

  return { ok: false, reason: 'captcha_timeout', href: page.url() };
}

/**
 * 用浏览器打开文章页。
 * @returns {Promise<{ok:boolean, reason?:string, html?:string, finalUrl?:string,
 *                    ctx?:object, page?:object, close?:Function}>}
 */
async function fetchWithBrowser(url, options = {}) {
  const {
    headed = false,
    profileDir = defaultProfileDir(),
    timeoutMs = 45000,
    manualWaitMs = 90000,
  } = options;

  const pw = loadPlaywright();
  if (!pw) {
    return {
      ok: false,
      reason: 'playwright_missing',
      hint: '未检测到 playwright，无法启用浏览器兜底。可执行 npm i -g playwright && npx playwright install chromium',
    };
  }

  fs.mkdirSync(profileDir, { recursive: true });

  const launched = await launchContext(pw, { headless: !headed, profileDir });
  if (!launched.ctx) {
    return {
      ok: false,
      reason: 'launch_failed',
      hint: `浏览器启动失败（${launched.error}）。可执行 npx playwright install chromium，或安装 Chrome 后重试`,
    };
  }
  const ctx = launched.ctx;

  const close = async () => {
    try {
      await ctx.close();
    } catch {
      /* ignore */
    }
  };

  try {
    const page = ctx.pages()[0] || (await ctx.newPage());
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: timeoutMs });

    const waited = await waitForArticle(page, { headed, manualWaitMs });
    if (!waited.ok) {
      const html = await page.content().catch(() => '');
      await close();
      return {
        ok: false,
        reason: waited.reason,
        hint:
          waited.reason === 'captcha_timeout'
            ? '无人值守模式下未能越过人机验证。改用 --headed 打开浏览器手动完成一次验证后，会写入持久化 profile，后续可复用。'
            : '浏览器打开后仍未拿到正文，可能文章已删除或网络异常。',
        html,
      };
    }

    // 让懒加载图片与正文样式收敛
    await page.evaluate(() => window.scrollTo(0, 300)).catch(() => {});
    await sleep(500);

    const html = await page.content();
    return { ok: true, html, finalUrl: page.url(), ctx, page, close, browser: launched.via };
  } catch (e) {
    await close();
    return { ok: false, reason: 'navigate_failed', hint: `打开页面失败：${e.message}` };
  }
}

module.exports = { fetchWithBrowser, loadPlaywright, defaultProfileDir };
