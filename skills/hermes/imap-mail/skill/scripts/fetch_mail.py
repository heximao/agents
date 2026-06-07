#!/usr/bin/env python3
"""
IMAP Mail Fetcher - 拉取邮件并整理为 Markdown

用法:
    python fetch_mail.py --server imap.gmail.com --user you@gmail.com --password your-app-password
    python fetch_mail.py --profile icloud --limit 20 --since 7d
"""

import argparse
import email
import email.utils
import imaplib
import json
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from typing import Optional

# 默认分类规则
DEFAULT_CATEGORIES = {
    "工作": ["工作", "会议", "项目", "报告", "任务", "deadline", "meeting", "project"],
    "账单": ["账单", "支付", "发票", "扣款", "还款", "银行", "bill", "payment", "invoice"],
    "通知": ["通知", "提醒", "验证码", "激活", "确认", "notification", "verify", "alert"],
    "订阅": ["订阅", "newsletter", "推送", "unsubscribe", "邮件列表", "mailing list"],
    "个人": [],  # 需要配置发件人白名单
}

# 常用邮箱配置
EMAIL_PROVIDERS = {
    "icloud": {"server": "imap.mail.me.com", "port": 993},
    "gmail": {"server": "imap.gmail.com", "port": 993},
    "outlook": {"server": "outlook.office365.com", "port": 993},
    "qq": {"server": "imap.qq.com", "port": 993},
    "163": {"server": "imap.163.com", "port": 993},
    "126": {"server": "imap.126.com", "port": 993},
}


def decode_str(s: str) -> str:
    """解码邮件头字符串"""
    if s is None:
        return ""
    decoded_parts = []
    for part, charset in decode_header(s):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def get_email_body(msg) -> str:
    """提取邮件正文"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                continue
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
                except:
                    pass
            elif content_type == "text/html" and not body:
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                except:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except:
            pass
    # 简单的 HTML 清理
    body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL|re.IGNORECASE)  # 移除 style 标签
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL|re.IGNORECASE)  # 移除 script 标签
    body = re.sub(r'<[^>]+>', ' ', body)  # 移除其他 HTML 标签
    body = re.sub(r'&nbsp;', ' ', body)  # 替换 &nbsp;
    body = re.sub(r'&[a-z]+;', '', body)  # 移除其他 HTML 实体
    body = re.sub(r'\s+', ' ', body).strip()  # 合并多余空白
    # 截断过长的内容
    if len(body) > 5000:
        body = body[:5000] + '...\n[内容已截断，原文较长]'
    return body


def categorize_email(subject: str, sender: str, categories: dict, whitelist: list = None) -> str:
    """根据规则分类邮件"""
    subject_lower = subject.lower()
    sender_lower = sender.lower()

    # 检查个人白名单
    if whitelist:
        for person in whitelist:
            if person.lower() in sender_lower:
                return "个人"

    # 按关键词分类
    for category, keywords in categories.items():
        if category == "个人":
            continue
        for keyword in keywords:
            if keyword.lower() in subject_lower:
                return category

    return "未分类"


def get_attachments(msg) -> list:
    """获取附件列表"""
    attachments = []
    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" in content_disposition:
            filename = part.get_filename()
            if filename:
                attachments.append(decode_str(filename))
    return attachments


def format_date(date_str: str) -> str:
    """格式化邮件日期"""
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except:
        return date_str


def create_markdown(mail_data: dict) -> str:
    """生成 Markdown 内容"""
    md = f"""# {mail_data['subject']}

**发件人**: {mail_data['sender']}
**收件人**: {mail_data['recipient']}
**日期**: {mail_data['date']}
**分类**: {mail_data['category']}

---

{mail_data['body']}
"""

    if mail_data['attachments']:
        md += "\n## 附件\n"
        for att in mail_data['attachments']:
            md += f"- {att}\n"

    return md


def sanitize_filename(name: str) -> str:
    """清理文件名"""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip()
    if len(name) > 100:
        name = name[:100]
    return name or "untitled"


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def parse_since(since: str) -> datetime:
    """解析时间过滤参数"""
    since = since.lower().strip()
    now = datetime.now()

    if since.endswith("d"):
        days = int(since[:-1])
        return now - timedelta(days=days)
    elif since.endswith("w"):
        weeks = int(since[:-1])
        return now - timedelta(weeks=weeks)
    elif since.endswith("m"):
        months = int(since[:-1])
        return now - timedelta(days=months * 30)
    else:
        # 尝试解析日期
        try:
            return datetime.strptime(since, "%Y-%m-%d")
        except:
            return now - timedelta(days=30)


def main():
    parser = argparse.ArgumentParser(description="IMAP 邮件拉取与整理工具")
    parser.add_argument("--server", help="IMAP 服务器地址")
    parser.add_argument("--port", type=int, default=993, help="IMAP 端口,默认 993")
    parser.add_argument("--user", help="邮箱账号")
    parser.add_argument("--password", help="密码/应用密码/授权码")
    parser.add_argument("--profile", help="使用配置文件中的账户")
    parser.add_argument("--config", default="~/.openclaw/imap_config.json", help="配置文件路径")
    parser.add_argument("--folder", default="INBOX", help="邮件文件夹,默认 INBOX")
    parser.add_argument("--limit", type=int, default=10, help="拉取邮件数量")
    parser.add_argument("--since", default="30d", help="时间过滤,如 7d, 30d, 2024-01-01")
    parser.add_argument("--output", default="./mail_output", help="输出目录")
    parser.add_argument("--format", choices=["single", "combined"], default="single", help="输出格式")
    parser.add_argument("--provider", choices=EMAIL_PROVIDERS.keys(), help="预设邮箱提供商")

    args = parser.parse_args()

    # 加载配置
    config = load_config(os.path.expanduser(args.config))

    # 确定连接参数
    if args.profile:
        if args.profile not in config:
            print(f"错误: 配置文件中未找到 profile '{args.profile}'")
            return
        profile = config[args.profile]
        server = profile.get("server")
        port = profile.get("port", 993)
        user = profile.get("user")
        password = profile.get("password")
    elif args.provider:
        provider = EMAIL_PROVIDERS[args.provider]
        server = args.server or provider["server"]
        port = args.port or provider["port"]
        user = args.user
        password = args.password
    else:
        server = args.server
        port = args.port
        user = args.user
        password = args.password

    if not all([server, user, password]):
        print("错误: 请提供服务器、用户名和密码,或使用 --profile/--provider")
        return

    print(f"连接 {server}:{port}...")

    # 连接 IMAP
    try:
        mail = imaplib.IMAP4_SSL(server, port)
        mail.login(user, password)
        print(f"登录成功: {user}")
    except Exception as e:
        print(f"连接失败: {e}")
        return

    # 选择文件夹
    mail.select(args.folder)

    # 搜索邮件
    since_date = parse_since(args.since)
    since_str = since_date.strftime("%d-%b-%Y")
    status, messages = mail.search(None, f'SINCE {since_str}')

    if status != "OK":
        print("搜索邮件失败")
        mail.logout()
        return

    email_ids = messages[0].split()
    total = len(email_ids)
    email_ids = email_ids[-args.limit:]  # 取最新的 N 封

    print(f"找到 {total} 封邮件,处理最新的 {len(email_ids)} 封...")

    # 加载分类规则
    categories = DEFAULT_CATEGORIES
    whitelist = config.get("whitelist", [])

    # 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    date_folder = datetime.now().strftime("%Y-%m-%d")
    combined_md = ""
    processed = 0

    for i, email_id in enumerate(reversed(email_ids)):
        status, msg_data = mail.fetch(email_id, "(FLAGS BODY.PEEK[])")
        if status != "OK":
            continue

        for response in msg_data:
            # 处理 bytes 或 tuple 类型
            if isinstance(response, bytes):
                continue  # 跳过纯 bytes 响应（如 b'1 (RFC822 {size})'）
            if not isinstance(response, tuple):
                continue

            msg = email.message_from_bytes(response[1])

            # 提取邮件信息
            subject = decode_str(msg.get("Subject", "无标题"))
            sender = decode_str(msg.get("From", "未知发件人"))
            recipient = decode_str(msg.get("To", user))
            date = format_date(msg.get("Date", ""))
            body = get_email_body(msg)
            attachments = get_attachments(msg)

            # 分类
            category = categorize_email(subject, sender, categories, whitelist)

            mail_data = {
                "subject": subject,
                "sender": sender,
                "recipient": recipient,
                "date": date,
                "body": body,
                "attachments": attachments,
                "category": category,
            }

            md_content = create_markdown(mail_data)

            if args.format == "single":
                # 单独保存
                category_dir = output_dir / date_folder / category
                category_dir.mkdir(parents=True, exist_ok=True)

                filename = f"{sanitize_filename(subject)}_{i+1:03d}.md"
                filepath = category_dir / filename
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(md_content)
                print(f"  [{i+1}/{len(email_ids)}] {category}/{subject[:50]}")
            else:
                # 合并保存
                combined_md += md_content + "\n\n---\n\n"

            processed += 1

    # 保存合并文件
    if args.format == "combined" and combined_md:
        combined_path = output_dir / f"combined_{date_folder}.md"
        with open(combined_path, "w", encoding="utf-8") as f:
            f.write(combined_md)
        print(f"\n合并文件已保存: {combined_path}")

    mail.logout()
    print(f"\n完成! 共处理 {processed} 封邮件,保存在 {output_dir}")


if __name__ == "__main__":
    main()
