---
name: imap-mail
description: IMAP 邮件读取与整理工具。用于连接邮箱服务器、拉取邮件内容、智能分类整理并保存为 Markdown 文件。触发场景：(1) 用户要求读取/整理邮件；(2) 用户要求将邮件导出为 Markdown；(3) 用户提到 iCloud/Gmail/QQ邮箱等邮件整理需求。
---
# IMAP Mail

通过 IMAP 协议连接邮箱，拉取邮件内容，分类整理后保存为 Markdown 文件。

## 快速开始

```bash
# 基本用法
python scripts/fetch_mail.py --server <IMAP服务器> --user <邮箱> --password <密码> [options]

# 示例：iCloud 邮箱
python scripts/fetch_mail.py --server imap.mail.me.com --user yourname@icloud.com --password your-app-password

# 示例：Gmail
python scripts/fetch_mail.py --server imap.gmail.com --user yourname@gmail.com --password your-app-password

# 示例：QQ邮箱
python scripts/fetch_mail.py --server imap.qq.com --user your@qq.com --password your-auth-code
```

## 常用邮箱 IMAP 配置

| 邮箱 | IMAP 服务器 | 端口 | 说明 |
|------|-------------|------|------|
| iCloud | imap.mail.me.com | 993 | 需要应用专用密码 |
| Gmail | imap.gmail.com | 993 | 需要应用专用密码 + 开启 IMAP |
| Outlook | outlook.office365.com | 993 | 需要应用密码 |
| QQ邮箱 | imap.qq.com | 993 | 需要授权码 |
| 163邮箱 | imap.163.com | 993 | 需要授权码 |

## 参数说明

| 参数 | 说明 |
|------|------|
| `--server` | IMAP 服务器地址 |
| `--user` | 邮箱账号 |
| `--password` | 密码/应用专用密码/授权码 |
| `--folder` | 邮件文件夹，默认 `INBOX` |
| `--limit` | 拉取邮件数量，默认 10 |
| `--since` | 时间过滤，如 `7d`、`30d`、`2024-01-01` |
| `--output` | 输出目录，默认 `./mail_output` |
| `--format` | 输出格式：`single`（每封一个文件）或 `combined`（合并为一个文件） |

## 输出结构

邮件将按分类保存为 Markdown 文件：

```
mail_output/
├── 2024-01-15/
│   ├── 工作/
│   │   ├── 邮件标题_001.md
│   │   └── 邮件标题_002.md
│   ├── 账单/
│   │   └── 银行账单通知.md
│   └── 未分类/
│       └── 其他邮件.md
└── combined_2024-01-15.md  # 合并文件（可选）
```

## Markdown 格式

每封邮件的 Markdown 格式：

```markdown
# 邮件标题

**发件人**: sender@example.com  
**收件人**: you@example.com  
**日期**: 2024-01-15 10:30  
**分类**: 工作  

---

邮件正文内容...

## 附件
- report.pdf
- image.png
```

## 分类规则

默认分类规则（可在 `references/categories.md` 中自定义）：

- **工作**：包含 "工作"、"会议"、"项目"、"报告" 等关键词
- **账单**：包含 "账单"、"支付"、"发票"、"扣款" 等
- **通知**：包含 "通知"、"提醒"、"验证码"、"激活" 等
- **订阅**：包含 "订阅"、"Newsletter"、"推送" 等
- **个人**：来自已知联系人（需配置）
- **未分类**：无法自动分类的邮件

## 安全提示

1. **不要在命令行直接输入密码** - 使用环境变量或配置文件
2. **应用专用密码** - iCloud/Gmail 等需要在账户设置中生成
3. **配置文件** - 可创建 `~/.imap_config.json` 存储凭据：

```json
{
  "icloud": {
    "server": "imap.mail.me.com",
    "user": "your@icloud.com",
    "password": "xxxx-xxxx-xxxx-xxxx"
  }
}
```

使用配置文件：
```bash
python scripts/fetch_mail.py --profile icloud
```

## Resources

### scripts/
- `fetch_mail.py` - 主脚本，拉取并整理邮件

### references/
- `categories.md` - 分类规则配置
