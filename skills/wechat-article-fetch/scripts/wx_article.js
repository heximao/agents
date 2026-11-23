#!/usr/bin/env node

'use strict';

/**
 * 微信公众号文章采集：识别链接 → 抓正文 → 抓留言 → 落盘。
 *
 * 用法：
 *   node scripts/wx_article.js detect "<文本/链接>"
 *   node scripts/wx_article.js fetch "<链接或分享文案>" [选项]
 *   node scripts/wx_article.js fetch --clipboard [选项]
 *   node scripts/wx_article.js fetch --input-file links.txt [选项]
 *
 * 选项见 --help。
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

const { extractLinks, parseArticleParams } = require('./lib/link');
const { fetchHtml, sleep, UA_WECHAT_IOS } = require('./lib/http');
const { parseArticlePage } = require('./lib/article');
const { fetchWithBrowser, loadPlaywright, defaultProfileDir } = require('./lib/browser');
const { fetchCommentsHttp, fetchCommentsInBrowser } = require('./lib/comments');
const { persist, stampNow } = require('./lib/render');

const CREDS_FILE_DEFAULT = path.join(__dirname, '..', '.creds.json');

function log(msg) {
  process.stderr.write(msg + '\n');
}

function parseArgs(argv) {
  const args = { _: [] };
  const flagsWithValue = new Set([
    'out', 'cookie', 'cookie-file', 'creds-file', 'uin', 'key', 'pass-ticket',
    'delay', 'limit', 'max-comments-pages', 'input-file', 'profile', 'appmsg-token',
  ]);
  const booleans = new Set([
    'comments', 'no-comments', 'browser', 'http-only', 'headed', 'images', 'json',
    'print', 'clipboard', 'stdin', 'help', 'quiet',
  ]);

  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (token.startsWith('--')) {
      const eq = token.indexOf('=');
      const name = eq === -1 ? token.slice(2) : token.slice(2, eq);
      if (flagsWithValue.has(name)) {
        args[name] = eq === -1 ? argv[++i] : token.slice(eq + 1);
      } else if (booleans.has(name)) {
        args[name] = true;
      } else {
        args[name] = eq === -1 ? true : token.slice(eq + 1);
      }
    } else {
      args._.push(token);
    }
  }
  return args;
}

function readCreds(args) {
  const creds = { cookie: '', uin: '', key: '', passTicket: '' };

  const file = args['creds-file'] || (fs.existsSync(CREDS_FILE_DEFAULT) ? CREDS_FILE_DEFAULT : '');
  if (file && fs.existsSync(file)) {
    try {
      const raw = JSON.parse(fs.readFileSync(file, 'utf-8'));
      if (raw.cookie) creds.cookie = String(raw.cookie);
      if (raw.uin) creds.uin = String(raw.uin);
      if (raw.key) creds.key = String(raw.key);
      if (raw.pass_ticket) creds.passTicket = String(raw.pass_ticket);
      if (raw.passTicket) creds.passTicket = String(raw.passTicket);
    } catch (e) {
      log(`[warn] 凭证文件解析失败：${e.message}`);
    }
  }

  if (args['cookie-file'] && fs.existsSync(args['cookie-file'])) {
    creds.cookie = fs.readFileSync(args['cookie-file'], 'utf-8').trim();
  }
  if (args.cookie) creds.cookie = args.cookie;
  if (args.uin) creds.uin = args.uin;
  if (args.key) creds.key = args.key;
  if (args['pass-ticket']) creds.passTicket = args['pass-ticket'];

  if (!creds.cookie) creds.cookie = process.env.WX_MP_COOKIE || '';
  if (!creds.uin) creds.uin = process.env.WX_MP_UIN || '';
  if (!creds.key) creds.key = process.env.WX_MP_KEY || '';
  if (!creds.passTicket) creds.passTicket = process.env.WX_MP_PASS_TICKET || '';

  return creds;
}

/** 从命令行参数 / 剪贴板 / 文件 / stdin 收集原始输入文本 */
function gatherInput(args) {
  const chunks = [...args._.slice(1)];

  if (args['input-file']) {
    if (!fs.existsSync(args['input-file'])) throw new Error(`输入文件不存在：${args['input-file']}`);
    chunks.push(fs.readFileSync(args['input-file'], 'utf-8'));
  }

  if (args.clipboard) {
    try {
      chunks.push(execSync('pbpaste', { encoding: 'utf8' }));
    } catch (e) {
      log(`[warn] 读取剪贴板失败：${e.message}`);
    }
  }

  if (args.stdin) {
    try {
      chunks.push(fs.readFileSync(0, 'utf-8'));
    } catch {
      /* ignore */
    }
  }

  return chunks.join('\n');
}

function extractTargets(input) {
  // 输入本身可能是本地 HTML 文件路径（调试用）
  let text = input;
  const fileHit = input.trim().match(/^(?:\/|\.\/|~\/)[^\n]+\.(?:html?|txt)$/i);
  if (fileHit && fs.existsSync(input.trim())) {
    const p = input.trim();
    text = fs.readFileSync(p.replace(/^~/, os.homedir()), 'utf-8');
  }
  return extractLinks(text);
}

/**
 * 抓一篇文章的 HTML：先 HTTP，失败降级浏览器。
 */
async function loadPage(target, options) {
  const attempts = [];

  if (!options.forceBrowser) {
    const res = await fetchHtml(target.url, { cookie: options.creds.cookie, uaSeed: 0 });
    const parsed = res.ok ? parseArticlePage(res.html, target.url) : { ok: false, reason: res.reason };

    if (parsed.ok) {
      return { ok: true, html: res.html, via: 'http', article: parsed.article, page: null, close: null };
    }
    attempts.push(`http: ${parsed.reason || res.reason}`);
  }

  if (options.httpOnly) {
    return { ok: false, reason: attempts.join('; ') || 'http_only', attempts };
  }

  if (!loadPlaywright()) {
    return {
      ok: false,
      reason: 'playwright_missing',
      attempts,
      hint: '需要浏览器兜底但未安装 playwright：npm i -g playwright && npx playwright install chromium',
    };
  }

  log(`[browser] 用浏览器打开：${target.url.slice(0, 90)}…`);
  const bres = await fetchWithBrowser(target.url, {
    headed: options.headed,
    profileDir: options.profileDir,
  });

  if (!bres.ok) {
    attempts.push(`browser: ${bres.reason}`);
    return { ok: false, reason: attempts.join('; '), attempts, hint: bres.hint };
  }

  const parsed = parseArticlePage(bres.html, bres.finalUrl || target.url);
  if (!parsed.ok) {
    await bres.close();
    attempts.push(`browser: ${parsed.reason}`);
    return { ok: false, reason: attempts.join('; '), attempts, hint: parsed.hint };
  }

  return { ok: true, html: bres.html, via: 'browser', article: parsed.article, page: bres.page, close: bres.close };
}

async function collectComments(target, article, page, options) {
  if (options.comments === false) return { skipped: true };

  const params = {
    biz: article.biz,
    mid: article.mid,
    idx: article.idx,
    commentId: article.comment_id,
    appmsgToken: options.appmsgToken || article.appmsg_token,
    referer: target.url,
  };

  if (!params.commentId) {
    return { available: false, reason: 'no_comment_id' };
  }

  const maxPages = options.maxCommentPages;

  if (page) {
    log('[comments] 尝试在浏览器上下文内读取留言…');
    const res = await fetchCommentsInBrowser(page, params, { maxPages });
    if (res.ok) return { available: true, ...res, via: 'browser' };
    // 浏览器内失败时，若用户提供了凭证再走一次 HTTP
    if (!options.creds.cookie && !options.creds.uin) return { available: false, ...res, via: 'browser' };
  }

  log('[comments] 通过接口读取留言…');
  const res = await fetchCommentsHttp(params, options.creds, { maxPages });
  if (res.ok) return { available: true, ...res, via: 'http' };
  return { available: false, ...res, via: 'http' };
}

async function fetchOne(target, options) {
  const record = {
    url: target.url,
    fetched_at: stampNow(),
    title: '',
    account: '',
    author: '',
    digest: '',
    publish_time: '',
    publish_ts: null,
    word_count: 0,
    images: [],
    content_markdown: '',
    comments: null,
    warnings: [],
    source: {},
  };

  const page = await loadPage(target, options);

  if (!page.ok) {
    record.error = page.reason;
    record.hint = page.hint || '';
    return record;
  }

  record.source.via = page.via;
  Object.assign(record, page.article);
  record.url = target.url;

  if (page.via === 'browser') {
    record.warnings.push('正文经浏览器兜底获取（HTTP 直连被微信人机验证拦截）。');
  }

  if (!record.title) record.warnings.push('未能解析到标题，文件名使用链接占位。');
  if (!record.publish_time) record.warnings.push('未解析到发布时间。');

  try {
    record.comments = await collectComments(target, record, page.page, options);
  } catch (e) {
    record.comments = { available: false, reason: 'exception', hint: e.message };
  } finally {
    if (page.close) await page.close();
  }

  return record;
}

async function runFetch(args) {
  const input = gatherInput(args);
  const targets = extractTargets(input);

  if (!targets.length) {
    log('未识别到微信公众号文章链接。请确认输入含 mp.weixin.qq.com/s/... 或 /s?__biz=... 形式的链接。');
    return 2;
  }

  const limit = args.limit ? Number(args.limit) : targets.length;
  const selected = targets.slice(0, limit);
  if (selected.length < targets.length) {
    log(`[info] 共识别 ${targets.length} 条链接，本次处理前 ${selected.length} 条（--limit）。`);
  }

  const options = {
    comments: !args['no-comments'],
    forceBrowser: !!args.browser,
    httpOnly: !!args['http-only'],
    headed: !!args.headed,
    profileDir: args.profile || defaultProfileDir(),
    creds: readCreds(args),
    appmsgToken: args['appmsg-token'] || '',
    maxCommentPages: args['max-comments-pages'] ? Number(args['max-comments-pages']) : 10,
  };

  const delayMs = args.delay ? Number(args.delay) : Math.max(1500, Math.round(3000 / selected.length));

  const records = [];
  for (let i = 0; i < selected.length; i++) {
    const target = selected[i];
    log(`\n=== [${i + 1}/${selected.length}] ${target.url.slice(0, 100)}`);
    if (target.risk === 'missing_chksm') {
      log('  [注意] 该链接是完整链接但缺少 chksm 参数，微信大概率返回人机验证页；优先改用公众号原始分享的短链（mp.weixin.qq.com/s/xxxx）。');
    }

    const record = await fetchOne(target, options);
    if (target.risk === 'missing_chksm') record.warnings.push('链接缺少 chksm 参数，属于高风险形态（易触发人机验证）。');
    records.push(record);

    if (record.error) {
      log(`  ✗ 采集失败：${record.error}${record.hint ? ' — ' + record.hint : ''}`);
    } else {
      const c = record.comments;
      const cInfo = !c
        ? ''
        : c.skipped
          ? '留言跳过'
          : c.available
            ? `留言 ${c.items.length}/${c.total}`
            : `留言不可用(${c.reason})`;
      log(`  ✓ ${record.title || '(无标题)'} | ${record.account || '-'} | ${record.word_count} 字 | ${record.images.length} 图 | ${cInfo}`);
    }

    if (i < selected.length - 1) await sleep(delayMs);
  }

  const successful = records.filter((r) => !r.error);

  // 落盘
  const outDir = path.resolve(args.out || 'wechat-mp-output');
  const persisted = [];
  for (const rec of successful) {
    if (!rec.title && !rec.content_markdown) continue;
    const saved = await persist(rec, {
      outDir,
      downloadImageFiles: !!args.images,
      includeComments: options.comments,
      ua: UA_WECHAT_IOS,
    });
    persisted.push({ record: rec, ...saved });
    if (!args.quiet) log(`  → ${saved.mdPath}`);
  }

  // stdout
  if (args.json) {
    process.stdout.write(JSON.stringify({ count: records.length, records }, null, 2) + '\n');
  } else if (args.print) {
    for (const p of persisted) process.stdout.write(p.md + '\n');
  } else {
    const summary = records.map((r) => ({
      url: r.url,
      title: r.title || null,
      account: r.account || null,
      publish_time: r.publish_time || null,
      word_count: r.word_count || 0,
      images: (r.images || []).length,
      comments: r.comments
        ? { available: !!r.comments.available, collected: r.comments.items ? r.comments.items.length : 0, total: r.comments.total || 0, reason: r.comments.reason || null }
        : null,
      error: r.error || null,
      saved_to: (persisted.find((p) => p.record === r) || {}).dir || null,
    }));
    process.stdout.write(JSON.stringify({ ok: successful.length > 0, out_dir: outDir, items: summary }, null, 2) + '\n');
  }

  if (!successful.length) {
    log('\n全部文章采集失败。常见原因：链接不完整（缺 chksm）、文章已删除、当前网络被微信风控。');
    return 1;
  }
  return 0;
}

function runDetect(args) {
  const input = gatherInput(args) || args._.slice(1).join(' ');
  const targets = extractLinks(input);
  const out = targets.map((t) => ({
    url: t.url,
    kind: t.kind,
    key: t.key,
    params: t.params,
  }));
  process.stdout.write(JSON.stringify({ count: out.length, links: out }, null, 2) + '\n');
  return out.length ? 0 : 2;
}

function usage() {
  process.stdout.write(`微信公众号文章采集（正文 + 留言）

用法:
  node scripts/wx_article.js detect <文本|链接> [--clipboard] [--input-file f]
  node scripts/wx_article.js fetch  <文本|链接> [选项]

输入来源（可组合）:
  位置参数            直接粘贴链接或整段分享文案
  --input-file <f>    从文件读取（一行一条或整段文本）
  --clipboard         读取 macOS 剪贴板（pbpaste）
  --stdin             从标准输入读取

采集选项:
  --out <dir>              输出目录（默认 ./wechat-mp-output）
  --no-comments            只抓正文，不抓留言
  --images                 下载正文图片到 images/ 并改写为本地路径
  --browser                强制走浏览器（HTTP 被风控时更稳，需要 playwright）
  --http-only              只用 HTTP，不启用浏览器兜底
  --headed                 浏览器使用有头模式（可手动完成人机验证）
  --profile <dir>          浏览器持久化 profile（默认 ~/.workbuddy/skills/wechat-article-fetch/.profile）
  --limit <n>              最多处理前 n 篇文章
  --delay <ms>             批量间隔（默认约 3000/n，最少 1500ms）
  --max-comments-pages <n> 留言翻页上限（默认 10 页 × 100 条）

留言凭证（不提供时留言会跳过并说明原因）:
  --cookie "<k=v; k=v>"    微信会话 Cookie
  --cookie-file <f>        Cookie 文本文件
  --creds-file <f>         JSON 凭证：{cookie, uin, key, pass_ticket}
  --uin / --key / --pass-ticket
  环境变量                 WX_MP_COOKIE / WX_MP_UIN / WX_MP_KEY / WX_MP_PASS_TICKET
  默认凭证文件             scripts/../.creds.json

输出:
  --json                   完整结果 JSON 输出到 stdout
  --print                  输出 Markdown 到 stdout
  --quiet                  不在 stderr 打印落盘路径

示例:
  node scripts/wx_article.js fetch "https://mp.weixin.qq.com/s/AbCdEfGh"
  node scripts/wx_article.js fetch --clipboard --comments --images
  node scripts/wx_article.js fetch --input-file links.txt --out ./archive
`);
}

async function main() {
  const argv = process.argv.slice(2);
  const args = parseArgs(argv);
  const command = args._[0];

  if (args.help || !command || command === 'help') {
    usage();
    return args.help ? 0 : 2;
  }

  if (command === 'detect') return runDetect(args);
  if (command === 'fetch') return runFetch(args);

  log(`未知命令：${command}`);
  usage();
  return 2;
}

main()
  .then((code) => process.exit(code || 0))
  .catch((e) => {
    log(`致命错误：${e && e.stack ? e.stack : e}`);
    process.exit(1);
  });

module.exports = { fetchOne, parseArgs };
