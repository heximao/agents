'use strict';

/**
 * 微信公众号文章链接识别与归一化。
 *
 * 支持的输入形态：
 *   - 纯链接：https://mp.weixin.qq.com/s/AbCdEfGh
 *   - 完整链接：https://mp.weixin.qq.com/s?__biz=..&mid=..&idx=..&sn=..&chksm=..
 *   - 微信分享文案：标题 + 换行 + 链接 + 「阅读原文」等尾巴
 *   - 无协议前缀：mp.weixin.qq.com/s/xxx
 *   - HTML 实体化链接：...&amp;mid=...
 */

// 链接允许的字符范围。刻意排除中文标点与括号，避免把分享文案的标点吞进 URL。
const LINK_RE = /(?:https?:\/\/)?mp\.weixin\.qq\.com\/[^\s"'`<>()（）【】\[\]、，。；：！？“”‘’]+/gi;

// 只影响统计追踪、不影响可访问性的参数，归一化时清掉
const DROP_PARAMS = new Set([
  'xtrack', 'from', 'isappinstalled', 'clicktime', 'enterid',
  'sessionid', 'subscene', 'ascene', 'wx_header', 'exportkey',
  'poc_token', 'nwr_flag', 'key', 'pass_ticket', 'uin', 'devicetype',
  'version', 'nettype', 'lang', 'fontscale', 'abtest_cookie', 'x5',
]);

function decodeEntities(str) {
  if (!str) return '';
  return str
    .replace(/&amp;/g, '&')
    .replace(/&#38;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

/**
 * 归一化单条链接：补协议、去 hash、清理追踪参数。
 * 关键点两处：
 *   1. chksm 必须保留 —— 微信完整链接缺少 chksm 时几乎必然被 302 到人机验证页。
 *   2. query 不走 URLSearchParams 重建 —— 否则 __biz 里的 "==" 会被编码成 %3D%3D，
 *      与用户原始分享链接不一致，徒增风控风险。
 */
function stripParams(search, dropSet) {
  if (!search || search === '?') return '';
  const kept = search
    .slice(1)
    .split('&')
    .filter((pair) => pair && !dropSet.has(pair.split('=')[0]));
  return kept.length ? '?' + kept.join('&') : '';
}

function normalizeUrl(raw) {
  let s = decodeEntities(String(raw || '').trim());
  if (!s) return null;
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;

  let url;
  try {
    url = new URL(s);
  } catch {
    return null;
  }
  if (!/^mp\.weixin\.qq\.com$/i.test(url.hostname)) return null;

  url.hash = '';
  url.protocol = 'https:';
  url.search = stripParams(url.search, DROP_PARAMS);
  return url.toString();
}

/**
 * 解析链接中的文章身份参数。
 * @returns {{kind:'short'|'param', biz:string|null, mid:string|null, idx:string|null,
 *            sn:string|null, chksm:string|null, shortId:string|null}}
 */
function parseArticleParams(rawUrl) {
  const url = new URL(rawUrl);
  const path = url.pathname.replace(/\/+$/, '');
  const q = url.searchParams;
  const shortMatch = path.match(/^\/s\/([A-Za-z0-9_-]{6,})$/);

  const params = {
    kind: shortMatch ? 'short' : 'param',
    biz: q.get('__biz') || null,
    mid: q.get('mid') || q.get('appmsgid') || null,
    idx: q.get('idx') || null,
    sn: q.get('sn') || null,
    chksm: q.get('chksm') || null,
    shortId: shortMatch ? shortMatch[1] : null,
  };

  // 有 __biz 但缺 mid/idx 的链接不是标准图文链接
  if (!shortMatch && !params.biz) params.kind = 'unknown';
  return params;
}

/**
 * 从任意文本中识别公众号文章链接。
 * @param {string} text
 * @returns {Array<{url:string, raw:string, kind:string, key:string}>}
 */
function extractLinks(text) {
  const src = decodeEntities(String(text || ''));
  const seen = new Set();
  const out = [];

  for (const m of src.matchAll(LINK_RE)) {
    const url = normalizeUrl(m[0]);
    if (!url) continue;
    const params = parseArticleParams(url);
    if (params.kind === 'unknown') continue;

    // 去重键：完整链接用 biz+mid+idx，短链用 shortId
    const key = params.biz && params.mid
      ? `biz:${params.biz}:${params.mid}:${params.idx || '1'}`
      : `short:${params.shortId}`;
    if (seen.has(key)) continue;
    seen.add(key);

    // 完整链接缺 chksm 时，微信几乎必然 302 到人机验证页；提前给出风险标记
    const risk = params.kind === 'param' && !params.chksm ? 'missing_chksm' : null;

    out.push({ url, raw: m[0], kind: params.kind, key, params, risk });
  }
  return out;
}

/** 从文本中提取「标题 + 链接」这种分享形态里的标题（尽力而为，失败返回空串） */
function guessShareTitle(text) {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  for (const line of lines) {
    if (/mp\.weixin\.qq\.com/i.test(line)) continue;
    if (line.length < 4) continue;
    if (/^(阅读原文|分享|收藏|在看|点赞|复制链接)$/.test(line)) continue;
    return line;
  }
  return '';
}

module.exports = {
  decodeEntities,
  normalizeUrl,
  parseArticleParams,
  extractLinks,
  guessShareTitle,
};
