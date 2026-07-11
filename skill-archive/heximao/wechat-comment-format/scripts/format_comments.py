import sys
import re

def parse_comments(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        full_content = f.read()

    # 1. 提取并保留 YAML Frontmatter
    frontmatter_match = re.match(r'^(---\n.*?\n---\n)', full_content, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        body = full_content[len(frontmatter):]
    else:
        frontmatter = ""
        body = full_content

    # 2. 预处理：移除噪音行
    noise_patterns = [
        r'^留言 \d+$',
        r'^Like$',
        r'^\d+条回复$',
        r'.*?\d+小时前.*',
        r'.*?\d+分钟前.*',
        r'.*?刚刚.*',
        r'^赞\d+$',
        r'^顶\d+$',
        r'^!\[\].*$',
    ]
    
    lines = body.split('\n')
    clean_lines = []
    for line in lines:
        s_line = line.strip()
        if not s_line:
            continue
        if any(re.match(p, s_line) for p in noise_patterns):
            continue
        clean_lines.append(s_line)

    # 3. 识别块：用户名/作者 vs 留言内容
    # 定义作者标识
    author_identifiers = ['金渐成作者', '金渐成', '作者', '天机奇谈', '未命名用户作者']
    
    # 定义常见省份/地区用于辅助识别用户名
    regions = ['北京', '上海', '广州', '深圳', '广东', '浙江', '江苏', '山东', '福建', '安徽', '湖北', '湖南', '四川', '重庆', '河北', '河南', '山西', '辽宁', '吉林', '黑龙江', '内蒙古', '广西', '海南', '贵州', '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆', '香港', '澳门', '台湾']
    
    formatted_output = []
    current_conv = [] # 存储当前一组对话（用户留言+作者回复）
    
    i = 0
    while i < len(clean_lines):
        line = clean_lines[i]
        
        # 判断是否为作者
        is_author = any(id_str == line for id_str in author_identifiers)
        
        # 判断是否为普通用户（通常较短，或者包含地区）
        has_region = any(r in line for r in regions)
        is_user = (len(line) < 30 and (has_region or not is_author)) # 简单的 heuristic
        
        if is_author:
            # 如果是作者，下一行通常是回复内容
            name = "作者"
            if i + 1 < len(clean_lines):
                content = clean_lines[i+1]
                current_conv.append(f"{name}\n{content}")
                i += 2
            else:
                i += 1
        elif is_user:
            # 如果是新用户留言，开始新的一组对话
            if current_conv:
                formatted_output.append("\n\n".join(current_conv))
                current_conv = []
            
            name = line
            if i + 1 < len(clean_lines):
                content = clean_lines[i+1]
                current_conv.append(f"{name}\n{content}")
                i += 2
            else:
                i += 1
        else:
            # 如果既不是名字也不是作者，可能是漏掉的内容或格式异常，尝试追加到上一个块
            if current_conv:
                current_conv[-1] += f"\n{line}"
            i += 1

    if current_conv:
        formatted_output.append("\n\n".join(current_conv))

    # 4. 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        if frontmatter:
            f.write(frontmatter.strip() + "\n\n")
        f.write("\n\n---\n\n".join(formatted_output))
        f.write("\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 format_comments.py <file_path>")
        sys.exit(1)
    parse_comments(sys.argv[1])
