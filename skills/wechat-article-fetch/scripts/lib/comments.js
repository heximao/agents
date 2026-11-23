'use strict';

/**
 * 公众号留言（精选评论）采集。
 *
 * 硬约束：/mp/appmsg_comment?action=getcomment 需要真实微信会话凭证
 * （Cookie 中的 uin/pass_ticket 或 key，外加页面里的 appmsg_token）。
 * 匿名请求一律返回 ret=-3 "no session" —— 这是接口设计，不是 Bug。
 *
 * 因此本模块提供两种执行方式：
 *   1) HTTP + 用户提供的凭证（最快、上限高）
 *   2) 复用浏览器页面上下文内 fetch（继承该浏览器 profile 的登录态）
 */

const { fetchJson, sleep } = require('./http');
const { htmlToText } = require('./html2md');

const ENDPOINT = 'https://mp.weixin.qq.com/mp/appmsg_comment';
const PAGE_LIMIT = 100;

/**
 * @param {{biz:string, mid:string, idx:string, commentId:string, appmsgToken?:string}} target
 * @param {{cookie?:string, uin?:string, key?:string, passTicket?:string}} creds
 */
function buildCommentUrl(target, creds = {}, offset = 0, limit = PAGE_LIMIT) {
  const q = new URLSearchParams();
  q.set('action', 'getcomment');
  q.set('scene', '0');
  q.set('__biz', target.biz || '');
  q.set('appmsgid', target.mid || '');
  q.set('idx', target.idx || '1');
  q.set('comment_id', target.commentId || '');
  q.set('offset', String(offset));
  q.set('limit', String(limit));
  q.set('count', String(limit));
  if (creds.uin) q.set('uin', creds.uin);
  if (creds.key) q.set('key', creds.key);
  if (creds.passTicket) q.set('pass_ticket', creds.passTicket);
  if (target.appmsgToken) q.set('appmsg_token', target.appmsgToken);
  q.set('wxtoken', '');
  q.set('devicetype', '');
  q.set('clientversion', '');
  q.set('x5', '0');
  q.set('f', 'json');
  return `${ENDPOINT}?${q.toString()}`;
}

function ipLocationOf(item) {
  const ip = item.ip_wording;
  if (ip && typeof ip === 'object') {
    return [ip.country_name, ip.province_name, ip.city_name].filter(Boolean).join(' ');
  }
  if (typeof ip === 'string') return ip;
  return '';
}

function cleanCommentText(raw) {
  if (!raw) return '';
  const text = /<[a-z][\s\S]*>/i.test(raw) ? htmlToText(raw) : String(raw);
  return text.replace(/\s+\n/g, '\n').replace(/[ \t]{2,}/g, ' ').trim();
}

function normalizeReply(reply) {
  if (!reply) return [];
  const list = Array.isArray(reply) ? reply : [reply];
  const out = [];
  for (const r of list) {
    if (!r || typeof r !== 'object') continue;
    const nested = r.reply_list || r.reply;
    const item = {
      nickname: (r.nick_name || r.nickname || '').trim(),
      content: cleanCommentText(r.content),
      like_num: Number(r.like_num || 0),
      create_time: r.create_time ? require('./article').formatChinaTime(Number(r.create_time) * 1000) : '',
      ip_location: ipLocationOf(r),
    };
    if (item.content) out.push(item);
    if (nested) out.push(...normalizeReply(nested));
  }
  return out;
}

function normalizeComment(item, index) {
  const replies = normalizeReply(item.reply);
  return {
    index: index + 1,
    nickname: (item.nick_name || item.nickname || '').trim(),
    content: cleanCommentText(item.content),
    like_num: Number(item.like_num || 0),
    create_time: item.create_time ? require('./article').formatChinaTime(Number(item.create_time) * 1000) : '',
    ip_location: ipLocationOf(item),
    is_top: Number(item.is_top || 0) === 1,
    content_id: item.content_id ? String(item.content_id) : '',
    avatar: item.logo_url || '',
    replies,
    reply_count: replies.length,
  };
}

function interpretError(json, text) {
  const ret = json && (json.base_resp ? json.base_resp.ret : json.ret);
  const errmsg = (json && ((json.base_resp && json.base_resp.errmsg) || json.errmsg)) || '';
  if (ret === 0) return null;
  if (ret === -3 || /no session/i.test(errmsg)) {
    return { reason: 'no_session', hint: '留言接口需要微信会话凭证（uin + key/pass_ticket），匿名请求无法读取' };
  }
  if (ret === 200003) {
    return { reason: 'rate_limited', hint: '请求过于频繁，微信已限频，请降低频率后重试' };
  }
  if (ret === -1 || ret === 200002) {
    return { reason: 'invalid_request', hint: `接口返回异常：${errmsg || ret}` };
  }
  if (!json && text) {
    return { reason: 'not_json', hint: `接口返回非 JSON（前 120 字）：${text.slice(0, 120)}` };
  }
  return { reason: 'unknown', hint: `接口返回 ret=${ret} ${errmsg}`.trim() };
}

function extractPage(json) {
  const list = json.elected_comment || json.comment || [];
  const total = Number(
    json.elected_comment_total_cnt || json.comment_total_cnt || json.total || (Array.isArray(list) ? list.length : 0)
  );
  return { list: Array.isArray(list) ? list : [], total };
}

/**
 * 通过 HTTP 逐页拉取留言。
 * @param {object} target {biz, mid, idx, commentId, appmsgToken}
 * @param {object} creds {cookie, uin, key, passTicket}
 */
async function fetchCommentsHttp(target, creds = {}, options = {}) {
  const { maxPages = 10, delayMs = 900 } = options;

  if (!target.commentId) {
    return { ok: false, reason: 'no_comment_id', hint: '文章没有留言区（未开通留言或页面未返回 comment_id）' };
  }

  const collected = [];
  let total = 0;
  let pages = 0;

  for (let page = 0; page < maxPages; page++) {
    const url = buildCommentUrl(target, creds, page * PAGE_LIMIT, PAGE_LIMIT);
    const res = await fetchJson(url, { cookie: creds.cookie || '', retries: 0, referer: target.referer || 'https://mp.weixin.qq.com/' });

    const err = interpretError(res.json, res.text);
    if (err) {
      // 第一页就失败 → 整体失败；后续页失败 → 保留已抓内容
      if (page === 0) return { ok: false, ...err, total: 0, items: [], pages: 0 };
      return {
        ok: true,
        partial: true,
        truncated_reason: err.reason,
        total,
        items: collected,
        pages,
      };
    }

    const { list, total: t } = extractPage(res.json);
    total = t || total;
    pages += 1;

    let added = 0;
    for (const raw of list) {
      const key = raw.content_id || `${raw.nick_name}|${raw.content}`;
      if (collected.some((c) => c.content_id && c.content_id === key)) continue;
      collected.push(normalizeComment(raw, collected.length));
      added += 1;
    }

    const reachedEnd = list.length < PAGE_LIMIT || (total > 0 && collected.length >= total);
    if (reachedEnd || added === 0) break;
    await sleep(delayMs + Math.random() * 400);
  }

  return {
    ok: true,
    total: total || collected.length,
    items: collected,
    pages,
    truncated: total > collected.length,
  };
}

/**
 * 在已打开的浏览器页面里请求留言（继承浏览器 Cookie / 登录态）。
 * @param {import('playwright').Page} page
 */
async function fetchCommentsInBrowser(page, target, options = {}) {
  const { maxPages = 10, waitMs = 1200 } = options;

  if (!target.commentId) {
    return { ok: false, reason: 'no_comment_id', hint: '文章没有留言区（未开通留言或页面未返回 comment_id）' };
  }

  const collected = [];
  let total = 0;
  let pages = 0;

  for (let i = 0; i < maxPages; i++) {
    const url = buildCommentUrl(target, {}, i * PAGE_LIMIT, PAGE_LIMIT);
    let payload;
    try {
      payload = await page.evaluate(async (u) => {
        const r = await fetch(u, { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const t = await r.text();
        try {
          return { json: JSON.parse(t), text: t };
        } catch {
          return { json: null, text: t };
        }
      }, url);
    } catch (e) {
      return { ok: false, reason: 'browser_fetch_failed', hint: `页面内请求失败：${e.message}`, total, items: collected, pages };
    }

    const err = interpretError(payload.json, payload.text);
    if (err) {
      if (i === 0) return { ok: false, ...err, total: 0, items: [], pages: 0 };
      return { ok: true, partial: true, truncated_reason: err.reason, total, items: collected, pages };
    }

    const { list, total: t } = extractPage(payload.json);
    total = t || total;
    pages += 1;

    let added = 0;
    for (const raw of list) {
      const key = raw.content_id || `${raw.nick_name}|${raw.content}`;
      if (collected.some((c) => c.content_id && c.content_id === key)) continue;
      collected.push(normalizeComment(raw, collected.length));
      added += 1;
    }

    if (list.length < PAGE_LIMIT || (total > 0 && collected.length >= total) || added === 0) break;
    await page.waitForTimeout(waitMs);
  }

  return { ok: true, total: total || collected.length, items: collected, pages, truncated: total > collected.length };
}

module.exports = {
  buildCommentUrl,
  fetchCommentsHttp,
  fetchCommentsInBrowser,
  normalizeComment,
  interpretError,
  PAGE_LIMIT,
};
