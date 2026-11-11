#!/usr/bin/env python3
"""从 ClashX Meta 日志中提取未被本仓库 yaml 规则覆盖的目标（结构化输出 v2）。

覆盖两类未覆盖目标：
1. match Match —— 落入漏网之鱼兜底策略组（未命中任何规则）
2. match RuleSet(oc-cn-domain) —— 命中外部 OpenClash CN 域名规则集（通常走 DIRECT）

用法：
    python3 extract_match_domains.py [--skip-list PATH] <log文件或目录> [更多路径...]

- 目录会递归收集其中的 *.log
- 只匹配 info 级别行；dial 报错行（`match Match/`、`match RuleSet/xxx`）天然不匹配
- 聚合每个目标的发起进程名与出现次数（日志行中源地址后的 `(进程名)` 字段）

内置过滤（不再依赖人工排除）：
- 无 TLD 伪域名（monitor_browser / kwrt / lan 等）
- 探针族：wpad、*.dotnxdomain.net / *.dashnxdomain.net / *.starnxdomain.net、
  root-key-sentinel-* 标签（NextDNS + DNSSEC 探针）
- 私有 / 保留 IP 段（RFC1918、loopback、link-local、CGNAT、组播等）
- skip-list.txt 清单：skip 项不进候选，manual 项单列 manual-review 段

输出段（均为纯文本，按总次数降序）：
- # summary            本轮统计（各类计数）
- # domains            候选域名表：域名 | 类别 | 次数 | 进程(次数)
- # registrable        主域归并：主域 <- 子域(次数), ...
- # public-ips         公网裸 IP：IP | 类别 | 次数 | 进程(次数)
- # manual-review      skip-list manual 项本轮命中（待人工，不参与自动裁决）
- # skipped            skip-list skip 项本轮命中（审计用）

类别缩写：mm = match Match，oc = oc-cn-domain。
主域归并为启发式（常见二级 TLD 如 com.cn 取三级，其余取两级），无 publicsuffix
数据依赖；个别特殊后缀可能归并不准，落盘前仍须按 AGENTS.md 判据复核。
"""
import argparse
import ipaddress
import re
import sys
from collections import Counter
from pathlib import Path

LINE_RE = re.compile(r"--> (\S+):\d+ match (Match|RuleSet\(oc-cn-domain\)) using")
PROC_RE = re.compile(r"\(([^()]+)\) -->")

PROBE_EXACT = {"wpad"}
PROBE_SUFFIXES = (".dotnxdomain.net", ".dashnxdomain.net", ".starnxdomain.net")

# 常见"二级 TLD"：命中时可注册主域取三级标签
MULTI_TLDS = {
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn", "mil.cn",
    "com.hk", "com.tw", "com.sg", "com.au", "com.br", "com.mx", "com.ru",
    "com.tr", "com.ua", "com.vn", "co.uk", "org.uk", "co.jp", "co.kr",
    "co.in", "co.nz", "co.za", "com.ar", "com.co", "com.my", "com.ph",
}


def registrable(host: str) -> str:
    """启发式可注册主域：常见二级 TLD 取三级标签，其余取两级。"""
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in MULTI_TLDS and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_probe(host: str) -> bool:
    if host in PROBE_EXACT or host.endswith(PROBE_SUFFIXES):
        return True
    return any(lbl.startswith("root-key-sentinel") for lbl in host.split("."))


def is_public_ip(host: str) -> bool:
    """是合法 IP 且非私有/保留/特殊段。"""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    bad = (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )
    return not bad


def load_skip_list(path: Path):
    """返回 (skip: {后缀: 原因}, manual: {后缀: 原因})。"""
    skip, manual = {}, {}
    if not path.exists():
        return skip, manual
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        pattern, rest = parts[0].lower(), parts[1].strip()
        mode, _, reason = rest.partition(":")
        target = skip if mode == "skip" else manual
        target[pattern] = reason.strip() or mode
    return skip, manual


def skip_hit(host: str, table: dict):
    """后缀匹配：host 等于 pattern 或以 .pattern 结尾。"""
    for pattern, reason in table.items():
        if host == pattern or host.endswith("." + pattern):
            return pattern, reason
    return None, None


def collect_logs(paths):
    for p in map(Path, paths):
        if p.is_dir():
            yield from sorted(p.rglob("*.log"))
        else:
            yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="日志文件或目录")
    ap.add_argument(
        "--skip-list",
        default=str(Path(__file__).resolve().parent / "skip-list.txt"),
        help="跳过清单路径（默认：脚本旁 skip-list.txt）",
    )
    args = ap.parse_args()

    skip_tbl, manual_tbl = load_skip_list(Path(args.skip_list))

    entries = {}   # host -> {"cats": set, "count": int, "procs": Counter}
    manual_hit = {}  # host -> entry（skip-list manual 命中）
    skip_hit_map = {}  # host -> entry（skip-list skip 命中）
    stats = Counter()
    n_logs = 0

    def record(table: dict, host: str, cat: str, proc: str):
        e = table.setdefault(host, {"cats": set(), "count": 0, "procs": Counter()})
        e["cats"].add(cat)
        e["count"] += 1
        if proc:
            e["procs"][proc] += 1

    for log in collect_logs(args.paths):
        n_logs += 1
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            m = LINE_RE.search(line)
            if not m:
                continue
            host, category = m.group(1).strip(".[]"), m.group(2)
            host = host.lower()
            cat = "mm" if category == "Match" else "oc"
            pm = PROC_RE.search(line)
            proc = pm.group(1) if pm else ""
            try:
                ipaddress.ip_address(host)
                is_ip = True
            except ValueError:
                is_ip = False
            if is_ip:
                if is_public_ip(host):
                    record(entries, host, cat, proc)
                else:
                    stats["private-ip-filtered"] += 1
                continue
            if "." not in host:
                stats["pseudo-filtered"] += 1
                continue
            if is_probe(host):
                stats["probe-filtered"] += 1
                continue
            if skip_hit(host, skip_tbl)[0]:
                record(skip_hit_map, host, cat, proc)
                continue
            if skip_hit(host, manual_tbl)[0]:
                record(manual_hit, host, cat, proc)
                continue
            record(entries, host, cat, proc)

    def fmt_entry(host, e, extra=""):
        cats = "+".join(sorted(e["cats"]))
        procs = ", ".join(f"{p}({n})" for p, n in e["procs"].most_common())
        line = f"{host} | {cats} | {e['count']} | {procs}"
        return line + (f" | {extra}" if extra else "")

    def dump_table(title, table, extra_fn=None):
        print(title)
        if not table:
            print("（无）")
            return
        for host in sorted(table, key=lambda h: (-table[h]["count"], h)):
            print(fmt_entry(host, table[host], extra_fn(host) if extra_fn else ""))
        print()

    # --- summary ---
    domains, ips = {}, {}
    for h, e in entries.items():
        try:
            ipaddress.ip_address(h)
            ips[h] = e
        except ValueError:
            domains[h] = e
    mm_d = sum(1 for e in domains.values() if "mm" in e["cats"])
    oc_d = sum(1 for e in domains.values() if "oc" in e["cats"])
    mm_i = sum(1 for e in ips.values() if "mm" in e["cats"])
    oc_i = sum(1 for e in ips.values() if "oc" in e["cats"])

    print("# summary")
    print(f"logs: {n_logs}")
    print(f"candidate domains: {len(domains)} (mm {mm_d} / oc {oc_d})")
    print(f"public ips: {len(ips)} (mm {mm_i} / oc {oc_i})")
    print(f"manual-review hits: {len(manual_hit)}; skip-list hits: {len(skip_hit_map)}")
    print(
        f"filtered: pseudo {stats['pseudo-filtered']}, probe {stats['probe-filtered']}, "
        f"private-ip {stats['private-ip-filtered']}"
    )
    print()

    # --- domains ---
    dump_table("# domains（域名 | 类别 | 次数 | 进程）", domains)

    # --- registrable ---
    print("# registrable（主域归并）")
    groups = {}
    for h in domains:
        groups.setdefault(registrable(h), []).append(h)
    if not groups:
        print("（无）")
    else:
        for rd in sorted(groups, key=lambda r: (-sum(domains[h]["count"] for h in groups[r]), r)):
            subs = ", ".join(
                f"{h}({domains[h]['count']})" for h in sorted(groups[rd])
            )
            print(f"{rd} <- {subs}")
    print()

    # --- public-ips ---
    dump_table("# public-ips（IP | 类别 | 次数 | 进程）", ips)

    # --- manual-review ---
    def manual_reason(host):
        p, r = skip_hit(host, manual_tbl)
        return f"{r} [skip-list: {p}]"
    dump_table("# manual-review（待人工，不参与自动裁决）", manual_hit, manual_reason)

    # --- skipped ---
    def skip_reason(host):
        p, r = skip_hit(host, skip_tbl)
        return f"{r} [skip-list: {p}]"
    dump_table("# skipped（skip-list 命中，审计）", skip_hit_map, skip_reason)


if __name__ == "__main__":
    main()
