'use strict';

/**
 * 零依赖 HTML → Markdown。
 *
 * 之所以自己写：微信正文里 <section>/<span> 嵌套极深、内联样式满天飞，
 * 正则粗暴替换会产出大量碎片；这里先建一棵轻量 DOM 树再递归渲染，结果稳定得多。
 */

const VOID_TAGS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
  'meta', 'param', 'source', 'track', 'wbr', 'mpvoice', 'mp-common-video', 'mp-common-profile',
]);

const BLOCK_TAGS = new Set([
  'address', 'article', 'aside', 'blockquote', 'center', 'dd', 'div', 'dl', 'dt',
  'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'header', 'hr', 'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'tbody',
  'td', 'tfoot', 'th', 'thead', 'tr', 'ul',
]);

// 整块丢弃的标签
const DROP_TAGS = new Set(['script', 'style', 'noscript', 'template', 'svg', 'canvas', 'button', 'select', 'textarea']);

// 内容按原始文本处理的标签（内部不做标签解析）
const RAW_TEXT_TAGS = new Set(['script', 'style', 'textarea', 'title']);

const NAMED_ENTITIES = {
  nbsp: ' ', ensp: ' ', emsp: ' ', thinsp: ' ', ldquo: '“', rdquo: '”', lsquo: '‘',
  rsquo: '’', hellip: '…', mdash: '—', ndash: '–', middot: '·', bull: '•',
  copy: '©', reg: '®', trade: '™', deg: '°', plusmn: '±', times: '×', divide: '÷',
  laquo: '«', raquo: '»', amp: '&', lt: '<', gt: '>', quot: '"', apos: "'",
  zwj: '', zwnj: '', shy: '',
};

function decodeEntities(str) {
  if (!str) return '';
  return str
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => safeCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => safeCodePoint(parseInt(d, 10)))
    .replace(/&([a-zA-Z][a-zA-Z0-9]*);/g, (m, name) => {
      const key = name.toLowerCase();
      return Object.prototype.hasOwnProperty.call(NAMED_ENTITIES, key) ? NAMED_ENTITIES[key] : m;
    });
}

function safeCodePoint(n) {
  try {
    return String.fromCodePoint(n);
  } catch {
    return '';
  }
}

/** 找到标签结束位置，跳过属性值中的 '>' */
function findTagEnd(html, start) {
  let quote = null;
  for (let i = start; i < html.length; i++) {
    const ch = html[i];
    if (quote) {
      if (ch === quote) quote = null;
    } else if (ch === '"' || ch === "'") {
      quote = ch;
    } else if (ch === '>') {
      return i;
    }
  }
  return html.length - 1;
}

const ATTR_RE = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>`=]+))/g;
const BARE_ATTR_RE = /(?:^|\s)([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?=\s|$)/g;

function parseAttrs(source) {
  const attrs = {};
  for (const m of source.matchAll(ATTR_RE)) {
    const name = m[1].toLowerCase();
    const value = m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : m[4] !== undefined ? m[4] : '';
    attrs[name] = decodeEntities(value);
  }
  // 无值属性（如 <td nowrap>）
  for (const m of source.matchAll(BARE_ATTR_RE)) {
    const name = m[1].toLowerCase();
    if (!(name in attrs)) attrs[name] = '';
  }
  return attrs;
}

/** 把 HTML 解析成 { tag, attrs, children } 树 */
function parseHTML(html) {
  const root = { tag: 'root', attrs: {}, children: [] };
  const stack = [root];
  const src = String(html || '');
  let i = 0;

  const pushText = (text) => {
    if (!text) return;
    stack[stack.length - 1].children.push({ tag: '#text', value: decodeEntities(text) });
  };

  while (i < src.length) {
    const lt = src.indexOf('<', i);
    if (lt === -1) {
      pushText(src.slice(i));
      break;
    }
    if (lt > i) pushText(src.slice(i, lt));

    // 注释 / CDATA / DOCTYPE
    if (src.startsWith('<!--', lt)) {
      const end = src.indexOf('-->', lt + 4);
      i = end === -1 ? src.length : end + 3;
      continue;
    }
    if (src.startsWith('<![CDATA[', lt)) {
      const end = src.indexOf(']]>', lt + 9);
      pushText(src.slice(lt + 9, end === -1 ? src.length : end));
      i = end === -1 ? src.length : end + 3;
      continue;
    }
    if (src[lt + 1] === '!' || src[lt + 1] === '?') {
      i = findTagEnd(src, lt) + 1;
      continue;
    }

    const gt = findTagEnd(src, lt);
    const inner = src.slice(lt + 1, gt).trim();
    if (!inner) {
      i = gt + 1;
      continue;
    }

    const isClose = inner[0] === '/';
    const nameMatch = inner.replace(/^\//, '').match(/^([a-zA-Z][a-zA-Z0-9:-]*)/);
    if (!nameMatch) {
      i = gt + 1;
      continue;
    }
    const tag = nameMatch[1].toLowerCase();
    const selfClosing = /\/$/.test(inner);

    if (isClose) {
      for (let d = stack.length - 1; d > 0; d--) {
        if (stack[d].tag === tag) {
          stack.length = d;
          break;
        }
      }
      i = gt + 1;
      continue;
    }

    const attrSource = inner.slice(nameMatch[0].length).replace(/\/$/, '');
    const node = { tag, attrs: parseAttrs(attrSource), children: [] };
    stack[stack.length - 1].children.push(node);

    // script/style 等原始文本元素：内部可能含 '<'、'>'、引号，
    // 必须整段跳到对应闭合标签，否则会打乱整棵树的层级。
    if (RAW_TEXT_TAGS.has(tag)) {
      const closeRe = new RegExp(`</${tag}\\s*>`, 'i');
      const rest = src.slice(gt + 1);
      const m = closeRe.exec(rest);
      if (m) {
        node.children.push({ tag: '#text', value: rest.slice(0, m.index) });
        i = gt + 1 + m.index + m[0].length;
        continue;
      }
    }

    if (!selfClosing && !VOID_TAGS.has(tag)) stack.push(node);
    i = gt + 1;
  }

  return root;
}

function styleOf(node) {
  return (node.attrs && node.attrs.style ? node.attrs.style : '').toLowerCase();
}

function isHidden(node) {
  const style = styleOf(node);
  if (/display\s*:\s*none/.test(style)) return true;
  // 注意：不把 visibility:hidden 当隐藏 —— 微信正文容器本身就用它做淡入动画，
  // 按它过滤会把整篇正文丢掉。
  if (node.attrs && 'hidden' in node.attrs) return true;
  return false;
}

function pickImgSrc(attrs) {
  const candidates = [attrs['data-src'], attrs['data-original'], attrs.src];
  for (const c of candidates) {
    if (!c) continue;
    // 微信会在图片 URL 末尾拼 "#imgIndex=n" 用于懒加载定位，对下游无意义
    const v = c.trim().replace(/#.*$/, '');
    if (!v) continue;
    if (/^data:/i.test(v)) continue;
    if (/^javascript:/i.test(v)) continue;
    return v;
  }
  return null;
}

function absolutize(href) {
  if (!href) return '';
  const v = href.trim();
  if (!v || v === '#' || /^javascript:/i.test(v)) return '';
  if (/^\/\//.test(v)) return 'https:' + v;
  if (/^\/s(-|\/|\?)/.test(v) || v.startsWith('/mp/')) return 'https://mp.weixin.qq.com' + v;
  if (/^https?:\/\//i.test(v)) return v;
  if (/^mp\.weixin\.qq\.com/i.test(v)) return 'https://' + v;
  return '';
}

function textContent(node) {
  if (node.tag === '#text') return node.value || '';
  if (!node.children) return '';
  return node.children.map(textContent).join('');
}

function renderChildren(node, ctx) {
  if (!node.children) return '';
  return node.children.map((child) => renderNode(child, ctx)).join('');
}

function wrapInline(text, marker) {
  const trimmed = text.trim();
  if (!trimmed) return '';
  return marker + trimmed + marker;
}

function renderList(node, ctx) {
  const ordered = node.tag === 'ol';
  const items = (node.children || []).filter((c) => c.tag === 'li');
  let index = 0;
  const lines = [];
  for (const li of items) {
    index += 1;
    const body = renderChildren(li, ctx).trim().replace(/\n{2,}/g, '\n');
    if (!body) continue;
    const prefix = ordered ? `${index}. ` : '- ';
    const [first, ...rest] = body.split('\n');
    lines.push(prefix + first.trim());
    for (const line of rest) lines.push(line.trim() ? '  ' + line.trim() : '');
  }
  return lines.length ? lines.join('\n') + '\n\n' : '';
}

function renderTable(node) {
  const rows = [];
  const walk = (n) => {
    for (const c of n.children || []) {
      if (c.tag === 'tr') rows.push(c);
      else if (c.tag === 'thead' || c.tag === 'tbody' || c.tag === 'tfoot') walk(c);
    }
  };
  walk(node);
  if (!rows.length) return '';

  const matrix = rows.map((tr) =>
    (tr.children || [])
      .filter((c) => c.tag === 'td' || c.tag === 'th')
      .map((cell) => textContent(cell).replace(/\s+/g, ' ').replace(/\|/g, '\\|').trim())
  ).filter((r) => r.length);

  if (!matrix.length) return '';
  const width = Math.max(...matrix.map((r) => r.length));
  const pad = (r) => {
    const copy = r.slice();
    while (copy.length < width) copy.push('');
    return copy;
  };
  const lines = [];
  lines.push('| ' + pad(matrix[0]).join(' | ') + ' |');
  lines.push('| ' + Array(width).fill('---').join(' | ') + ' |');
  for (const row of matrix.slice(1)) lines.push('| ' + pad(row).join(' | ') + ' |');
  return lines.join('\n') + '\n\n';
}

function renderNode(node, ctx) {
  if (!node) return '';

  if (node.tag === '#text') {
    const text = node.value || '';
    if (!text.trim()) return /\s/.test(text) ? ' ' : '';
    return text.replace(/\s+/g, ' ');
  }

  if (DROP_TAGS.has(node.tag)) return '';
  if (isHidden(node)) return '';

  if (ctx.imageMap && node.tag === 'img') {
    const src = pickImgSrc(node.attrs || {});
    if (!src) return '';
    const w = Number(node.attrs['data-w'] || node.attrs.width || 0);
    if (w && w < 60) return ''; // 装饰性小图/占位图
    const mapped = ctx.imageMap.get(src);
    const alt = (node.attrs.alt || '').replace(/[\r\n]+/g, ' ').trim();
    return `\n\n![${alt}](${mapped || src})\n\n`;
  }

  if (node.tag === 'img') {
    const src = pickImgSrc(node.attrs || {});
    if (!src) return '';
    const w = Number(node.attrs['data-w'] || node.attrs.width || 0);
    if (w && w < 60) return '';
    const alt = (node.attrs.alt || '').replace(/[\r\n]+/g, ' ').trim();
    return `\n\n![${alt}](${src})\n\n`;
  }

  switch (node.tag) {
    case 'br':
      return '\n';
    case 'hr':
      return '\n\n---\n\n';
    case 'h1':
      return '\n\n# ' + renderChildren(node, ctx).trim() + '\n\n';
    case 'h2':
      return '\n\n## ' + renderChildren(node, ctx).trim() + '\n\n';
    case 'h3':
      return '\n\n### ' + renderChildren(node, ctx).trim() + '\n\n';
    case 'h4':
      return '\n\n#### ' + renderChildren(node, ctx).trim() + '\n\n';
    case 'h5':
      return '\n\n##### ' + renderChildren(node, ctx).trim() + '\n\n';
    case 'h6':
      return '\n\n###### ' + renderChildren(node, ctx).trim() + '\n\n';
    case 'strong':
    case 'b':
      return wrapInline(renderChildren(node, ctx), '**');
    case 'em':
    case 'i':
      return wrapInline(renderChildren(node, ctx), '*');
    case 'del':
    case 's':
    case 'strike':
      return wrapInline(renderChildren(node, ctx), '~~');
    case 'code': {
      const code = textContent(node).trim();
      if (!code) return '';
      if (code.includes('\n')) return '\n\n```\n' + code + '\n```\n\n';
      return '`' + code + '`';
    }
    case 'pre': {
      const code = textContent(node).replace(/^\n+|\n+$/g, '');
      if (!code.trim()) return '';
      return '\n\n```\n' + code + '\n```\n\n';
    }
    case 'blockquote': {
      const body = renderChildren(node, ctx).trim().replace(/\n{3,}/g, '\n\n');
      if (!body) return '';
      const quoted = body
        .split('\n')
        .map((line) => (line.trim() ? '> ' + line.trim() : '>'))
        .join('\n')
        // 连续的空引用行压成一行，避免出现 "> > >"
        .replace(/(?:^>\n){2,}/gm, '>\n');
      return '\n\n' + quoted + '\n\n';
    }
    case 'ul':
    case 'ol':
      return '\n\n' + renderList(node, ctx) + '\n\n';
    case 'table':
      return '\n\n' + renderTable(node) + '\n\n';
    case 'a': {
      const href = absolutize(node.attrs.href);
      const label = renderChildren(node, ctx).trim();
      if (!label) return '';
      if (!href) return label;
      return `[${label}](${href})`;
    }
    case 'mpvoice':
      return '\n\n> [语音] ' + (node.attrs.name || node.attrs.voice_encode_fileid || '') + '\n\n';
    case 'mp-common-video':
      return '\n\n> [视频] ' + (node.attrs['data-mpvid'] || '') + '\n\n';
    case 'iframe':
      return '\n\n> [内嵌内容] ' + (node.attrs.src || '') + '\n\n';
    default:
      break;
  }

  const inner = renderChildren(node, ctx);

  if (BLOCK_TAGS.has(node.tag)) {
    const trimmed = inner.trim();
    if (!trimmed) return '';
    // 图片块自带空行，避免重复堆叠
    if (/^!\[[^\]]*\]\([^)]*\)$/.test(trimmed)) return '\n\n' + trimmed + '\n\n';
    return '\n\n' + trimmed + '\n\n';
  }

  return inner;
}

/** 规范化 markdown：压缩空行、清理行尾空格 */
function normalizeMarkdown(md) {
  return String(md || '')
    .replace(/\r\n/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\n+/, '')
    .replace(/\n+$/, '') + '\n';
}

/**
 * HTML → Markdown
 * @param {string} html
 * @param {{imageMap?: Map<string,string>}} [options] imageMap 用于把远程图片改写成本地相对路径
 */
function htmlToMarkdown(html, options = {}) {
  return nodeToMarkdown(parseHTML(html), options);
}

/** 对已解析好的节点树渲染 Markdown（正文抽取时复用，避免二次解析） */
function nodeToMarkdown(tree, options = {}) {
  const ctx = { imageMap: options.imageMap || null };
  return normalizeMarkdown(renderChildren(tree, ctx));
}

/** HTML → 纯文本（摘要、校验用） */
function htmlToText(html) {
  const tree = parseHTML(html);
  const ctx = { imageMap: null };
  return renderChildren(tree, ctx)
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[#>*`~]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

module.exports = { parseHTML, htmlToMarkdown, nodeToMarkdown, htmlToText, decodeEntities, textContent, normalizeMarkdown };
