---
name: fill-domains-from-log
version: v2.8.0
description: 从 ClashX Meta 日志提取漏网之鱼（match Match）及 oc-cn-domain 外部规则集命中的域名，结构化输出去重候选（自带 skip-list 已裁决过滤、私有 IP/探针过滤、主域归并）；用 check-coverage 脚本做规则级查重与品牌标签锚点检索，进程名粗判后自主裁决归属（证据不足时自主调用 RDAP/DoH，不再经用户确认），分类补录到 clash-proxy 规则 yaml 并执行查重自检闭环。证据不足无法判定归属的域名写入 issues-domain.md 待人工表（表格列出命中子域/次数/进程/已查证据/存疑点），留用户判定（v2.8.0 新增）。日志获取采用 cp 复制：从 ~/.config/clash.meta/logs 只读复制昨天的日志到仓库 log/clashx-meta-log/（禁止 mv/rm 源目录，避免沙箱授权弹窗、支持 automation 全自动；当天日志不处理、更早的留存源目录），处理完成后归档至 log/.archive/。Git 侧所有改动直接在 main 上完成：每轮开头 fetch 并确认与远程双向 0 0，提交后立即 push 并再次确认。当用户要求补漏域名、归类漏网之鱼、分析日志补规则、整理 match Match 或 oc-cn-domain 域名时使用。
---

# 从日志补漏域名

在 clash-proxy 仓库中将 ClashX Meta 日志里未被本仓库 yaml 规则覆盖的目标归类到合适的规则文件。覆盖两类：

- `match Match` —— 未命中任何规则，落入"漏网之鱼"兜底策略组
- `match RuleSet(oc-cn-domain)` —— 命中外部 OpenClash CN 域名规则集（通常走 DIRECT），同样说明本仓库规则未覆盖

全程在仓库根目录 `/Users/saibopika/clash-proxy` 执行命令。

## 处理流程（必须按序执行）

```text
 0. ★ 同步准备（每轮开头必做，详见第 0 节）★
      git fetch origin → main 追上远程 → 确认与远程双向 0 0
      （交互式会话加做：skip-list ↔ AGENTS.md 已裁决清单对齐；automation 轮跳过）
      ↓
 1. 准备日志（cp 复制昨天的：~/.config/clash.meta/logs → log/clashx-meta-log/）
      ↓
 2. 提取（extract-match-domains 脚本：结构化候选表 + skip-list 过滤
    + 私有 IP/探针过滤 + 主域归并；候选为 0 → 空结果轮收尾，直接跳 12）
      ↓
 3. 人工复核过滤边界（脚本内置过滤之外的漏网情况）
      ↓
 4. 规则级查重（scripts/check-coverage/check_coverage.py，含品牌标签锚点）
    + 读历史 changelog + 进程名粗判，粗判表落盘 log/.work/ 续跑
   —— 本步骤禁止任何外部查询 ——
      ↓
 5. ★ 自主裁决归属（证据足直接定；不足进 6）★
      ↓
   ┌── 证据充分 ─────────────────┐
   │                            ↓
   └── 证据不足 → 6. 自主 RDAP / DoH 查询 → 据结果定夺
                              ↓
              ┌─ 有结论 ───────────→ 7. 按自主裁决结论分类到规则文件
              └─ 仍无结论 → 6b. 登记 issues-domain.md 待人工表
                           + skip-list(manual) + changelog 待人工段
                              ↓
 7. 按自主裁决结论分类到规则文件
      ↓
 8. 编辑格式（payload: 开头、DOMAIN-SUFFIX、# === 分组 ===）
      ↓
 9. 自检闭环：find_duplicates.py + yaml语法校验
      ↓
10. 更新 changelog → 在 main 上提交（显式列文件，不推远程）
      ↓
11. push main → 确认 0 0 → 删除本轮粗判草稿 log/.work/
      ↓
12. 归档已处理日志（log/clashx-meta-log/ → log/.archive/）
```

**两条核心原则：**

1. **归属判断自主裁决（2026-10-17 起取消 review 关卡）。** 粗判 + 必要时 RDAP/DoH 即为判断依据，每个决定须**留痕**（AGENTS.md 判据条号 / 进程名 / 域名语义 / RDAP 结果），写入 changelog 可追溯。证据不足且查询无结论的按既定规则兜底（无主端点不归类、国内杂项归 `direct.yaml`、海外杂项归 `proxy.yaml`），不强行归类、不凭感觉。**归属完全无法判定的（含判据 5 无锚点厂商文件的大型公司主域）登记 `issues-domain.md` 待人工表留用户判定（第 6b 节）**，与 skip-list `manual`、changelog 待人工段三处一致。用户主动介入给归属时以用户为准，但默认不主动询问用户。
2. **动手前必须确认本地与远程一致。** main 与 `auto-merge-reject.yml` 工作流共管（每日 00:20 UTC 自动推送 `reject.yaml`），远程随时可能出现新提交；每轮开头和每次 commit 前都必须 fetch + 双向 `0 0` 校验，否则可能在过期基线上做查重判断。所有编辑直接在 main 上进行（2026-10-17 起取消分支制度）。

## 0. 同步准备（每轮开头必做，不可跳过）

本仓库的 `main` 由 `auto-merge-reject.yml` 工作流共管（每日 00:20 UTC 自动推送 `reject.yaml`），远程随时可能出现新提交；本地只保留 `main` 一个分支（2026-10-17 起取消分支制度，所有改动直接在 main 上进行）。**动手分析日志之前必须先完成同步准备**，否则可能在过期的代码基线上做查重判断。

执行：

```bash
cd /Users/saibopika/clash-proxy

# 1. 取远程引用（安全，不动工作区）
git fetch origin

# 2. 本地 main 追上远程 main
git checkout main
git status                                    # 有未暂存改动 → 先 git stash
git pull --rebase origin main
git stash pop                                 # 仅 stash 过才需要

# 3. 确认落位：与远程双向同步
git rev-list --left-right --count origin/main...HEAD   # 必须输出 0  0
git status -sb                                # 工作区干净（未跟踪文件不影响）
```

判定与异常处理：

- `git pull --rebase` 在存在未暂存改动时会直接失败，此时**必须先 `git stash`**，不要用 `git checkout --` 丢弃改动。
- rebase 出现冲突时先解决冲突再 `git rebase --continue`；无法判断时 `git rebase --abort` 回到操作前状态并汇报。
- **禁止 `git push --force` / `--force-with-lease` 任何形式**，会抹掉 bot 的自动合并提交。
- 第 3 步不是 `0  0` 就不算完成，必须继续同步；走到第 1 步时若 HEAD 不在 main 上，先 `git checkout main`。

**skip-list ↔ AGENTS.md 清单对齐检查（仅交互式会话执行；automation 轮必须跳过）**

比对 `.agents/skills/fill-domains-from-log/scripts/extract-match-domains/skip-list.txt` 各条目与 AGENTS.md「已裁决结论」清单（以及 `.agents/memory/MEMORY.md` 的同构清单）：

- skip-list 有而 AGENTS.md / MEMORY.md 清单缺的已裁决项（典型：cron 轮新增裁决，automation 会话写 AGENTS.md 被 BLOCKED 遗留），补入对应清单行，恢复三处一致。
- 用户已定案移除的 manual 项（skip-list 已删），同步从清单移除。
- **`issues-domain.md` 待人工表 ↔ skip-list `manual` 段一致性**：表为 manual 项的人类可读表格视图（第 6b 节）。表中有而 skip-list 无（或反之）的，以 skip-list 为准对齐补表；用户只在表中划掉某行而未同步 skip-list 的，按用户已定案处理（补录 yaml 或转 skip，并补移除 skip-list 项）。
- 对齐产生的 AGENTS.md / MEMORY.md 改动随本轮提交入库。

AGENTS.md 是受保护文件，cron / automation 会话（无交互用户）中 patch 必被 BLOCKED——automation 轮**不要尝试**此步，不一致留给下一次交互式会话；skip-list 是运行时唯一数据源，清单短暂不一致不影响 automation 正确性。

## 1. 准备日志

- 日志源目录：`/Users/saibopika/.config/clash.meta/logs`，文件夹命名格式 `YYYY-MM-DD_HH-MM-SS`。
- **只处理昨天的日志**（2026-10-17 用户裁决）：当天日志仍被 ClashX Meta 实时写入，不处理；更早的历史日志留存源目录不处理（累积由用户定期清理）。默认昨天；用户显式指定其他日期时按指定。
- **cp 复制（禁止 mv/rm 源目录）**：用 `cp -R` 把昨天的文件夹复制到仓库 `log/clashx-meta-log/`——**只读源、写仓库、不删源**：
  ```bash
  cp -R /Users/saibopika/.config/clash.meta/logs/<YYYY-MM-DD_HH-MM-SS> log/clashx-meta-log/
  ```
  **禁止 `mv` / `rm` 源目录**：写/删 `~/.config`（系统配置目录）会触发沙箱授权弹窗，定时 automation 无人响应会卡死，违背全自动诉求；cp 只读源不触发弹窗（实测 `ls`/`diff`/`cp` 读 `~/.config` 均无弹窗，`mv`/`rm` 写删才弹）。
- **优先用仓库已有**：先在 `log/clashx-meta-log/` 下找昨天日期前缀的文件夹，**有则直接用**（上轮遗留或已 cp）；没有才从源目录 cp。这样无论日志在源还是在仓库（如历史 mv 进去后未归档）都能处理。
- **cp 套娃防护**：`cp -R src dst/` 当 `dst/src` 已存在时会复制成 `dst/src/src` 套娃。cp 前确认 `log/clashx-meta-log/<folder>` 不存在；存在则跳过（已复制过）。
- `log/clashx-meta-log/` 下未归档存量（上轮中断遗留）直接纳入本轮提取范围；处理完成后按第 12 节归档（归档是工作区内 mv，不碰 ~/.config，不弹窗）。

## 2. 提取与过滤（结构化脚本）

用本 skill 自带脚本提取（v2.6.0 起为**结构化输出**，目录结构与仓库 scripts/ 约定一致——每脚本一目录一 README）：

```bash
python3 .agents/skills/fill-domains-from-log/scripts/extract-match-domains/extract_match_domains.py <日志文件或目录>
```

输出段（详见脚本旁 README.md）：

| 段 | 内容 |
|---|---|
| `# summary` | 各类计数（候选数、过滤数、skip-list 命中数） |
| `# domains` | 候选域名表 `域名 \| 类别(mm/oc) \| 次数 \| 进程(次数)`，按总次数降序——第 4 步粗判的直接输入 |
| `# registrable` | 主域归并 `主域 <- 子域(次数), ...`——check_coverage 的直接输入 |
| `# public-ips` | 公网裸 IP（私有/保留段已过滤） |
| `# manual-review` | skip-list `manual` 项本轮命中——待人工，不参与自动裁决，changelog「待人工确认」段照抄；**已在 `issues-domain.md` 表中的不重复登记**（第 6b 节） |
| `# skipped` | skip-list `skip` 项本轮命中——changelog「整批跳过」段照抄即可，不再逐个判断 |

脚本内置过滤（不再人工排除）：无 TLD 伪域名、探针族（`wpad`、`*.dotnxdomain.net` / `*.dashnxdomain.net` / `*.starnxdomain.net`、`root-key-sentinel-*`）、私有/保留 IP 段、skip-list 清单。

**skip-list.txt 维护入口**：`.agents/skills/fill-domains-from-log/scripts/extract-match-domains/skip-list.txt` 是「已裁决结论」的机器可读映射（`skip`=静默跳过、`manual`=待人工可见）。每轮产生新的「已裁决不归类 / 待人工」结论后，落 changelog 的同时**必须同步追加**到该文件，否则下轮重复出现同样候选。反过来，人工已定案的 manual 项（用户给出归属）要从文件移除。**`manual` 项另有人类可读表格视图：仓库根 `issues-domain.md` 待人工表（第 6b 节）**——新 manual 项三处同留痕（skip-list + issues-domain.md + changelog），用户定案后三处同步移除。

**AGENTS.md 清单同步（交互式会话专属动作，automation 轮禁止）**：skip-list 是已裁决项的**运行时唯一数据源**（提取脚本只读它）；AGENTS.md「已裁决结论」清单与 `.agents/memory/MEMORY.md` 同构清单是它的**人类可读快照**。AGENTS.md 是受保护文件，cron / automation 会话写它必被 patch 工具 BLOCKED（2026-10-18 实测）——automation 轮产生新裁决项时只落 skip-list + changelog，并在 changelog 条目标注「AGENTS.md 同步延后」；清单对齐由**交互式会话**在每轮第 0 节的对齐检查中完成。

只提取 info 级别的 `... using` 行；忽略 `match Match/`、`match RuleSet/oc-cn-domain` 等斜杠形式的 dial 报错行（同一目标已含于 info 行）。

日志行格式：`[TCP] 源地址(进程名) --> 目标:端口 match <Match|RuleSet(oc-cn-domain)> using 策略组`。进程名位于源地址后的圆括号内，可有可无。

## 2b. 空结果轮收尾（候选为 0 时必走）

automation 每天跑，多数轮可能过滤后**一个候选都没有**（全部已覆盖 / 被 skip-list 消化）。此时：

- **不写 changelog 条目、不产生任何提交**——空轮没有可审计的变更，changelog 只记实质变更。
- **照常归档**（第 12 节）：已提取确认无增量的日志文件夹照样移入 `log/.archive/`，否则下轮重复提取。
- **记当日 memory 一行**（如「10-18 轮：昨日日志提取 0 候选，全部已覆盖，已归档」），供用户事后核对 automation 存活。
- 公网裸 IP 段也无新增时同样适用。

## 3. 人工复核过滤边界

脚本已内置过滤伪域名、探针族、私有 IP、skip-list。本步只人工兜底脚本覆盖不到的：

- 偶发漏网的明显本地服务主机名（内网域名后缀但非保留 IP 的目标）。
- `# domains` 里明显是广告/追踪类的（按 AGENTS.md「广告/追踪类整批不落盘」只记录不判断）。
- 主域归并是启发式（常见二级 TLD 取三级、其余取两级），个别特殊后缀可能归并不准，粗判时留意 `# registrable` 里归并结果是否合理。

## 4. 规则级查重 + 粗判归属（不做外部查询）

**这一阶段禁止调用任何外部查询（RDAP / DoH / wayback / urlscan / WebSearch）**，只靠本地证据做粗判，为第 5 步自主裁决提供素材。

1. **规则级查重（取代 grep 子串匹配）**：把 `# registrable` 段的主域喂给仓库脚本（也可加裸 IP）：
   ```bash
   python3 .agents/skills/fill-domains-from-log/scripts/extract-match-domains/extract_match_domains.py <日志目录> \
     | awk '/^# registrable/{f=1;next} /^# public-ips/{f=0} f && !/^（无）/{print $1}' \
     | python3 scripts/check-coverage/check_coverage.py -
   ```
   - 输出 `COVERED`（含命中文件与规则）的主域**整批跳过**——规则集先于本地 yaml 匹配，不代表规则缺失。
   - 输出 `DOMAIN,精确主机` 命中的注意判据 8：精确主机规则 ≠ 主域覆盖，回看命中行规则类型再定。
   - 输出 `DOMAIN-KEYWORD` 命中的是弱证据，不算覆盖。
   - 输出 `BRAND-ANCHOR` 的即判据 1 命中（库内同标签其他 TLD），直接可定为该锚点文件。
   - 输出 `UNCOVERED` 的进入粗判。
   **禁止查询、核对 `reject.yaml`**（脚本已自动排除）。
2. **读历史 changelog**：重点读最近若干条目，看未覆盖主域是否已被往期记录判定过。reject 上游已收录等历史跳过项已由 skip-list 机器化，changelog 主要查「往期裁决过但未进 skip-list」的漏网记录。
3. **进程名粗判**：`# domains` 表的进程列是第一手线索：
   - `Trae CN Helper` / `TRAE SOLO CN Helper` / `DoubaoIme` → 字节系（Trae / 豆包）
   - `Feishu` / `Lark Helper` → 飞书系
   - `wpsoffice` / `wpscloudsvr` → 金山办公 WPS
   - `trustd` → macOS 证书校验，目标多为 OCSP / CRL 端点
   - `mihomo` / `OrbStack Helper` → 内核 / 基础设施自身流量
   - `logioptionsplus_agent` → 罗技 Options+（logitech 系，无锚点时留人工）
   - `Google Chrome Helper` / `firefox` → **无产品指向，归属由第 5/6 步自主裁决；证据不足走 RDAP**
4. **粗判表落盘（中断续跑）**：每个未覆盖主域写一行「主域 → 建议归属文件 + 判断依据（进程名 / 域名语义 / BRAND-ANCHOR / AGENTS.md 判据条号）」，标记 `可定` / `待查`，**写入 `log/.work/YYYY-MM-DD-draft.md`**（gitignore 覆盖，不入库）。中断后下轮若发现该文件存在，先读它续跑而不是从头再来；第 11 步 push 成功后删除。

## 5. 自主裁决归属（留痕，可追溯）

**本步骤取代旧版 review 关卡（2026-10-17 起取消用户确认环节）。** 粗判完成后，由 agent 自主裁决归属，不再用 `AskUserQuestion` 向用户提问。

裁决规则：

- **证据充分（`可定`）**：粗判依据明确（命中 AGENTS.md 判据条号、或进程名+域名语义双佐证、或同文件已有同类分组）→ 直接定归属文件，进入第 7 步落盘。
- **证据不足（`待查`）**：进入第 6 节自主调用 RDAP / DoH / wayback 查询；查询有结论的据结果定夺，无结论的按既定兜底规则处理（见下），其中**归属完全无法判定的登记 `issues-domain.md` 待人工表**（第 6b 节）。
- **已裁决项直接跳过**：AGENTS.md「已裁决结论」、skip-list 已收录项（reject 上游已收录如 `clarity.ms`、`jpush.cn` 等，无主端点，伪域名/探针族——提取脚本已自动消化，见 `# skipped` / `# manual-review` 段）——不查、不收、不归类。
- **无主端点兜底**：Cloudflare NS + RDAP 无注册商实体 + 首页 429/空 + 直连超时 + 仅浏览器进程且无产品指向（典型 `antpeak.com` / `hibchr.com` / `zorvian.com`）→ 不归类，记 changelog「待人工」（`skip` 模式，不进 issues-domain.md）。
- **杂项兜底**：国内经 RDAP/NS 确认归 `direct.yaml`；海外归 `proxy.yaml`；归属仍完全无法判定的（含判据 5 无锚点厂商文件的大型公司主域，如 `jd.com` / `mi.com` / `zoom.us`——automation 不代建厂商文件）**登记 `issues-domain.md` 待人工表**（第 6b 节）+ skip-list `manual` + changelog「待人工」三处留痕，跳过落盘，不强行归类。

**留痕要求**：每个归类决定在 changelog 写明依据（判据条号 / 进程名 / RDAP 结果），未归类项写明原因。这是自主模式下唯一的可追溯手段，不可省略。

**用户介入通道**：默认不主动询问用户；若用户在对话中主动给出归属（如「zhipin.com → 猎聘」），以用户输入为准，不再自行论证或改判。

## 6. RDAP / DoH 查询（自主调用，针对证据不足项）

**前置条件：第 5 步自主裁决中标记为 `待查` 的项。** 不再以"用户答不确定"为触发条件，由 agent 自主判断证据是否充分。

- **代理可用性先探测（每轮现场做）**：本机 7893 代理状态会来回翻转，查询前先 `nc -z 127.0.0.1 7893`。不通时**不要无限重试**：所有待查项在粗判草稿（`log/.work/`）中标记「代理不可用，顺延下轮」，本轮按无结论兜底处理（记 changelog「待人工/下轮重试」），automation 正常收尾不卡死。
- **本机 `whois` 命令不可用**：`whois.iana.org` 无法解析，客户端会挂起而非报错；macOS 也**没有 `timeout` 命令**（`timeout: command not found`）。不要再尝试 `timeout 30 whois <domain>`。
- **RDAP（首选）**：`https_proxy=http://127.0.0.1:7893 curl -sL --max-time 20 https://rdap.org/domain/<domain>` — **必须走代理**（直连返回空）。首次调用常返回空响应，需重试 2–3 次（间隔 3s）。返回 JSON 中 `registrar` 为空数组 + `nameservers` 为 Cloudflare NS（`ALEC.NS.CLOUDFLARE.COM`）通常意味着注册信息完全隐私保护。**批量查证用 curl 循环落盘 JSON 再本地解析，不要用 python urllib/requests 直连代理（Hermes python3 缺 CA bundle，SSL 证书校验必失败，见第 15 节）。** 证据可信度层级：RDAP（注册商+NS）> DoH（CNAME 链可暴露所有者 DNS 调度域，如 `bytedns3.com` 实证字节）> HTTP 首页标题 > crt.sh（走代理常 502）/ wayback API（高频 429，两者不可作为主证据）。
- **批量 RDAP**：写成 `/tmp/rdap.py` 循环 + 重试执行（heredoc 内联 python 会被安全策略拦截，见第 15 节环境坑）。
- **DoH 存活检查**：`https_proxy=http://127.0.0.1:7893 curl -s "https://cloudflare-dns.com/dns-query?name=<domain>&type=A" -H "Accept: application/dns-json"` — `"Status":3`（NXDOMAIN）= 域名已失效，不归类。适合一次批量筛多个主域。
- **辅助判**：`https://archive.org/wayback/available?url=<domain>` 查历史快照（走代理，高频会 429）；`urlscan.io` 搜索结果常直接暴露归属（如 `cmicapm.com` → China Mobile Group Guangdong）。
- **查询结果据以定夺并留痕**：拿到 RDAP/外部证据后，结论与粗判不同或仍有歧义时，按查询结果修正裁决，不再回问用户。查询无结论的（隐私保护 + 首页 429/空 + 直连超时 + 仅浏览器进程）按第 5 节「无主端点兜底」处理——不归类，记 changelog「待人工」，并同步追加到 skip-list（`manual` 模式）。**其中需要用户定夺的（`manual` 模式）同时登记 `issues-domain.md` 待人工表，见第 6b 节。**
- **判定"无主端点"的标准**：Cloudflare NS + RDAP 无注册商实体 + 首页 429 或空响应 + 直连超时 + 发起进程仅浏览器且无产品指向 → 判定为无主广告/追踪端点。典型样例：antpeak.com / hibchr.com / zorvian.com（2026-10-04）。**这类默认不归类，记 changelog「待人工」并同步进 skip-list（`skip` 模式）；`skip` 模式是已裁决不归类，不进 issues-domain.md，不主动询问用户。**

## 6b. issues-domain.md 登记（证据不足项的最终去向）

**触发条件：第 6 步 RDAP/DoH 查询后仍无法判定归属的主域**（含判据 5「无锚点厂商文件」的大型公司主域，如 `jd.com` / `mi.com` / `zoom.us`——automation 不代建厂商文件）。除 changelog「待人工」段与 skip-list `manual` 外，**必须写入仓库根目录 `issues-domain.md` 待人工判定表**，留用户判定。

**文件定位**：`issues-domain.md`（仓库根，已入 git 跟踪）是 skip-list `manual` 段的**人类可读表格视图**——skip-list 管机器过滤，本表管用户判定。只有 `manual` 类（待用户判定）进表；`skip` 类（已裁决不归类：无主端点、广告/追踪类、reject 上游已收录、伪域名/探针）不进表。

**表格列定义**（追加时每列必填，无数据填 `—`）：

| 列 | 内容 |
|---|---|
| `#` | 序号，接续表尾 |
| `域名` | 主域（归并后） |
| `登记日期` | 首次挂起的日期（YYYY-MM-DD，取该轮 changelog 条目日期） |
| `命中子域（次数）` | 日志实证子域与次数，注明轮次 |
| `进程` | 发起进程名 |
| `已查证据` | RDAP/DoH/BRAND-ANCHOR/判据条号等已完成的查证 |
| `存疑点 / 待定夺` | 为什么定不了 + 需要用户定夺什么 |

**追加规则**：

- 新无法判定项**追加到表尾**；表整体按登记日期升序排列（最早挂起的排最前，长期未定案项保持可见）。
- **已在表中的域名不重复登记**；本轮又命中的，在 changelog「待人工确认」段照抄命中行即可（热度信息可选更新到该行「命中子域（次数）」列）。
- 文件不存在时（首轮）按「使用说明 + 表头」模板创建（模板见仓库现有 `issues-domain.md`）。
- **命中子域/次数/进程必须从日志实证**（`# domains` / `# manual-review` 段或归档日志 grep），不得凭记忆填写。

**用户定案闭环**（本表行的唯一移除途径）：

1. 用户在表/对话中给出归属 → 按归属补录 yaml → **移除本表该行** + skip-list `manual` 项移除 + changelog 记录定案。
2. 用户裁决不收录 → 移除本表该行 + skip-list 改 `skip` 模式 + AGENTS.md「已裁决结论」清单留痕（交互式会话动作）。
3. **agent 不得自行移除行**（误登记需修正时，在 changelog 说明后改行，不静默删）。

**automation 兼容性**：`issues-domain.md` 是普通仓库文件（不同于受保护的 AGENTS.md），automation 轮可直接追加并随本轮提交推送；行的移除只发生在用户定案后，由交互式会话执行。

## 7. 分类到规则文件（按自主裁决结论执行）

**前提：第 5 步自主裁决完成，第 6 步（证据不足项）已查清。按自主裁决结论执行，留痕已写入 changelog 草稿。**

按以下优先级判定（细则以 AGENTS.md 为准）：

| 域名特征 | 目标文件 |
|---|---|
| 大型互联网公司主域 | 对应厂商文件：`google.yaml`、`apple.yaml`、`microsoft.yaml`、`meta.yaml`、`bytedance.yaml`、`alibaba.yaml`、`tencent.yaml` 等 |
| 大厂海外 / 国际版服务 | 对应 `-global.yaml`（`alibaba-global`、`bytedance-global`、`tencent-global`） |
| 大厂 AI 服务 | 优先归入厂商专属 AI 文件（如 `claude.yaml`、`openai.yaml`）；无专属文件的按可直连 / 需代理归 `direct-ai.yaml` / `proxy-ai.yaml` |
| 无法直连或直连不稳定的杂项 | `proxy.yaml` |
| 可稳定直连的杂项 | `direct.yaml` |
| 特定领域服务 | 对应主题文件（`streaming.yaml`、`telegram.yaml`、`github.yaml` 等） |

判断要点：

- 日志中走代理节点不代表必须归代理文件；按服务性质判断（如 Let's Encrypt 证书端点 `lencr.org` 可直连归 `proxy.yaml` 或 `direct.yaml` 的证书验证分组需按实际情况定）。
- **oc-cn-domain 类别**的域名命中外部 OpenClash CN 域名规则集且通常走 DIRECT，说明其为国内可达服务，多为国内大厂子域（字节系 `zijieapi.com`、`doubao.com`、`feishu.cn`、`byteimg.com` 等，腾讯系 `qq.com`、`weixinbridge.com` 等）——优先归入对应厂商文件，杂项归 `direct.yaml`。**高频场景：oc-cn-domain 提取出的域名主域往往已被现有 `DOMAIN-SUFFIX` 规则覆盖（如 `*.feishu.cn` 已有 `DOMAIN-SUFFIX,feishu.cn`），这是 Clash 规则集评估优先级导致——规则集先于本地 yaml 匹配，不代表规则缺失。check_coverage 判为 COVERED 的整批跳过，不逐个处理。**
- **不要用厂商主域一次性兜底**：`DOMAIN-SUFFIX,tencent.com` 这类主域会与其它文件里的子域分组产生语义冲突（如 hk-bank.yaml 的 `tpns.hk.tencent.com`），厂商主域很宽时改用精确子域。
- 已收录的域名不重复添加；若已有文件中的归属明显合理，沿用即可。
- **禁止编辑 `reject.yaml`**。
- 全库空壳占位文件已清零（2026-10-17）；如再出现仅有无效占位行 `DOMAIN-SUFFIX,` 的文件，补充真实域名时直接替换该占位行。

## 8. 编辑格式

- 文件必须以 `payload:` 开头；规则用 `DOMAIN-SUFFIX,example.com`（连字符，不用下划线），可选 `DOMAIN,`、`DOMAIN-KEYWORD,`、`IP-CIDR,x.x.x.x/32,no-resolve`。
- 分组注释头格式：`# === 名称（YYYY-MM-DD 漏网之鱼补录）===`，归入文件内已有的同类分组时直接追加到该分组下。
- 若因补录使文件性质变化（如占位文件有了真实内容），同步更新 README.md「规则文件」表中该文件的描述。

## 9. 自检闭环（强制）

每次编辑任意 `.yaml` 后必须执行：

1. 运行 `python3 scripts/find-duplicates/find_duplicates.py`（扫描根已锚定仓库根，任意目录可跑），读取 `scripts/find-duplicates/DUPLICATES.md`。
2. 若存在本次编辑**新引入**的重复，调整归属或删除冗余后重跑。编辑前已存在的历史重复（基线 1 条：`settings.crashlytics.com` direct/google）不在本次处理范围，在汇报中说明即可。
3. 语法校验每个被编辑文件（注意用带 pyyaml 的解释器，见第 15 节）：
   `/Users/saibopika/.workbuddy/binaries/python/envs/default/bin/python -c "import yaml; yaml.safe_load(open('<file>.yaml'))"`
4. `DUPLICATES.md` 与 `duplicates.json` 均**已纳入 git 跟踪**：本轮有 yaml 编辑（报告内容变化）时，把两者随本次提交显式暂存入库；纯 skill/文档轮次不涉及。

## 10. 更新 changelog 并在 main 上提交

**前提：第 5 步自主裁决已完成、第 9 步自检闭环已通过。确认 `git rev-parse --abbrev-ref HEAD` 输出 `main`、且与远程双向 `0 0` 再提交。**

0. **先写 changelog**：在 `changelog.md` 顶部追加本轮条目（已纳入 git 跟踪，**提交时须一并显式暂存**；格式见第 13 节）。
1. 再次确认工作区范围，只暂存本次改动的文件（**不要 `git add -A` / `git add .`**，工作区仍有未跟踪本地文件——`domain-distribution.html`、`log/` 等）：
   ```bash
   git status -sb
   git add direct.yaml github.yaml README.md scripts/find-duplicates/DUPLICATES.md changelog.md   # 显式列出，changelog.md 变更随提交入库
   ```
   本轮如有 `issues-domain.md` 变更（第 6b 节新登记 / 用户定案后移除），一并显式暂存。
2. **确认 `reject.yaml` 未被暂存**（`git diff --cached --name-only | grep -x reject.yaml` 必须无输出）。该文件由 bot 独占维护，人工提交带上它会与上游自动合并冲突。
3. 提交信息用中文，一次逻辑变更一个提交，格式示例：
   ```
   漏网之鱼归类：trae.ai 归入 bytedance-global.yaml

   Co-Authored-By: WorkBuddy <noreply@workbuddy.cn>
   ```
4. **提交前再同步检查一次**：`git fetch origin && git rev-list --left-right --count origin/main...HEAD`，双向 `0 0` 才继续；远程又有新提交则按第 0 节同步后重来。
5. 本步不推远程，推送统一在第 11 步。

## 11. push main 并确认同步

```bash
# 1. 推送前最后确认一次远程状态（bot 可能在提交期间推了新提交）
git fetch origin
git rev-list --left-right --count origin/main...HEAD   # 左侧为 0 才能推

# 2. push（若被拒说明 bot 刚推了新提交，重新同步后再 push，禁止强推）
git push origin main

# 3. 门禁：必须输出 0  0
git rev-list --left-right --count origin/main...HEAD

# 4. push 成功后清理粗判草稿（本轮已消费的所有草稿，含往日中断遗留）
rm -f log/.work/*.md
```

冲突与异常处理：

- **push 被拒（non-fast-forward）**：说明 bot 在本地提交期间推了新提交。`git pull --rebase origin main` 同步后重新校验自检闭环再 push，**不要 `git push --force` / `--force-with-lease`**，会抹掉 bot 的自动合并提交。
- rebase 出现冲突时先 `git status` 看冲突文件；与 `reject.yaml` 的冲突一律 `git checkout --theirs reject.yaml` 保留 bot 版本（人工改动与 bot 的 reject.yaml 几乎不会重叠，真出现先停下来汇报）。
- 第 3 步不是 `0  0` 就不算完成，汇报里必须明确指出未同步。

## 12. 归档已处理日志

**前提：第 11 步 push 已完成、同步确认 `0 0`、changelog 条目已按第 10 步写入并随提交入库（hash 回填按既有纪律顺延下轮）。** 归档是本轮流程的收尾动作，未归档不算完成。

```bash
mkdir -p log/.archive
mv log/clashx-meta-log/<已处理文件夹> log/.archive/
```

- 只归档本轮**确认处理完成**的文件夹；上轮中断遗留、本轮未能定案（留待人工）的日志**留在 `log/clashx-meta-log/` 原地**，待后续轮次处理完再归档。
- **cp 模式下仓库副本是静态快照**（cp 后不再增长，源目录的实时写入不影响仓库副本），可直接归档。仅当历史 mv 场景遗留的文件夹仍在被内核写入时（fd 指向仓库副本）才需检查：`pgrep -fl ClashX` + `ls -lT log/clashx-meta-log/<folder>/` 看 core/mihomo mtime 是否接近当前时间；是则留原地待 app 重启后归档。
- `.archive/` 与 `clashx-meta-log/` 同级（即 `log/.archive/`），同被 `.gitignore` 的 `log/` 规则覆盖，不会入库。
- 归档后 `log/clashx-meta-log/` 应只剩未处理项；下一轮的待处理集合 = 昨天日期前缀的文件夹（源目录或仓库已有）+ `log/clashx-meta-log/` 未归档存量。
- 归档情况（哪些文件夹移入了 `.archive/`）记入当日 memory 日志。

## 13. 收尾核对与记忆

push 并确认 `0 0` 后做四件收尾（changelog 条目本体已在第 10 步随提交写入，本节只核对不重写；若第 10 步遗漏，此处补写并在下轮补提交）：

1. **核对 changelog 条目已入库**：`git show --stat HEAD` 应包含 `changelog.md`。条目格式：

```markdown
## YYYY-MM-DD 漏网之鱼归类：<一句话摘要>

- 数据来源：<日志路径>，提取未被本仓库规则覆盖的目标去重后共 N 个（`match Match` x 个、`oc-cn-domain` y 个）：<列表>。
- <每个归类决定：规则、目标文件、归属依据>
- <未归类项及原因：伪域名、已收录、自主裁决不归类（无主端点/证据不足待人工——已登记 issues-domain.md）等>
- 重复检查结果与语法校验结论。
- Git：main 提交 <hash> 已推送，同步 0 0。
```

2. **核对 `issues-domain.md`**：本轮新无法判定项已按第 6b 节登记（条目数 = skip-list manual 新增数）；用户本轮定案的项已从表中移除并同步 skip-list。
3. **经验落记忆**：把本轮经验追加到 `.agents/memory/YYYY-MM-DD.md`（若产生新的归属判定经验，同步更新 `.agents/memory/MEMORY.md`；新的已裁决项同时更新 skip-list，见第 2 节维护入口）。automation 轮产生新裁决项但 AGENTS.md 清单无法同步时，在 memory 日志标注「AGENTS.md 待同步」供下次交互式会话第 0 节对齐检查补齐。
4. **完成日志归档**：按第 12 节执行。

## 14. 硬性约束

- **禁止跳过第 0 步同步准备（本地与远程一致性检查）。** 在旧基线上做查重与规则判断会得出错误结论。
- **查重必须用 `scripts/check-coverage/check_coverage.py`（规则级判断）**，不得回退到 `grep -l <域名> *.yaml` 子串匹配（会误命中 `xxxx53.com` 这类假阳性、漏掉品牌标签锚点）。
- **skip-list 是已裁决跳过项的唯一数据源**：`.agents/skills/fill-domains-from-log/scripts/extract-match-domains/skip-list.txt`。新的「已裁决不归类 / 待人工」结论落 changelog 时必须同步追加（`skip` / `manual`），用户定案的 manual 项要移除；禁止只写 changelog 不更新 skip-list。
- **证据不足项三处留痕（v2.8.0 起）**：无法判定归属的主域必须同时落 changelog「待人工」段、skip-list `manual`、`issues-domain.md` 待人工表，禁止只记其一；`skip` 类已裁决项（无主端点/广告追踪/reject 上游/伪域名）不进 issues-domain.md。
- **`issues-domain.md` 行只许因用户定案移除**（补录 yaml 或裁决不收录两种闭环），agent 不得自行删行；误登记修正须在 changelog 说明。表中命中子域/次数/进程必须取日志实证，不得凭记忆填写。
- **AGENTS.md 清单同步是交互式会话动作**：AGENTS.md 是受保护文件，cron / automation 会话写它必被 BLOCKED（2026-10-18 实测）——automation 轮只落 skip-list + changelog 即完整闭环（提取脚本只读 skip-list，下轮不受影响），禁止重试写 AGENTS.md；清单对齐走第 0 节对齐检查，延后到交互式会话完成。
- **自主裁决须留痕**：每个归类决定在 changelog 写明依据（AGENTS.md 判据条号 / 进程名 / BRAND-ANCHOR / RDAP 结果 / 同文件同类分组），未归类项写明原因；证据不足且查询无结论的按兜底规则处理（无主端点不归类、国内杂项归 `direct.yaml`、海外杂项归 `proxy.yaml`），不强行归类、不凭感觉。
- **第 4 步只做本地查重和粗判，禁止外部查询**；RDAP/DoH/wayback 等外部查询集中在第 6 节按需自主发起；代理 7893 不可用时待查项顺延下轮，不无限重试阻塞 automation。
- **空结果轮按第 2b 节收尾**：无候选 → 无 changelog、无提交、照常归档、记 memory 一行。
- **禁止 `mv` / `rm` 源目录 `~/.config/clash.meta/logs`**（沙箱授权弹窗 + automation 卡死）：写/删系统配置目录触发沙箱升级，定时 automation 无人响应会卡死。日志获取只用 `cp -R` 只读源（读 `~/.config` 不弹窗）。归档用工作区内 `mv`（不碰 `~/.config`，安全）。
- **禁止编辑 `reject.yaml`**，**禁止在提交中包含 `reject.yaml`**。
- **禁止任何形式的强制推送**（`--force` / `--force-with-lease`）。
- **禁止 `git add -A` / `git add .` 等批量跟踪**，只显式暂存本次改动文件；commit 后必须立即 push 并校验 `0 0`。
- **禁止跳过日志归档（第 12 节）**：push 并确认 `0 0` 后必须把本轮已处理日志移入 `log/.archive/`（空结果轮同样归档），否则下轮会对同一批日志重复提取。
- 用户主动介入给归属时（对话中直接给出），以用户输入为准，不再自行论证或改判；默认不主动询问用户。

## 15. 环境坑（本机实测）

- 系统 `python3` **无 pyyaml**。YAML 语法校验必须用：
  `/Users/saibopika/.workbuddy/binaries/python/envs/default/bin/python -c "import yaml; yaml.safe_load(open('<file>.yaml'))"`
- `timeout` 命令不存在（macOS），`whois` 不可用（见第 6 节）。
- **`mv <源文件夹> <已存在同名文件夹的目标目录>` 不报错，而是把源塞进目标内部**（套娃）。移动日志前必须 diff 确认目标侧无同名文件夹（见第 1 节）。
- **heredoc 内联 python 会被安全策略误判为系统级工具并直接拒绝执行**（提示"该命令属于系统级工具（如 WSL、wmic、sc、reg、schtasks）"）。必须先用 Write 写成 `/tmp/xxx.py`，再 `python3 /tmp/xxx.py`。
- `scripts/find-duplicates/find_duplicates.py` 已排除 reject.yaml，报告中的重复项**均为真实业务文件之间的重复**，可直接作为门禁使用。
- `scripts/check-coverage/check_coverage.py` 为行级正则解析（与 find-duplicates 一致），不依赖 pyyaml，系统 `python3` 可直接运行；退出码恒为 0（查询工具，非门禁）。
- Git 提交用 heredoc（`git commit -F - <<'EOF'`）可用，不会被安全策略拦截；只有 python 内联脚本会被误判。
- **`.workbuddy/skills` 与 `.workbuddy/memory` 是指向 `.agents/` 下真实目录的符号链接**，两个路径访问的是同一份文件。`Skill` 工具加载本 skill 会报 "Cannot find skill"（符号链接对加载器不生效），需要时直接 Read `.agents/skills/fill-domains-from-log/SKILL.md`。
- **AGENTS.md 是受保护文件**：cron / automation 会话（无交互用户 / gateway 在场）中 patch 工具直接 BLOCKED，报 "requires approval but no interactive user or gateway is present"（2026-10-18 实测）。automation 轮新裁决项只落 skip-list + changelog 即闭环；AGENTS.md「已裁决结论」清单与 MEMORY.md 同构清单的同步延后至交互式会话（第 0 节对齐检查）。
- **Hermes python3 走代理 SSL 证书校验失败（CA bundle 缺失，2026-10-21 实测）**：urllib/build_opener 报 `SSLCertVerificationError`。RDAP/DoH 类外部查询一律用 `curl -sL --max-time N`（走 `https_proxy` 环境变量，curl 用系统钥匙串正常）；批量时 curl 循环落盘 `/tmp/*.json` 再写 python 解析脚本执行（heredoc 内联 python 仍被拦）。crt.sh 走代理常 502、wayback API 高频 429——两者不可作为归属判定的主证据。
- **并发会话冲突（2026-10-21 实测）**：同一工作区可能有用户交互会话在 automation 轮运行途中直接提交（本轮交互轮 `e2a6302` 补录 sora.com 与本轮独立裁决撞车）。症状：find_duplicates 报出某文件 intra-file 重复，而自己确认只编辑过一处。排查法：`git diff HEAD -- <file>` + `git show HEAD:<file>` 三方状态定位——若 HEAD 版本已含该域（他人已提交），撤销本轮自己的追加、保留他人版本，并在 changelog 注明并发去重；DUPLICATES.md 重跑结果可能与他人提交的基线版本雷同，属正常。提交前 fetch + 双向 `0 0` 的窗口检查把碰撞概率降到最低，但查重→编辑窗口内仍可能被插队，发现症状先查 git 三方状态再动手。

