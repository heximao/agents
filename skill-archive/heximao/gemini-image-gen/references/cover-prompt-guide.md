# 封面 Prompt 编写指南

基于已有文章封面 prompt 文件提炼的最佳实践。

## 10 种封面风格模板

| # | 风格 | 适用场景 | 关键词 |
|---|-----|---------|--------|
| 1 | 巨轮隐喻 | 市场集中度、系统性风险 | `Cruise ship tilting, Wall Street skyline, cinematic` |
| 2 | 赛博朋克 | 科技股狂欢、硬件爆发 | `Glowing chips, cyberpunk, macro photography` |
| 3 | 火箭/抛物线 | 行情高涨、减仓操作 | `Rocket, green flames, parachute, line art` |
| 4 | 瀑布对比 | 涨跌分化、暗流涌动 | `Number waterfall, green/red contrast, surrealist` |
| 5 | 拥挤门口 | 散户涌入、逆向思维 | `Trading hall, crowd, exit door, aerial view` |
| 6 | 静物等待 | 弹药储备、耐心观望 | `Minimalist desk, K-lines, muted palette` |
| 7 | 天平失衡 | 板块集中度、权重失衡 | `Golden balance scale, tilted, metallic textures` |
| 8 | 宏大场景 | 产业周期、基础设施 | `Data center, aerial drone, sci-fi documentary` |
| 9 | 棋盘博弈 | 市场单边、博弈失衡 | `Chess board, tilt-shift, miniature photography` |
| 10 | 潮汐锚定 | 半仓策略、进退两难 | `Ocean tides, anchor, watercolor + digital` |

## Prompt 结构公式

```
[主体描述] + [环境/背景] + [视角/构图] + [风格/质感] + [光线/色调]
```

### 好 prompt 示例

```
A massive luxury cruise ship tilting heavily on calm seas, almost all passengers
crowded on one side of the deck while the other side is completely empty.
Wall Street-style skyline in the distance.
Cinematic quality, wide-angle lens, golden hour lighting with warm-cool contrast.
```

- 主体：巨轮倾斜 + 乘客拥挤一侧
- 环境：华尔街天际线
- 视角：广角
- 风格：电影质感
- 光线：黄昏暖冷对比

### 差 prompt 示例

```
A stock market image with AI chips
```

过于模糊，无风格、无构图、无质感描述，Gemini 会自由发挥导致质量不稳定。

## 中文 Prompt 转英文要点

1. 翻译时保留核心意象（邮轮、芯片、火箭、天平等）
2. 风格词汇要精确（`cyberpunk`、`surrealist`、`minimalist`、`line art`）
3. 摄影术语直接用英文（`wide-angle lens`、`macro photography`、`shallow depth of field`、`tilt-shift`）
4. 色调描述要明确（`warm-cool contrast`、`muted Morandi palette`、`high contrast`）
