#!/bin/bash
# =============================================================================
# 微信公众号留言内容验证脚本
# 用途：验证排版后内容未丢失，对比备份文件和当前文件的有效内容
# =============================================================================

set -e

# 支持自动恢复参数
AUTO_RECOVER=false
if [ "$1" = "--auto-recover" ] || [ "$1" = "-r" ]; then
    AUTO_RECOVER=true
    shift
fi

if [ $# -lt 2 ]; then
    echo "用法：$0 [-r|--auto-recover] <原始备份文件> <排版后文件>"
    echo "示例：$0 comments.md.backup.20260422_151321 comments.md"
    echo ""
    echo "选项："
    echo "  -r, --auto-recover    发现内容丢失时自动从备份恢复"
    exit 1
fi

ORIGINAL="$1"
FORMATTED="$2"

if [ ! -f "$ORIGINAL" ]; then
    echo "错误：备份文件不存在：$ORIGINAL"
    exit 1
fi

if [ ! -f "$FORMATTED" ]; then
    echo "错误：排版后文件不存在：$FORMATTED"
    exit 1
fi

# 创建临时文件用于对比
TEMP_ORIGINAL=$(mktemp)
TEMP_FORMATTED=$(mktemp)
trap "rm -f '$TEMP_ORIGINAL' '$TEMP_FORMATTED'" EXIT

# 提取有效文字内容（去除图片、链接、表情、统计等装饰性内容）
extract_content() {
    local file="$1"
    local output="$2"

    awk '
    BEGIN { in_yaml = 0 }

    # 跳过 YAML frontmatter
    NR == 1 && /^---$/ { in_yaml = 1; next }
    in_yaml && /^---$/ { in_yaml = 0; next }
    in_yaml { next }

    # 跳过图片链接
    /!\[\]/ { next }
    /!\[\[/ { next }

    # 跳过 base64 图片
    /data:image/ { next }

    # 跳过纯 URL
    /^https?:\/\// { next }

    # 跳过空行
    /^[[:space:]]*$/ { next }

    # 跳过点赞、统计
    /^赞[0-9]+/ { next }
    /^顶[0-9]+/ { next }
    /^[0-9]+赞/ { next }
    /^[0-9]+顶/ { next }

    # 跳过时间戳
    /^[0-9]+(小时|分钟|秒) 前/ { next }

    # 保留其他所有行（用户名、留言内容、作者回复等）
    {
        # 清理行内的图片标记，保留文字
        gsub(/!\[.*?\]\(.*\)/, "")
        gsub(/!\[\[.*?\]\]/, "")
        gsub(/\(data:image[^)]*\)/, "")

        # 清理行内 URL（可选，根据需要调整）
        # gsub(/https?:\/\/[^ ]+/, "")

        # 清理时间戳 YYYY-MM-DD HH:MM:SS
        gsub(/[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]+/, "")

        # 去除首尾空白
        gsub(/^[[:space:]]+|[[:space:]]+$/, "")

        if (length($0) > 0) {
            print
        }
    }
    ' "$file" | sort > "$output"
}

echo "正在提取原始有效内容..."
extract_content "$ORIGINAL" "$TEMP_ORIGINAL"

echo "正在提取排版后有效内容..."
extract_content "$FORMATTED" "$TEMP_FORMATTED"

# 对比两个文件
ORIG_LINES=$(wc -l < "$TEMP_ORIGINAL")
FORM_LINES=$(wc -l < "$TEMP_FORMATTED")

echo ""
echo "=== 内容验证报告 ==="
echo "原始有效内容行数：$ORIG_LINES"
echo "排版后内容行数：$FORM_LINES"
echo ""

# 使用 diff 找出差异
DIFF_RESULT=$(diff "$TEMP_ORIGINAL" "$TEMP_FORMATTED" 2>&1) || true

if [ -z "$DIFF_RESULT" ]; then
    echo "✅ 验证通过：所有有效内容均已保留"
    exit 0
else
    echo "⚠️ 发现内容差异："
    echo ""
    echo "$DIFF_RESULT"
    echo ""

    # 找出具体的差异行
    MISSING_IN_FORMATTED=$(comm -23 "$TEMP_ORIGINAL" "$TEMP_FORMATTED")
    ADDED_IN_FORMATTED=$(comm -13 "$TEMP_ORIGINAL" "$TEMP_FORMATTED")

    if [ -n "$MISSING_IN_FORMATTED" ]; then
        echo "❌ 排版后缺失的内容："
        echo "$MISSING_IN_FORMATTED"
        echo ""
    fi

    if [ -n "$ADDED_IN_FORMATTED" ]; then
        echo "ℹ️  排版后新增的内容（可能是格式调整）："
        echo "$ADDED_IN_FORMATTED"
        echo ""
    fi

    # 自动恢复逻辑
    if [ "$AUTO_RECOVER" = true ]; then
        echo ""
        echo "=== 自动恢复 ==="
        echo "检测到内容丢失，正在从备份恢复..."

        # 创建恢复前快照
        RECOVER_SNAPSHOT="${FORMATTED}.recover-before.$(date +%Y%m%d_%H%M%S)"
        cp "$FORMATTED" "$RECOVER_SNAPSHOT"
        echo "已创建恢复前快照：$RECOVER_SNAPSHOT"

        # 从备份恢复
        cp "$ORIGINAL" "$FORMATTED"
        echo "已从备份恢复原始文件：$ORIGINAL → $FORMATTED"

        echo ""
        echo "恢复完成。请重新执行排版流程。"
        echo ""
        echo "建议的下一步："
        echo "1. 检查备份文件确认内容完整"
        echo "2. 重新运行清理脚本：bash scripts/clean-repeated-content.sh $FORMATTED"
        echo "3. 重新运行格式化：bash scripts/format-comments.sh $FORMATTED"
        echo "4. 重新验证：bash scripts/verify-comments.sh $ORIGINAL $FORMATTED"

        exit 2  # 特殊退出码表示已执行恢复
    fi

    echo ""
    echo "=== 手动恢复 ==="
    echo "如需恢复，请运行："
    echo "  cp $ORIGINAL $FORMATTED"
    echo ""
    echo "或使用自动恢复模式："
    echo "  $0 -r $ORIGINAL $FORMATTED"

    exit 1
fi
