---
name: md2wechat
description: Convert Markdown to WeChat Official Account HTML. Supports AI mode (free, themed layouts). Features writer style assistant, AI trace removal (humanizer), and draft upload.
---

# MD to WeChat

将 Markdown 文章转换为微信公众号格式并自动上传到草稿箱。

> **重要说明**：在 OpenCode 中，AI 模式完全免费，无需任何 API Key。Claude 直接生成精美排版。

## 快速使用（自然语言）

直接告诉我要做什么：

```
"把 article.md 转换为微信公众号格式"
"用深海静谧主题转换这篇文章并发送到草稿箱"
```

## AI 模式工作原理

在使用这个 skill 时，我会：

1. **读取 Markdown** → 分析文章结构、提取元数据
2. **生成 HTML** → 根据选定主题，生成带内联 CSS 的微信格式 HTML
3. **上传封面** → 调用微信 API 上传图片
4. **创建草稿** → 推送到微信公众号后台

**全部由 AI 完成，无需外部 API Key。**

## 主题选择

| 主题 | 风格 | 适合内容 |
|------|------|----------|
| `autumn-warm` (秋日暖光) | 温暖橙色调 | 情感故事、生活随笔 |
| `spring-fresh` (春日清新) | 清新绿色调 | 旅行日记、自然主题 |
| `ocean-calm` (深海静谧) | 专业蓝色调 | 技术文章、商业分析 |

## 使用方法

### 发送到草稿箱（最常用）

```
"把 [文章路径] 发送到微信草稿箱，主题用 [主题名]，封面用 [封面图路径]"
```

### 仅预览 HTML

```
"把 [文章路径] 转换为微信公众号格式预览"
```

## 必需配置

只需要微信公众号的 AppID 和 Secret：

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| AppID | 公众号唯一标识 | 微信公众平台 → 设置与开发 → 基本配置 |
| Secret | API 密钥 | 同上，需管理员权限 |

### 配置方法

```bash
# 初始化配置文件
md2wechat config init

# 然后编辑配置文件
open ~/.config/md2wechat/config.yaml
```

### 单账号配置

```yaml
wechat:
  appid: 你的AppID
  secret: 你的Secret
```

### 多账号配置

```yaml
# 默认账号（不指定时使用）
wechat:
  appid: wx1234567890
  secret: your_secret_here

# 多账号列表
accounts:
  赛博野人:
    appid: wx1234567890
    secret: your_secret_here
  另一个账号:
    appid: wx0987654321
    secret: another_secret
```

**使用时指定账号**：

```
"把文章发送到 [账号名] 的草稿箱"
"用赛博野人账号发送这篇文章到草稿箱"
```

如果不指定，默认使用 `wechat` 下的账号。

## 微信 HTML 规范

生成 HTML 时遵循以下规则：

1. **内联 CSS**：所有样式使用 `style` 属性
2. **安全标签**：`<p>`, `<h1>`-`<h6>`, `<section>`, `<blockquote>`, `<ul>`, `<ol>`
3. **避免**：`<script>`, `<iframe>`, 外部样式表
4. **颜色显式指定**：每个 `<p>` 必须指定 `color`，微信会重置为黑色

## 故障排除

### "IP not in whitelist"

在微信公众平台添加当前 IP 到白名单：

1. 登录 [微信公众平台](https://mp.weixin.qq.com)
2. 设置与开发 → 基本配置 → IP白名单
3. 添加你的公网 IP

获取公网 IP：
```bash
curl ifconfig.me
```

### 图片无法显示

确保图片已上传到微信素材库，使用 `mmbiz.qpic.cn` 域名的 URL。

## 参考资料

- [GitHub 仓库](https://github.com/geekjourneyx/md2wechat-skill)
- [详细文档](https://github.com/geekjourneyx/md2wechat-skill#readme)
