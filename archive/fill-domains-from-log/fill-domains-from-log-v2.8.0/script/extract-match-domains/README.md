# extract-match-domains

从 ClashX Meta 日志提取未被本仓库 yaml 规则覆盖的目标（`match Match` 漏网之鱼、
`match RuleSet(oc-cn-domain)` 外部规则集命中），输出结构化候选表供
fill-domains-from-log skill 第 4–5 步（查重 + 自主裁决）消费。

## 用法

```bash
python3 .agents/skills/fill-domains-from-log/scripts/extract-match-domains/extract_match_domains.py <日志文件或目录>
# 自定义跳过清单（默认读取脚本旁 skip-list.txt）：
python3 .../extract_match_domains.py --skip-list /path/to/other-skip-list.txt <日志目录>
```

## 输出段

| 段 | 用途 |
|---|---|
| `# summary` | 各类计数（候选数、过滤数、skip-list 命中数） |
| `# domains` | 候选域名表：`域名 \| 类别(mm/oc) \| 次数 \| 进程(次数)`，按总次数降序 |
| `# registrable` | 主域归并：`主域 <- 子域(次数), ...`，供 check-coverage 输入 |
| `# public-ips` | 公网裸 IP（私有/保留段已过滤） |
| `# manual-review` | skip-list `manual` 项本轮命中——待人工，不参与自动裁决（已登记 `issues-domain.md` 待人工表的不重复登记，见 skill 第 6b 节） |
| `# skipped` | skip-list `skip` 项本轮命中——审计记录 |

## 内置过滤

- 无 TLD 伪域名（`monitor_browser`、`wpad` 等）
- 探针族：`*.dotnxdomain.net` / `*.dashnxdomain.net` / `*.starnxdomain.net`、
  `root-key-sentinel-*`（NextDNS + DNSSEC 探针）
- 私有 / 保留 IP 段（RFC1918、loopback、link-local、CGNAT 等）
- skip-list 清单（见下）

## skip-list.txt

已裁决跳过项的机器可读数据源（AGENTS.md「已裁决结论」的映射）：

- `skip` 模式：不进候选，仅审计段可见（如 reject 上游已收录域名）
- `manual` 模式：不进候选，但每轮单列 manual-review 段（长期挂起待人工项）

**维护纪律**：每轮产生新的「已裁决不归类 / 待人工」结论后，落 changelog 的同时
必须同步追加到 skip-list.txt，否则下轮会重复出现同样的候选。

**`manual` 项的表格视图**：`manual` 模式条目另登记于仓库根 `issues-domain.md`
待人工判定表（人类可读，留用户定夺；新 manual 项三处同留痕：skip-list +
issues-domain.md + changelog，用户定案后三处同步移除）。细则见 skill 第 6b 节。

## 已知限制

- 主域归并是启发式（常见二级 TLD 取三级、其余取两级），未依赖 publicsuffix
  列表；特殊后缀可能归并不准，落盘前按 AGENTS.md 判据复核。
- 输出按 `--> 目标:端口` 正则匹配 info 行，IPv6 目标会剥离方括号后按 IP 处理。
