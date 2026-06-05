---
name: Gemini AI 封面生图
description: 当用户需要"生成封面图片"、"AI 生图"、"cover image"、"用 Gemini 画图"或需要为文章批量生成封面时使用该技能。通过 Gemini API（中转站）生成高质量封面图片。
version: 1.0.0
---

# Skill: Gemini AI 封面生图

通过 Gemini API 自动生成文章封面图片。支持中英文 prompt，适用于公众号、雪球等自媒体平台的封面批量生产。

## 核心任务

接收 prompt（中英文皆可），调用 Gemini API 生成图片，保存到指定路径。

## 前置条件

| 环境变量 | 值 | 用途 |
|---------|---|------|
| `GEMINI_API_KEY` | 中转站 Key | API 鉴权 |
| `GEMINI_BASE_URL` | `http://10.0.0.4:3000` | 中转站地址 |
| `GEMINI_MODEL` | `gemini-3-pro-image` | 生图模型 |

环境变量已配置在 `~/.zshrc` 和 `~/.claude/settings.json`，直接通过 `zsh -i -c` 调用即可。

## 执行流程

1. **提炼 Prompt**：根据文章内容/封面 prompt 文件，提取英文描述（Gemini 对英文 prompt 响应更好）。
2. **调用脚本**：使用 `gemini_image.py` 脚本生成图片。
3. **保存输出**：图片保存到项目对应目录，文件命名符合 SPEC 规范。

## 调用方式

```bash
zsh -i -c 'python3 /Users/saibopika/wemedia/07-scripts/gemini_image.py "<English Prompt>" -o /path/to/output.png'
```

### 关键参数

| 参数 | 说明 |
|-----|------|
| `prompt` | 英文图片描述（必填） |
| `-o`, `--output` | 输出 PNG 路径（必填） |

### 批量生成

对多个封面 prompt，依次调用即可。API 有频率限制，建议逐个执行（每个约 10-30 秒）。

```bash
# 示例：为文章生成 10 张封面
zsh -i -c 'python3 /Users/saibopika/wemedia/07-scripts/gemini_image.py "A massive luxury cruise ship..." -o /Users/saibopika/wemedia/03-original/037-covers/cover_01.png'
zsh -i -c 'python3 /Users/saibopika/wemedia/07-scripts/gemini_image.py "Countless glowing AI chips..." -o /Users/saibopika/wemedia/03-original/037-covers/cover_02.png'
# ... 依此类推到 cover_10.png
```

## Prompt 编写要点

1. **英文优先**：Gemini 对英文 prompt 的理解和生成质量显著优于中文。
2. **风格描述**：末尾追加风格关键词，如 `Cinematic quality`、`Cyberpunk aesthetic`、`Minimalist composition`、`Financial illustration style`。
3. **构图指定**：明确视角、光线、色调，如 `Wide-angle lens`、`Golden hour lighting`、`High contrast`。
4. **避免文字**：Gemini 生成的图片中文字通常不清晰，避免在 prompt 中要求图片内嵌文字。
5. **尺寸**：Gemini 默认输出约 1.7-2MB 的 PNG，适合封面使用。

## 输出目录规范

| 用途 | 路径 |
|-----|------|
| 文章封面 | `03-original/037-covers/` |
| 测试图片 | 同上，完成后删除 |

文件名格式：`cover_01.png`、`cover_02.png` … 或使用文章日期前缀。

## 故障排查

| 错误 | 原因 | 处理 |
|-----|------|------|
| `HTTP Error 500` | 中转站网络波动 | 重试，或检查中转站状态 |
| `HTTP Error 401` | API Key 无效 | 检查 `GEMINI_API_KEY` 环境变量 |
| `No image data in response` | 模型未返回图片 | 检查 prompt 是否触发了文本回复而非生图 |
| `json.JSONDecodeError` | 响应格式异常 | 脚本已用 `strict=False`，如仍报错则检查中转站返回格式 |

## 资源导航

### 脚本
- **`/Users/saibopika/wemedia/07-scripts/gemini_image.py`**：Gemini 生图核心脚本（通过 OpenAI-compatible API）

### 参考
- **`references/cover-prompt-guide.md`**：封面 prompt 编写参考（从已有 prompt 文件提炼）

### 示例
- **`examples/batch-generate.md`**：批量生成封面的完整示例
