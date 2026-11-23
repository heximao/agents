'use strict';

/**
 * 输出层：组装 Markdown / JSON，落盘，可选的图片本地化。
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

function pad(n) {
  return String(n).padStart(2, '0');
}

function stampNow() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function dateNow() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const ILLEGAL = /[\\/:*?"<>|\r\n\t]/g;

function slugify(text, maxLen = 48) {
  const cleaned = String(text || '')
    .replace(ILLEGAL, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const cut = cleaned.length > maxLen ? cleaned.slice(0, maxLen).trim() : cleaned;
  return cut || 'untitled';
}

function extFromContentType(ct = '') {
  const t = String(ct).toLowerCase();
  if (t.includes('png')) return '.png';
  if (t.includes('gif')) return '.gif';
  if (t.includes('webp')) return '.webp';
  if (t.includes('svg')) return '.svg';
  return '.jpg';
}

function downloadOne(url, destBase, ua) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (v) => {
      if (!settled) {
        settled = true;
        resolve(v);
      }
    };
    let req;
    try {
      req = https.get(url, { headers: { 'User-Agent': ua, Accept: 'image/*,*/*' }, timeout: 20000 }, (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          done(null);
          return;
        }
        const ext = extFromContentType(res.headers['content-type']);
        const file = destBase + ext;
        const stream = fs.createWriteStream(file);
        res.pipe(stream);
        stream.on('finish', () => {
          stream.close(() => done(fs.existsSync(file) ? file : null));
        });
        stream.on('error', () => done(null));
      });
      req.on('error', () => done(null));
      req.on('timeout', () => {
        req.destroy();
        done(null);
      });
    } catch {
      done(null);
    }
  });
}

/**
 * 下载正文图片到 images/，返回 原URL → 相对路径 的映射。
 */
async function downloadImages(urls, dir, options = {}) {
  const { concurrency = 4, ua = 'Mozilla/5.0' } = options;
  fs.mkdirSync(dir, { recursive: true });
  const map = new Map();
  const queue = [...new Set(urls)];

  let idx = 0;
  const worker = async () => {
    while (queue.length) {
      const url = queue.shift();
      idx += 1;
      const base = path.join(dir, String(idx).padStart(3, '0'));
      const file = await downloadOne(url, base, ua);
      if (file) map.set(url, 'images/' + path.basename(file));
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, queue.length || 1) }, worker));
  return map;
}

function commentBlock(comments) {
  if (!comments) return '## 留言\n\n> 未尝试采集留言。\n';

  if (!comments.available) {
    const reasonText =
      comments.reason === 'no_comment_id'
        ? '文章没有留言区（未开通留言，或页面未返回 comment_id）'
        : comments.reason === 'no_session'
          ? '留言接口需要微信会话凭证（uin + key/pass_ticket），匿名访问无法读取。可参考 references/wechat-session.md 配置凭证后重试。'
          : comments.hint || `采集失败：${comments.reason || 'unknown'}`;
    return `## 留言\n\n> 未采集到留言：${reasonText}\n`;
  }

  const items = comments.items || [];
  if (!items.length) {
    return `## 留言\n\n> 接口可用，但该文章的精选留言为空（总留言数 ${comments.total || 0}）。\n`;
  }

  const head = `## 留言（${items.length}/${comments.total || items.length}）\n`;
  const parts = [head];

  if (comments.truncated) {
    parts.push(`> 说明：接口报告共 ${comments.total} 条精选留言，本次采集 ${items.length} 条${comments.truncated_reason ? `（翻页提前结束：${comments.truncated_reason}）` : ''}。\n`);
  }

  for (const c of items) {
    const meta = [
      c.nickname || '匿名',
      `赞 ${c.like_num}`,
      c.create_time,
      c.ip_location,
      c.is_top ? '置顶' : '',
    ]
      .filter(Boolean)
      .join(' · ');
    parts.push(`### ${c.index}. ${meta}`);
    const body = (c.content || '').split('\n').map((l) => '> ' + l).join('\n');
    parts.push(body);
    if (c.replies && c.replies.length) {
      parts.push(`\n**作者/其他回复（${c.replies.length}）**\n`);
      for (const r of c.replies) {
        const rmeta = [r.nickname || '匿名', r.like_num ? `赞 ${r.like_num}` : '', r.create_time].filter(Boolean).join(' · ');
        parts.push(`- ${rmeta}：${(r.content || '').replace(/\n+/g, ' ')}`);
      }
    }
    parts.push('');
  }

  return parts.join('\n');
}

/**
 * @param {object} record 采集结果
 * @param {{includeComments?:boolean, sourceLabel?:string}} options
 */
function buildMarkdown(record, options = {}) {
  const lines = [];
  lines.push(`# ${record.title || '(无标题)'}`);
  lines.push('');

  const meta = [];
  if (record.account) meta.push(`**公众号**：${record.account}`);
  if (record.author) meta.push(`**作者**：${record.author}`);
  if (record.publish_time) meta.push(`**发布时间**：${record.publish_time}`);
  meta.push(`**采集时间**：${record.fetched_at || stampNow()}`);
  meta.push(`**原文链接**：${record.url}`);
  if (record.word_count) meta.push(`**字数**：${record.word_count}`);
  if (record.images && record.images.length) meta.push(`**图片**：${record.images.length} 张`);
  if (record.digest) meta.push(`**摘要**：${record.digest}`);
  lines.push(meta.join('  \n'));
  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push(record.content_markdown ? record.content_markdown.trim() : '> 正文为空');
  lines.push('');
  lines.push('---');
  lines.push('');

  if (options.includeComments !== false) {
    lines.push(commentBlock(record.comments));
  }

  if (record.warnings && record.warnings.length) {
    lines.push('');
    lines.push('---');
    lines.push('');
    lines.push('## 采集提示');
    for (const w of record.warnings) lines.push(`- ${w}`);
    lines.push('');
  }

  return lines.join('\n').replace(/\n{4,}/g, '\n\n\n');
}

/**
 * 落盘：<outDir>/<date>-<account>-<title>/ 下存 article.md + article.json (+ images/)
 */
async function persist(record, options = {}) {
  const { outDir = path.resolve('wechat-mp-output'), downloadImageFiles = false, ua } = options;

  const folder = `${(record.publish_time || record.fetched_at || dateNow()).slice(0, 10)}-${slugify(record.account || 'unknown', 20)}-${slugify(record.title, 40)}`;
  const dir = path.join(outDir, folder);
  fs.mkdirSync(dir, { recursive: true });

  let imageMap = null;
  if (downloadImageFiles && record.images && record.images.length) {
    imageMap = await downloadImages(record.images, path.join(dir, 'images'), { ua });
    let i = 0;
    record.content_markdown = String(record.content_markdown || '').replace(
      /!\[([^\]]*)\]\(([^)]+)\)/g,
      (m, alt, src) => {
        const local = imageMap.get(src);
        if (!local) return m;
        i += 1;
        return `![${alt}](${local})`;
      }
    );
    record.local_images = [...imageMap.values()];
  }

  const md = buildMarkdown(record, { includeComments: options.includeComments !== false });
  const mdPath = path.join(dir, 'article.md');
  const jsonPath = path.join(dir, 'article.json');
  fs.writeFileSync(mdPath, md, 'utf-8');
  fs.writeFileSync(jsonPath, JSON.stringify(record, null, 2), 'utf-8');

  return { dir, mdPath, jsonPath, md };
}

module.exports = {
  buildMarkdown,
  persist,
  slugify,
  downloadImages,
  stampNow,
  dateNow,
  pad,
};
