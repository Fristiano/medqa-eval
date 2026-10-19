#!/usr/bin/env python3
"""③ 汇总指标、生成 Markdown 报告与图表，并可选做上线门禁。

用法：
    python3 scripts/03_report.py --tag doubao_v1
    python3 scripts/03_report.py --tag doubao_v1 --min-pass-rate 0.8 --max-violations 0

门禁：不达标时返回非零退出码，可接入上线流程（CI / 发布检查）。
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

from statistics import mean

from common import (
    COVER_MAX,
    FLAG_MAX,
    GRADE_MAX,
    OUT_DIR,
    REPORT_DIR,
    SAFETY_MAX,
    read_jsonl,
    summarize_rows,
)


def pct(value):
    return "—" if value is None else f"{100 * value:.1f}%"


def grouped(rows, key):
    buckets = defaultdict(list)
    for row in rows:
        buckets[row.get(key)].append(row)
    return dict(sorted(buckets.items(), key=lambda kv: str(kv[0])))


def make_charts(rows, tag, summary):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("未安装 matplotlib，跳过图表（pip3 install matplotlib 后可出图）")
        return []

    plt.rcParams["font.sans-serif"] = [
        "PingFang SC",
        "Arial Unicode MS",
        "Heiti TC",
        "SimHei",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    fig_dir = REPORT_DIR / "figs"
    fig_dir.mkdir(parents=True, exist_ok=True)
    figures = []

    # 图 1：各类别通过率
    by_category = grouped(rows, "category")
    labels = list(by_category.keys())
    rates = [sum(1 for r in by_category[k] if r["pass"]) / len(by_category[k]) for k in labels]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, [r * 100 for r in rates], color="#4C78A8")
    ax.set_ylabel("通过率 (%)")
    ax.set_ylim(0, 105)
    ax.set_title(f"各类别通过率 · {tag}")
    plt.xticks(rotation=20)
    for index, value in enumerate(rates):
        ax.text(index, value * 100 + 2, f"{value * 100:.0f}%", ha="center", fontsize=9)
    fig.tight_layout()
    path1 = fig_dir / f"report_{tag}_by_category.png"
    fig.savefig(path1, dpi=150)
    plt.close(fig)
    figures.append(path1)

    # 图 2：四维得分率
    dimensions = ["安全底线", "分级正确", "红旗信号", "要点覆盖"]
    values = [
        mean([r.get("safety_score", 0) for r in rows]) / SAFETY_MAX * 100,
        mean([r.get("grade_score", 0) for r in rows]) / GRADE_MAX * 100,
        mean([r["red_flag_score"] for r in rows if r.get("red_flag_score") is not None] or [0])
        / FLAG_MAX
        * 100,
        mean([r.get("coverage_score", 0) for r in rows]) / COVER_MAX * 100,
    ]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(dimensions, values, color="#F58518")
    ax.set_ylabel("得分率 (%)")
    ax.set_ylim(0, 105)
    ax.set_title(f"四维得分率 · {tag}")
    for index, value in enumerate(values):
        ax.text(index, value + 2, f"{value:.0f}%", ha="center", fontsize=9)
    fig.tight_layout()
    path2 = fig_dir / f"report_{tag}_dimensions.png"
    fig.savefig(path2, dpi=150)
    plt.close(fig)
    figures.append(path2)
    return figures


def build_markdown(rows, tag, summary, charts):
    models = sorted({r.get("model") or "—" for r in rows})
    sp_versions = sorted({str(r.get("prompt_version") or "—") for r in rows})
    bad = [r for r in rows if not r["pass"]]

    lines = []
    lines.append(f"# 评测报告 · {tag}")
    lines.append("")
    lines.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 被测模型：{', '.join(models)}")
    lines.append(f"- System Prompt 版本：{', '.join(sp_versions)}")
    lines.append(f"- 用例数：{summary['n']} 条（裁判失败 {summary['judge_errors']} 条）")
    lines.append("")
    lines.append("## 一、结论")
    lines.append("")
    lines.append(
        f"- 通过率：**{summary['passed']}/{summary['n']}（{pct(summary['pass_rate'])}）**"
    )
    lines.append(
        f"- 安全违规：**{summary['violations_total']} 处**，涉及 {summary['violations_items']} 条用例"
    )
    lines.append(
        f"- 分级准确率：{pct(summary['grade_exact'])}（允许差 1 级：{pct(summary['grade_within1'])}）"
    )
    lines.append(
        f"- 红旗信号召回率：{pct(summary['flag_full'])}（{summary['flag_rows']} 条用例需要紧急就医指引）"
    )
    lines.append(f"- 要点覆盖率均值：{pct(summary['coverage'])}")
    lines.append(f"- 平均总分：{summary['avg_total']:.1f}")
    lines.append("")

    lines.append("## 二、分场景指标")
    lines.append("")
    lines.append("| 类别 | 用例数 | 通过率 | 平均总分 | 安全违规 | 分级准确率 | 要点覆盖 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for key, bucket in grouped(rows, "category").items():
        stats = summarize_rows(bucket)
        lines.append(
            f"| {key} | {stats['n']} | {pct(stats['pass_rate'])} | {stats['avg_total']:.1f} | "
            f"{stats['violations_total']} | {pct(stats['grade_exact'])} | {pct(stats['coverage'])} |"
        )
    lines.append("")

    lines.append("## 三、分严重程度指标（分级能力）")
    lines.append("")
    lines.append("| 严重程度 | 用例数 | 通过率 | 平均总分 | 分级准确率 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for key, bucket in grouped(rows, "severity").items():
        stats = summarize_rows(bucket)
        lines.append(
            f"| {key} 级 | {stats['n']} | {pct(stats['pass_rate'])} | {stats['avg_total']:.1f} | "
            f"{pct(stats['grade_exact'])} |"
        )
    lines.append("")

    lines.append("## 四、未通过用例（badcase 清单）")
    lines.append("")
    if bad:
        lines.append("| 编号 | 类别 | 分级 | 总分 | 安全违规 | 主要问题 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in sorted(bad, key=lambda r: r["total"]):
            lines.append(
                f"| {row['id']} | {row['category']} | {row['severity']} | {row['total']} | "
                f"{len(row['violations'])} | {row.get('comment') or row.get('judge_error') or ''} |"
            )
        lines.append("")
        lines.append("> 逐条归因（属于哪类能力缺陷、SP 能不能解决）见 `docs/badcase_analysis.md`。")
    else:
        lines.append("本批全部通过。")
    lines.append("")

    if charts:
        lines.append("## 五、图表")
        lines.append("")
        for path in charts:
            lines.append(f"![{path.stem}](figs/{path.name})")
        lines.append("")

    lines.append("## 六、下一步建议（自动生成）")
    lines.append("")
    if summary["violations_total"]:
        lines.append(
            f"- 安全违规 {summary['violations_total']} 处是最高优先级：逐条看 `violations` 字段，"
            "判断是 SP 能约束（加规则/模板），还是需要靠数据与训练解决。"
        )
    weak = min(
        [
            ("分级准确率", summary["grade_exact"]),
            ("红旗信号召回率", summary["flag_full"] or 1.0),
            ("要点覆盖率", summary["coverage"]),
        ],
        key=lambda kv: kv[1],
    )
    lines.append(f"- 当前最弱维度是「{weak[0]}」（{pct(weak[1])}）：先在失败用例里做聚类，再一次只改一个 SP 变量。")
    lines.append("- 每轮改动都记进 `prompts/prompt_changelog.md`，用 `05_compare_runs.py` 出消融表。")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--min-pass-rate", type=float, default=None, help="门禁：最低通过率，如 0.8")
    parser.add_argument("--max-violations", type=int, default=None, help="门禁：允许的最大安全违规数")
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args()

    judged_path = OUT_DIR / f"judged_{args.tag}.jsonl"
    rows = read_jsonl(judged_path)
    if not rows:
        raise SystemExit(f"找不到评分文件：{judged_path}\n请先运行 02_judge.py")

    summary = summarize_rows(rows)
    charts = [] if args.no_charts else make_charts(rows, args.tag, summary)

    report_path = REPORT_DIR / f"report_{args.tag}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_markdown(rows, args.tag, summary, charts), encoding="utf-8")

    print(
        f"用例 {summary['n']} 条｜通过 {summary['passed']}（{pct(summary['pass_rate'])}）｜"
        f"安全违规 {summary['violations_total']} 处｜平均总分 {summary['avg_total']:.1f}"
    )
    print(f"报告：{report_path}")

    failures = []
    if args.min_pass_rate is not None and summary["pass_rate"] < args.min_pass_rate:
        failures.append(f"通过率 {pct(summary['pass_rate'])} 低于要求 {pct(args.min_pass_rate)}")
    if args.max_violations is not None and summary["violations_total"] > args.max_violations:
        failures.append(
            f"安全违规 {summary['violations_total']} 处超过上限 {args.max_violations} 处"
        )
    if failures:
        print("\n❌ 门禁未通过：")
        for item in failures:
            print(f"  - {item}")
        sys.exit(1)
    if args.min_pass_rate is not None or args.max_violations is not None:
        print("\n✅ 门禁通过")


if __name__ == "__main__":
    main()
