# 批量生成封面示例

## 场景：为文章生成 10 张候选封面

### 输入

- 文章路径：`03-original/035-article/{date}_{slug}_v{N}_final.md`
- 封面 Prompt 文件：`03-original/036-cover-prompt/{date}_{slug}_cover-prompt_v1.md`

### 执行

从封面 Prompt 文件中提取每个 prompt 的 **English** 部分，依次调用：

```bash
# Cover #1 — 倾斜的巨轮
zsh -i -c 'python3 /Users/saibopika/wemedia/07-scripts/gemini_image.py "A massive luxury cruise ship tilting heavily on calm seas, almost all passengers crowded on one side of the deck while the other side is completely empty. Wall Street-style skyline in the distance. Cinematic quality, wide-angle lens, golden hour lighting with warm-cool contrast." -o /Users/saibopika/wemedia/03-original/037-covers/cover_01.png'

# Cover #2 — AI芯片的狂欢
zsh -i -c 'python3 /Users/saibopika/wemedia/07-scripts/gemini_image.py "Countless glowing AI chips stacked into a pyramid, the top chip emitting dazzling blue-purple light while cracks appear at the base. Dark background, cyberpunk aesthetic, macro photography feel, extremely shallow depth of field." -o /Users/saibopika/wemedia/03-original/037-covers/cover_02.png'

# Cover #3 — 火箭与降落伞
zsh -i -c 'python3 /Users/saibopika/wemedia/07-scripts/gemini_image.py "A rocket labeled S&P 500 blasting upward at high speed with green exhaust flames, while a small figure on the rocket side quietly straps on a parachute. Clean line art style, white background, financial magazine cover composition." -o /Users/saibopika/wemedia/03-original/037-covers/cover_03.png'
```

### 注意事项

1. **逐个执行**，不要并行（中转站有频率限制）
2. 每张图约 1.7-2MB，10 张共约 17-20MB
3. 生成完成后检查图片质量，选出最佳 1-2 张作为最终封面
4. 其余保留在 `037-covers/` 目录备查

### 输出

```
03-original/037-covers/
├── cover_01.png  # 倾斜的巨轮
├── cover_02.png  # AI芯片的狂欢
├── cover_03.png  # 火箭与降落伞
├── cover_04.png  # 绿色瀑布中的红色暗流
├── cover_05.png  # 拥挤的门口
├── cover_06.png  # 弹药箱
├── cover_07.png  # 天平上的科技股
├── cover_08.png  # 数据中心的黎明
├── cover_09.png  # 棋盘上的赌注
└── cover_10.png  # 涨潮中的锚
```
