'use strict';

const http = require('http');
const https = require('https');
const zlib = require('zlib');

// 微信内置浏览器 UA 的通过率高于桌面 UA（正文页会按 UA 返回不同模板）
const UA_WECHAT_IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.49(0x18003132) NetType/WIFI Language/zh_CN';
const UA_WECHAT_ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/122.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.48.2580(0x28003036) WeChat/arm64';
const UA_DESKTOP = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

const UA_POOL = [UA_WECHAT_IOS, UA_WECHAT_ANDROID, UA_WECHAT_IOS, UA_DESKTOP];

function pickUA(seed) {
  if (typeof seed === 'number') return UA_POOL[seed % UA_POOL.length];
  return UA_POOL[Math.floor(Math.random() * UA_POOL.length)];
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function decompress(buf, encoding) {
  const enc = String(encoding || '').toLowerCase();
  try {
    if (enc.includes('gzip')) return zlib.gunzipSync(buf);
    if (enc.includes('deflate')) return zlib.inflateSync(buf);
    if (enc.includes('br')) return zlib.brotliDecompressSync(buf);
  } catch {
    /* 解压失败退回原始数据 */
  }
  return buf;
}

/** 单次请求，不跟随重定向 */
function rawRequest(urlStr, options = {}) {
  const { method = 'GET', headers = {}, timeoutMs = 20000 } = options;
  return new Promise((resolve, reject) => {
    let url;
    try {
      url = new URL(urlStr);
    } catch (e) {
      reject(e);
      return;
    }
    const lib = url.protocol === 'http:' ? http : https;
    const req = lib.request(
      {
        protocol: url.protocol,
        hostname: url.hostname,
        port: url.port || undefined,
        path: url.pathname + url.search,
        method,
        headers,
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          resolve({
            statusCode: res.statusCode || 0,
            headers: res.headers,
            body: decompress(Buffer.concat(chunks), res.headers['content-encoding']),
          });
        });
      }
    );
    req.on('error', reject);
    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error('timeout'));
    });
    req.end();
  });
}

function mergeCookies(jar, setCookie) {
  if (!setCookie) return jar;
  const list = Array.isArray(setCookie) ? setCookie : [setCookie];
  for (const item of list) {
    const pair = String(item).split(';')[0];
    const eq = pair.indexOf('=');
    if (eq <= 0) continue;
    jar[pair.slice(0, eq).trim()] = pair.slice(eq + 1).trim();
  }
  return jar;
}

function cookieHeader(jar) {
  return Object.entries(jar)
    .map(([k, v]) => `${k}=${v}`)
    .join('; ');
}

/**
 * 抓取 HTML，手动跟随重定向并累积 Cookie。
 * 不自动跟随到底的意义：需要识别「被重定向到 wappoc_appmsgcaptcha」这种风控信号。
 */
async function fetchHtml(urlStr, options = {}) {
  const {
    cookie = '',
    uaSeed,
    maxRedirects = 5,
    timeoutMs = 20000,
    retries = 1,
    referer = 'https://mp.weixin.qq.com/',
  } = options;

  const jar = {};
  for (const part of String(cookie || '').split(';')) {
    const eq = part.indexOf('=');
    if (eq > 0) jar[part.slice(0, eq).trim()] = part.slice(eq + 1).trim();
  }

  let target = urlStr;
  let lastError = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    target = urlStr;
    try {
      for (let hop = 0; hop <= maxRedirects; hop++) {
        const headers = {
          'User-Agent': pickUA(uaSeed),
          Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
          'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.6',
          'Accept-Encoding': 'identity',
          Referer: referer,
        };
        const ck = cookieHeader(jar);
        if (ck) headers.Cookie = ck;

        const res = await rawRequest(target, { headers, timeoutMs });
        mergeCookies(jar, res.headers['set-cookie']);

        const isRedirect = res.statusCode >= 300 && res.statusCode < 400 && res.headers.location;
        if (isRedirect) {
          const next = new URL(res.headers.location, target).toString();
          if (/wappoc_appmsgcaptcha/.test(next) || /\/mp\/verify/.test(next)) {
            return {
              ok: false,
              reason: 'captcha',
              finalUrl: next,
              statusCode: res.statusCode,
              html: res.body.toString('utf-8'),
              cookie: cookieHeader(jar),
            };
          }
          target = next;
          continue;
        }

        const html = res.body.toString('utf-8');
        const blocked = /wappoc_appmsgcaptcha|环境异常|去验证|Access Denied|captcha/i.test(html.slice(0, 4000));
        return {
          ok: res.statusCode === 200 && !blocked,
          reason: res.statusCode !== 200 ? `http_${res.statusCode}` : blocked ? 'captcha' : null,
          finalUrl: target,
          statusCode: res.statusCode,
          html,
          cookie: cookieHeader(jar),
        };
      }
      return { ok: false, reason: 'too_many_redirects', finalUrl: target, statusCode: 0, html: '', cookie: cookieHeader(jar) };
    } catch (e) {
      lastError = e;
      if (attempt < retries) await sleep(800 + Math.random() * 800);
    }
  }

  return {
    ok: false,
    reason: `network:${lastError ? lastError.message : 'unknown'}`,
    finalUrl: target,
    statusCode: 0,
    html: '',
    cookie: cookieHeader(jar),
  };
}

/** 抓取 JSON 接口（留言、阅读量等），带 Cookie 与重试 */
async function fetchJson(urlStr, options = {}) {
  const { cookie = '', uaSeed, timeoutMs = 20000, retries = 1, referer = 'https://mp.weixin.qq.com/' } = options;
  let lastError = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const headers = {
        'User-Agent': pickUA(uaSeed),
        Accept: 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'identity',
        Referer: referer,
        'X-Requested-With': 'XMLHttpRequest',
      };
      if (cookie) headers.Cookie = cookie;

      const res = await rawRequest(urlStr, { headers, timeoutMs });
      const text = res.body.toString('utf-8');
      let json = null;
      try {
        json = JSON.parse(text);
      } catch {
        json = null;
      }
      if (json) return { ok: true, statusCode: res.statusCode, json, text };
      return { ok: false, statusCode: res.statusCode, json: null, text, reason: 'not_json' };
    } catch (e) {
      lastError = e;
      if (attempt < retries) await sleep(800 + Math.random() * 600);
    }
  }
  return { ok: false, statusCode: 0, json: null, text: '', reason: `network:${lastError ? lastError.message : 'unknown'}` };
}

module.exports = { fetchHtml, fetchJson, cookieHeader, sleep, pickUA, UA_WECHAT_IOS, UA_DESKTOP };
