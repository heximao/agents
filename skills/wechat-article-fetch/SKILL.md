---
name: wechat-article-fetch
description: "采集微信公众号文章正文与留言。输入一条公众号文章链接（或整段分享文案、一批链接、剪贴板内容），自动识别链接形态、抓取正文并转成干净 Markdown、下载正文图片、按需采集精选留言，产出 article.md + article.json。当用户提到公众号文章链接、想把公众号文章存下来/导出/归档/转 Markdown、复制分享文案要正文、抓文章评论或留言、批量采集公众号文章时必须使用本技能；即使用户没说“采集”二字，只要给的是 mp.weixin.qq.com 链接且想要里面的内容，就用它。注意：按关键词搜索文章请用 wechat-article-search，本技能只负责“已有链接 → 取内容”。"
description_zh: "识别微信公众号文章链接，采集正文、图片与留言，输出 Markdown + JSON"
description_en: "Fetch WeChat official-account article body, images and comments from a URL"
version: 0.1.0
allowed-tools: Bash,Read
metadata:
  clawdbot:
    emoji: "\U0001F4F0"
    requires:
      bins:
        - node
display_name: "微信公众号文章采集"
display_name_en: "wechat-article-fetch"
visibility: "public"
---

# 微信公众号文章采集

一句话定位：**给链接，取内容**。识别链接 → 抓正文 → 转 Markdown → 下载图片 → 按需抓留言 → 落盘。

## 能力边界（先看这段，别承诺做不到的事）

| 能力 | 是否可用 | 说明 |
| --- | --- | --- |
| 识别链接（短链 / 完整链接 / 分享文案 / 批量） | ✅ 稳定 | 纯本地正则，无需联网 |
| 正文 + 元信息（标题/公众号/作者/时间/摘要） | ✅ 多数情况可用 | 取决于链接形态与当前 IP 风控状态，见下 |
| 正文图片下载与本地化 | ✅ 可用 | `--images` 开启 |
| 精选留言 | ⚠️ 需微信会话凭证 | 匿名请求固定返回 `ret=-3 no session`，这是接口设计 |
| 阅读量 / 点赞数 | ❌ 不做 | 需登录态，且微信已对多数账号关闭外显 |
| 未被作者选出的留言 | ❌ 任何手段都拿不到 | 公众号只对外暴露精选留言 |

### 链接形态与成功率（实测结论）

1. **短链** `https://mp.weixin.qq.com/s/AbCdEfGh...` —— 成功率最高，免登录可直抓。用户从微信「分享 → 复制链接」得到的通常是这种。
2. **完整链接 + chksm** `...&sn=..&chksm=..` —— 通常可直抓。
3. **完整链接缺 chksm** `...&__biz=..&mid=..&idx=..&sn=..` —— 微信几乎必然 302 到 `wappoc_appmsgcaptcha` 人机验证页。脚本会先标红提醒，再自动降级浏览器（headless 常常过不去，`--headed` 打开窗口手动过一次验证才稳）。

遇到第 3 种，最有效的解法是**换链接**：让用户回到公众号文章，用「分享 → 复制链接」拿短链，而不是复制正文里的引用链接。

## 工作流程

脚本零第三方依赖（只需 `node`），浏览器兜底才需要 playwright（本机通常已随 `@playwright/cli` 提供）。

### 1. 先识别，确认抓的是哪几条

```bash
node scripts/wx_article.js detect "<文本或链接>"
```

输出 `{count, links:[{url, kind, key, params}]}`。`kind` 为 `short` / `param`。这一步不联网，用于确认链接没被截断、批量时条数对不对。

### 2. 采集

```bash
# 单篇：直接贴链接或整段分享文案
node scripts/wx_article.js fetch "https://mp.weixin.qq.com/s/AbCdEfGh"

# 剪贴板（macOS）：用户说“这条链接存一下”时最省事
node scripts/wx_article.js fetch --clipboard

# 批量：一个文件多行链接 / 整段聊天记录
node scripts/wx_article.js fetch --input-file links.txt --out ./archive

# 需要图片落地、不要留言
node scripts/wx_article.js fetch "<链接>" --images --no-comments
```

默认输出目录 `./wechat-mp-output/`，每篇一个子目录：`<日期>-<公众号>-<标题>/`，内含 `article.md`、`article.json`（`--images` 时再加 `images/`）。

### 3. 把结果讲给用户

命令的 stdout 是 JSON 摘要（`items[]` 含 title / word_count / images / comments / saved_to / error）。按下面口径汇报：

- 成功：标题、公众号、字数、图片数、保存路径
- 留言：`comments.available=false` 时如实说「留言没采到：需要微信会话凭证」，**不要**说成“没有留言”
- 失败：直接给 `error` 与 `hint`，并提示换短链

## 参数

| 参数 | 作用 |
| --- | --- |
| `--out <dir>` | 输出目录，默认 `./wechat-mp-output` |
| `--no-comments` | 只抓正文（默认会尝试抓留言） |
| `--images` | 下载正文图片到 `images/` 并改写 Markdown 链接 |
| `--browser` | 强制走浏览器 |
| `--http-only` | 只用 HTTP，不降级浏览器（快，但风控下会直接失败） |
| `--headed` | 浏览器有头模式，用于手动过验证；验证结果写入持久化 profile |
| `--profile <dir>` | 浏览器 profile 目录（默认 skill 目录下 `.profile`） |
| `--limit <n>` | 批量时只处理前 n 条 |
| `--delay <ms>` | 批量间隔，默认约 `3000/n`，最低 1500ms |
| `--max-comments-pages <n>` | 留言翻页上限，默认 10 页 × 100 条 |
| `--json` / `--print` | 完整 JSON / Markdown 输出到 stdout |
| `--input-file` / `--clipboard` / `--stdin` | 输入来源，可与位置参数组合 |

## 留言采集

留言接口 `/mp/appmsg_comment?action=getcomment` 需要真实微信会话，参数为 `uin` + `key`/`pass_ticket` + 页面里的 `appmsg_token`。没有凭证时脚本会返回 `comments.reason = "no_session"`，并在 Markdown 里写明原因——这是**预期行为**，不是故障。

配置凭证的三种方式（细节见 `references/wechat-session.md`）：

```bash
# 1. JSON 凭证文件（推荐，放在 scripts/../.creds.json 会被自动读取）
#    {"cookie":"...","uin":"...","key":"...","pass_ticket":"..."}
node scripts/wx_article.js fetch "<链接>" --creds-file ~/.wechat-creds.json

# 2. 命令行
node scripts/wx_article.js fetch "<链接>" --cookie "uin=xx; key=xx" --uin xx --key xx --pass-ticket xx

# 3. 环境变量
WX_MP_COOKIE / WX_MP_UIN / WX_MP_KEY / WX_MP_PASS_TICKET
```

另一个免配凭证的路径：若某浏览器 profile 里已登录过微信文章页，用 `--browser --profile <该目录>` 打开页面后，脚本会在页面上下文内 `fetch` 留言接口，从而继承登录态。成功率取决于该 profile 的会话是否仍有效。

## 常见问题

- **`http: captcha; browser: captcha_timeout`** —— 链接缺 chksm 且当前 IP 被风控。换短链，或 `--headed` 手动过一次验证（通过后 profile 会记住）。
- **`playwright_missing` / `launch_failed`** —— 浏览器兜底不可用。启动策略依次尝试系统 Chrome → playwright 自带 chromium → 本机 `ms-playwright` 缓存中的可执行文件；都失败再执行 `npx playwright install chromium`。
- **`no_content`** —— 文章已删除、违规屏蔽、或本身就是非图文内容。
- **标题与网页显示不一致** —— 微信会对部分请求返回“改写标题”（引号位置重排），属数据源行为，不是解析错误。
- **批量时后半段开始失败** —— 触发了频率限制。加大 `--delay`，或分批抓，不要连环重试。

## 与其他技能的关系

- `wechat-article-search`：按关键词**找**文章（搜狗微信搜索），返回链接列表。要采集它搜到的文章时，把链接交给本技能。
- `wx` CLI（`wx biz-articles`）：从本地微信缓存列出已收到的公众号文章链接，可作为本技能的批量输入源。

## 注意事项

- 仅用于个人学习、归档与内容整理；遵守微信平台条款，控制频率，不要大规模爬取。
- 正文与留言的版权归原作者与公众号所有，产出物保留原文链接与公众号署名。
