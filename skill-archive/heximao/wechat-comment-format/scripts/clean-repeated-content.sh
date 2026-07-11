#!/bin/bash
# =============================================================================
# 公众号留言清理脚本
# 用途：仅清理指定图片链接，不碰任何文字内容
# =============================================================================

set -e

if [ $# -lt 1 ]; then
    echo "用法: $0 <文件路径>"
    exit 1
fi

FILE="$1"

if [ ! -f "$FILE" ]; then
    echo "错误: 文件不存在: $FILE"
    exit 1
fi

TEMP_FILE=$(mktemp)
trap "rm -f '$TEMP_FILE'" EXIT

# 清理规则（严格按以下模式匹配，不碰其他任何内容）：
# 1. ![](https://wx.qlogo.cn...64) - 微信头像
# 2. (data:image...=)               - base64 内嵌图片（带括号）
# 3. data:image...=                 - base64 内嵌图片（无括号）
# 4. [表情文字]                      - 微信表情符号
# 5. YYYY-MM-DD HH:MM:SSSS          - 时间戳

awk '
{
    # 规则 1：微信头像链接 ![](https://wx.qlogo.cn...64)
    gsub(/!\[[^]]*\]\(https?:\/\/wx\.qlogo\.cn[^)]*64\)/, "")

    # 规则 2：base64 内嵌图片（带括号）
    gsub(/\(data:image[^=]*=\)/, "")

    # 规则 3：base64 内嵌图片（无括号）
    gsub(/data:image[^=]*=/, "")

    # 规则 4：微信表情符号
    if (NR == 1) {
        emoji_file = "/Users/saibopika/天玑/.claude/skills/wechat-comment-format/references/wechat-emojis.txt"
        while ((getline line < emoji_file) > 0) {
            if (line ~ /^\[.*\]$/) {
                # 兼容带反斜杠和不带反斜杠的格式：\\?\[表情\\?\]
                safe_line = line
                sub(/\[/, "\\\\?\\[", safe_line)
                sub(/\]/, "\\\\?\\]", safe_line)
                emojis[emojis_count++] = safe_line
            }
        }
        close(emoji_file)
    }

    if (emojis_count > 0) {
        for (i = 0; i < emojis_count; i++) {
            gsub(emojis[i], "", $0)
        }
    }

    # 规则 5：时间戳 YYYY-MM-DD HH:MM:SSSS
    gsub(/[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{4,}/, "")

    print
}
' "$FILE" > "$TEMP_FILE"

mv "$TEMP_FILE" "$FILE"

echo "清理完成: $FILE"
