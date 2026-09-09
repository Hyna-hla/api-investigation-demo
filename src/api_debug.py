#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Demo 2 / JSON-API 调试器 (API Investigator)
--------------------------------------------
输入 : baseline.json(期望的 request/response) 与 actual.json(实际抓到的 request/response)
流程 : 加载 -> 递归 diff -> 规则引擎标记异常字段 -> 生成 Markdown 分析报告
用法 :
    python api_debug.py baseline.json actual.json [-o report.md] [--max-latency-ms 500] [--tol 1e-6]
依赖 : 仅 Python 标准库
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 被认为是“耗时”的字段名(毫秒)，超过阈值即异常
LATENCY_KEYS = ("latency", "elapsed", "cost", "duration", "took", "responsetime")
# 业务错误码字段：期望值应为 0
BIZ_CODE_KEYS = ("errcode", "error_code", "code", "ret", "status_code")
SUCCESS_STATUS = set(range(200, 300))

SEV_RANK = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}


def load_json(p: Path):
    if not p.exists():
        sys.exit(f"[错误] 找不到文件: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"[错误] {p.name} 不是合法 JSON: {e}")


def _norm(v):
    """数字比较时 int/float 等价。"""
    return v


def diff(expected, actual, path="$", findings=None, tol=1e-6):
    """递归比较，产出异常字段列表。"""
    if findings is None:
        findings = []

    # 期望有值、实际为 null：优先单列为 null_unexpected
    if expected is not None and actual is None:
        findings.append(_f(path, "null_unexpected", expected, actual, "HIGH", "期望有值，实际返回 null"))
        return findings

    # 类型不一致
    if type(expected) is not type(actual) and not (
        isinstance(expected, (int, float)) and isinstance(actual, (int, float))
    ):
        findings.append(_f(path, "type_mismatch", expected, actual, "HIGH",
                           f"期望类型 {type(expected).__name__}，实际 {type(actual).__name__}"))
        return findings

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            findings.append(_f(path, "type_mismatch", expected, actual, "HIGH", "期望对象，实际非对象"))
            return findings
        for k in expected:
            child = f"{path}.{k}"
            if k not in actual:
                findings.append(_f(child, "missing", expected[k], None, "HIGH", "期望中存在但响应缺失该字段"))
            else:
                diff(expected[k], actual[k], child, findings, tol)
        for k in actual:
            if k not in expected:
                findings.append(_f(f"{path}.{k}", "extra", None, actual[k], "LOW", "响应多出未约定字段(确认是否需要)"))
        return findings

    if isinstance(expected, list):
        if not isinstance(actual, list):
            findings.append(_f(path, "type_mismatch", expected, actual, "HIGH", "期望数组，实际非数组"))
            return findings
        if len(expected) != len(actual):
            findings.append(_f(path, "length_changed", len(expected), len(actual), "MEDIUM",
                               f"数组长度由 {len(expected)} 变为 {len(actual)}"))
        for i, (e_item, a_item) in enumerate(zip(expected, actual)):
            diff(e_item, a_item, f"{path}[{i}]", findings, tol)
        return findings

    # 标量比较
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        denom = max(abs(expected), 1e-9)
        if abs(expected - actual) / denom > tol:
            findings.append(_f(path, "value_changed", expected, actual, "MEDIUM", "数值偏离期望值，超出容差"))
        return findings

    if expected != actual:
        # 期望非空、实际为 null 单独高亮
        if expected is not None and actual is None:
            findings.append(_f(path, "null_unexpected", expected, actual, "HIGH", "期望有值，实际返回 null"))
        else:
            findings.append(_f(path, "value_changed", expected, actual, "MEDIUM", "字段取值与期望不一致"))
    return findings


def _f(path, kind, expected, actual, severity, reason):
    return {
        "path": path, "kind": kind, "expected": expected,
        "actual": actual, "severity": severity, "reason": reason,
    }


def rule_engine(actual_resp, findings, max_latency_ms):
    """在 diff 之外，对实际响应做独立的健康规则检查。"""
    def walk(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                child = f"{path}.{k}"
                kl = k.lower()
                # HTTP 状态码
                if kl in ("status", "http_status", "httpstatus") and isinstance(v, int):
                    if v not in SUCCESS_STATUS:
                        findings.append(_f(child, "bad_http_status", "2xx", v, "CRITICAL",
                                           f"HTTP 状态码 {v} 非 2xx，请求未成功"))
                # 业务错误码
                if kl in BIZ_CODE_KEYS and isinstance(v, (int, str)):
                    try:
                        if int(v) != 0 and kl != "status":
                            findings.append(_f(child, "biz_error", 0, v, "CRITICAL",
                                               f"业务错误码为 {v}(非 0)，接口返回业务失败"))
                    except ValueError:
                        pass
                # 耗时
                if any(lk in kl for lk in LATENCY_KEYS) and isinstance(v, (int, float)):
                    if v > max_latency_ms:
                        findings.append(_f(child, "slow", f"<= {max_latency_ms}", v, "MEDIUM",
                                           f"耗时 {v}ms 超过阈值 {max_latency_ms}ms"))
                walk(v, child)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(actual_resp)
    return findings


def collapse_duplicates(findings):
    """同一字段路径若已存在 HIGH 及以上问题，则丢弃它低级别、信息量重复的 value_changed。"""
    top_paths = {f["path"] for f in findings if SEV_RANK[f["severity"]] >= SEV_RANK["HIGH"]}
    out = []
    for f in findings:
        if (f["path"] in top_paths and SEV_RANK[f["severity"]] < SEV_RANK["HIGH"]
                and f["kind"] == "value_changed"):
            continue
        out.append(f)
    return out


def _short(v, limit=60):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    s = s.replace("|", "/").replace("\n", " ")
    return s if len(s) <= limit else s[:limit] + "…"


def build_report(base, act, findings, max_latency_ms):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    findings.sort(key=lambda x: -SEV_RANK[x["severity"]])
    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    crit_high = counts.get("CRITICAL", 0) + counts.get("HIGH", 0)
    verdict = "FAIL — 存在需立即处理的异常字段" if crit_high else (
        "WARN — 接口可用但存在偏差" if findings else "PASS — 与期望一致")

    req = act.get("request", base.get("request", {}))
    L = []
    L.append("# JSON / API 调试分析报告\n")
    L.append(f"> 由 `api_debug.py` 自动生成于 {now}\n")
    L.append("## 1. 结论\n")
    L.append(f"**判定：{verdict}**\n")
    L.append("| 严重级别 | 数量 |")
    L.append("| --- | ---: |")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        L.append(f"| {sev} | {counts.get(sev, 0)} |")
    L.append("")

    L.append("## 2. 请求回放\n")
    L.append("```json")
    L.append(json.dumps(req, ensure_ascii=False, indent=2)[:1200])
    L.append("```\n")

    L.append("## 3. 异常字段清单\n")
    if not findings:
        L.append("未发现任何字段差异或健康规则违例。\n")
    else:
        L.append("| 严重级别 | 字段路径 | 异常类型 | 期望值 | 实际值 | 说明 |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        for f in findings:
            L.append(f"| {f['severity']} | `{f['path']}` | {f['kind']} | "
                     f"{_short(f['expected'])} | {_short(f['actual'])} | {f['reason']} |")
        L.append("")

    L.append("## 4. 调查与定位思路\n")
    seen = set()
    for f in findings:
        key = f["kind"]
        bullet = None
        if key in ("bad_http_status", "biz_error"):
            bullet = (f"- `{f['path']}` 表明服务端返回失败：先看服务端同时段日志与该请求参数，"
                      "确认是参数问题还是下游依赖故障。")
        elif key == "missing":
            bullet = "- 字段缺失：确认接口版本是否变更、序列化是否忽略了空值、或该分支是否提前 return。"
        elif key == "type_mismatch":
            bullet = "- 类型不一致：常见于数字被序列化成字符串、对象被错误地包了一层数组，沿序列化层向上排查。"
        elif key in ("value_changed", "length_changed"):
            bullet = "- 取值/长度变化：判断是正常业务波动还是缺陷；若为金额/数量字段需重点核对计算逻辑。"
        elif key == "null_unexpected":
            bullet = "- 期望有值却为 null：排查上游数据是否缺失、外键关联是否断链。"
        elif key == "slow":
            bullet = f"- 耗时超过 {max_latency_ms}ms：检查慢查询、下游调用与是否命中缓存。"
        elif key == "extra":
            bullet = "- 多出字段：确认是否为新版本新增，避免客户端严格解析时报错。"
        if bullet and bullet not in seen:
            seen.add(bullet)
            L.append(bullet)
    L.append("")

    L.append("## 5. 复现命令\n")
    L.append("```bash")
    L.append("python api_debug.py samples/baseline.json samples/actual.json "
             f"--max-latency-ms {max_latency_ms}")
    L.append("```\n")
    return "\n".join(L), verdict


def main():
    ap = argparse.ArgumentParser(description="JSON/API 调试器：diff + 异常字段识别 + 报告")
    ap.add_argument("baseline", help="期望 request/response 的 JSON")
    ap.add_argument("actual", help="实际 request/response 的 JSON")
    ap.add_argument("-o", "--output", default="report/api-report.md")
    ap.add_argument("--max-latency-ms", type=float, default=500)
    ap.add_argument("--tol", type=float, default=1e-6)
    ap.add_argument("--json-out", default=None, help="可选：把结构化 findings 写到该 JSON")
    args = ap.parse_args()

    base = load_json(Path(args.baseline))
    act = load_json(Path(args.actual))
    base_resp, act_resp = base.get("response", base), act.get("response", act)

    findings = diff(base_resp, act_resp, tol=args.tol)
    findings = rule_engine(act_resp, findings, args.max_latency_ms)
    findings = collapse_duplicates(findings)

    report, verdict = build_report(base, act, findings, args.max_latency_ms)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[完成] 异常字段 {len(findings)} 个，判定：{verdict}")
    print(f"[输出] 报告已写入: {out.resolve()}")


if __name__ == "__main__":
    main()
