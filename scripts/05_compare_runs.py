#!/usr/bin/env python3
"""⑤ 生成 SP 消融表 / 多模型对比表（SP 调优最直接的证据）。

用法：
    python3 scripts/05_compare_runs.py --tags doubao_v1 doubao_v2 doubao_v3
    python3 scripts/05_compare_runs.py --tags doubao_v1 deepseek_v1 --out reports/model_compare.md
"""

import argparse
import time
from pathlib import Path

from common import OUT_DIR, REPORT_DIR, read_jsonl, summarize_rows


def pct(value):
    return "—" if value is None else f"{100 * value:.1f}%"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", nargs="+", required=True)
    parser.add_argument("--out", default=None, help="默认写入 reports/prompt_ablation.md")
    args = parser.parse_args()

    rows_by_tag = {}
    for tag in args.tags:
        rows = read_jsonl(OUT_DIR / f"judged_{tag}.jsonl")
        if not rows:
            print(f"⚠️ 跳过 {tag}：找不到 outputs/judged_{tag}.jsonl")
            continue
        rows_by_tag[tag] = rows

    if not rows_by_tag:
        raise SystemExit("没有可对比的结果，先跑 01_run_model.py 和 02_judge.py")

    lines = ["# 对比结果", "", f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
    lines.append(
        "| 运行标签 | 模型 | SP 版本 | 用例数 | 通过率 | 安全违规 | 分级准确率 | 红旗召回 | 要点覆盖 | 平均总分 |"
    )
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for tag, rows in rows_by_tag.items():
        stats = summarize_rows(rows)
        model = rows[0].get("model") or "—"
        sp = rows[0].get("prompt_version") or "—"
        lines.append(
            f"| {tag} | {model} | {sp} | {stats['n']} | **{pct(stats['pass_rate'])}** | "
            f"{stats['violations_total']} | {pct(stats['grade_exact'])} | {pct(stats['flag_full'])} | "
            f"{pct(stats['coverage'])} | {stats['avg_total']:.1f} |"
        )
    lines.append("")

    # 逐用例对比：同一批用例在不同运行下的通过情况
    common_ids = None
    for rows in rows_by_tag.values():
        ids = {r["id"] for r in rows}
        common_ids = ids if common_ids is None else (common_ids & ids)
    common_ids = sorted(common_ids or [])
    if common_ids:
        lines.append("## 逐用例对比（✅ 通过 / ❌ 未通过 / ⚠️ 裁判失败）")
        lines.append("")
        header = "| 用例 | 类别 | 分级 | " + " | ".join(rows_by_tag.keys()) + " |"
        lines.append(header)
        lines.append("| --- | --- | --- | " + " | ".join(["---"] * len(rows_by_tag)) + " |")
        for item_id in common_ids:
            cells = []
            meta = None
            for rows in rows_by_tag.values():
                found = next((r for r in rows if r["id"] == item_id), None)
                meta = meta or found
                if found is None:
                    cells.append("—")
                elif found.get("judge_error"):
                    cells.append("⚠️")
                else:
                    cells.append("✅" if found["pass"] else "❌")
            lines.append(
                f"| {item_id} | {meta['category']} | {meta['severity']} | " + " | ".join(cells) + " |"
            )
        lines.append("")

    out_path = Path(args.out) if args.out else REPORT_DIR / "prompt_ablation.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n对比表已写入：{out_path}")


if __name__ == "__main__":
    main()
