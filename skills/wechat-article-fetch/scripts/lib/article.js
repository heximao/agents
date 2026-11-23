'use strict';

/**
 * 从文章页 HTML 中抽取元信息、正文节点与留言区标识。
 */

const { parseHTML, nodeToMarkdown, normalizeMarkdown } = require('./html2md');

const DELETED_PATTERNS = [
  { re: /该内容已被发布者删除|此内容已被发布者删除/, reason: 'deleted' },
  { re: /此内容因违规无法查看|内容违规无法查看|该内容已被屏蔽/, reason: 'violation' },
  { re: /该公众号已迁移|帐号已迁移|账号已迁移/, reason: 'migrated' },
  { re: /参数错误|访问过于频繁|请稍后再试/, reason: 'blocked_or_invalid' },
];

/**
 * 读取页面内 `var name = ...;` 形态的变量。
 * 兼容：var a = "x" / var a = 'x' / var a = htmlDecode("x") / var a = "" || "x"
 */
function grabVar(html, name) {
  const re = new RegExp(`var\\s+${name}\\s*=\\s*([\\s\\S]{0,600}?);`, 'i');
  const m = re.exec(html);
  if (!m) return '';
  const expr = m[1];
  const strings = [];
  for (const sm of expr.matchAll(/(["'])((?:\\.|(?!\1)[^\\])*)\1/g)) {
    strings.push(sm[2]);
  }
  const first = strings.find((s) => s && s.trim() && s !== '0');
  if (!first) return '';
  return decodeJsString(first);
}

function decodeJsString(s) {
  return String(s)
    .replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/\\x([0-9a-fA-F]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
    .replace(/\\'/g, "'")
    .replace(/\\"/g, '"')
    .replace(/\\n/g, '\n')
    .replace(/\\t/g, '\t')
    .replace(/\\\\/g, '\\')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .trim();
}

function metaTag(html, key) {
  const patterns = [
    new RegExp(`<meta[^>]+property=["']${key}["'][^>]+content=["']([^"']*)["']`, 'i'),
    new RegExp(`<meta[^>]+content=["']([^"']*)["'][^>]+property=["']${key}["']`, 'i'),
    new RegExp(`<meta[^>]+name=["']${key}["'][^>]+content=["']([^"']*)["']`, 'i'),
  ];
  for (const re of patterns) {
    const m = re.exec(html);
    if (m) return decodeJsString(m[1]);
  }
  return '';
}

/** 深度优先查找满足条件的第一个节点 */
function findNode(node, predicate, guard = { depth: 0 }) {
  if (guard.depth > 200) return null;
  if (predicate(node)) return node;
  for (const child of node.children || []) {
    const found = findNode(child, predicate, { depth: guard.depth + 1 });
    if (found) return found;
  }
  return null;
}

function findContentNode(tree) {
  const byId = findNode(tree, (n) => n.attrs && n.attrs.id === 'js_content');
  if (byId) return byId;
  return findNode(tree, (n) => n.attrs && /\brich_media_content\b/.test(n.attrs.class || ''));
}

function collectImages(tree) {
  const urls = new Set();
  const walk = (node) => {
    if (node.tag === 'img') {
      const a = node.attrs || {};
      const src = (a['data-src'] || a['data-original'] || a.src || '').trim().replace(/#.*$/, '');
      const w = Number(a['data-w'] || a.width || 0);
      if (src && !/^data:/i.test(src) && !(w && w < 60)) urls.add(src);
    }
    for (const c of node.children || []) walk(c);
  };
  walk(tree);
  return [...urls];
}

function detectBlocked(html) {
  const head = html.slice(0, 6000);
  if (/wappoc_appmsgcaptcha/.test(html)) return 'captcha';
  for (const p of DELETED_PATTERNS) {
    if (p.re.test(head)) return p.reason;
  }
  return null;
}

/**
 * 解析文章页。
 * @param {string} html 页面 HTML
 * @param {string} url 文章链接（用于回填 biz/mid/idx/sn）
 * @returns {{ok:boolean, reason?:string, article?:object}}
 */
function parseArticlePage(html, url) {
  const tree = parseHTML(html);
  const contentNode = findContentNode(tree);

  const blocked = detectBlocked(html);
  if (!contentNode || blocked) {
    const reason = blocked || 'no_content';
    return {
      ok: false,
      reason,
      hint:
        reason === 'captcha'
          ? '被微信人机验证拦截，需要用浏览器打开一次（--browser）'
          : reason === 'deleted'
            ? '文章已被发布者删除'
            : reason === 'violation'
              ? '文章因违规无法查看'
              : reason === 'no_content'
                ? '页面里没有找到正文容器（可能不是图文文章，或被降级成提示页）'
                : '页面返回异常',
    };
  }

  const contentMarkdown = nodeToMarkdown(contentNode, {});
  const paragraphs = contentMarkdown ? contentMarkdown.split('\n\n').filter(Boolean).length : 0;

  const title =
    grabVar(html, 'msg_title') ||
    metaTag(html, 'og:title') ||
    findText(tree, 'activity-name') ||
    findTagText(html, 'title') ||
    '';

  const account = grabVar(html, 'nickname') || findText(tree, 'js_name') || '';
  const author = grabVar(html, 'author') || metaTag(html, 'og:article:author') || '';
  const digest = grabVar(html, 'msg_desc') || metaTag(html, 'description') || '';
  const ctRaw = grabVar(html, 'ct');
  const publishTs = /^\d{9,13}$/.test(ctRaw) ? Number(ctRaw) : null;
  const commentId = normalizeCommentId(grabVar(html, 'comment_id'));
  const cover = metaTag(html, 'og:image') || grabVar(html, 'ori_head_img_url') || '';
  const biz = grabVar(html, 'biz') || grabVar(html, 'user_name') || '';
  const appmsgToken = grabVar(html, 'appmsg_token') || '';

  let params = {};
  try {
    const u = new URL(url);
    params = {
      biz: u.searchParams.get('__biz') || '',
      mid: u.searchParams.get('mid') || '',
      idx: u.searchParams.get('idx') || '1',
      sn: u.searchParams.get('sn') || '',
    };
  } catch {
    params = {};
  }

  return {
    ok: true,
    article: {
      url,
      biz: params.biz || biz,
      mid: params.mid,
      idx: params.idx || '1',
      sn: params.sn,
      title: title.trim(),
      account: account.trim(),
      author: author.trim(),
      digest: digest.trim(),
      publish_ts: publishTs,
      publish_time: publishTs ? formatChinaTime(publishTs * 1000) : '',
      cover,
      comment_id: commentId,
      appmsg_token: appmsgToken,
      content_markdown: contentMarkdown,
      content_length: contentMarkdown.length,
      paragraph_count: paragraphs,
      images: collectImages(contentNode),
      word_count: countWords(contentMarkdown),
    },
  };
}

function normalizeCommentId(raw) {
  const v = String(raw || '').trim();
  if (!v || v === '0') return '';
  return /^\d{6,}$/.test(v) ? v : '';
}

function findText(tree, idOrClass) {
  const node = findNode(
    tree,
    (n) => n.attrs && (n.attrs.id === idOrClass || (n.attrs.class || '').includes(idOrClass))
  );
  if (!node) return '';
  return require('./html2md').textContent(node).replace(/\s+/g, ' ').trim();
}

function findTagText(html, tag) {
  const m = new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`, 'i').exec(html);
  return m ? require('./html2md').htmlToText(m[1]) : '';
}

function countWords(md) {
  const text = String(md || '')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#>*`~\-]/g, ' ');
  const cjk = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
  const words = (text.replace(/[\u4e00-\u9fa5]/g, ' ').match(/[A-Za-z0-9]+/g) || []).length;
  return cjk + words;
}

function formatChinaTime(ms) {
  const d = new Date(ms + 8 * 3600 * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

module.exports = { parseArticlePage, grabVar, formatChinaTime, detectBlocked, normalizeCommentId, normalizeMarkdown };
