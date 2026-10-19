#!/usr/bin/env python3
"""④ 扩样：把脱敏后的病历文本批量转成候选用例（机器构造 + 待人工审核）。

准备：把脱敏后的病历文本（.txt / .md，一份病历一个文件）放进 data_raw/。
输出：data/candidates_v2.csv，最后一列「人工审核结论」留空，必须人工过一遍才能并入评测集。

用法：
    python3 scripts/04_generate_cases.py --dir data_raw --model doubao-seed-2-1-lite-260915
"""

import argparse
import csv
import json
import re
from pathlib import Path

from common import PROMPT_DIR, ROOT, chat, model_name, read_text, render

FIELDS = [
    "候选编号",
    "来源文件",
    "question",
    "severity",
    "severity_reason",
    "expected_points",
    "forbidden",
    "red_flag",
    "人工审核结论",
    "参考答案（人工补写）",
]


def parse_json_block(text: str) -> dict:
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", text.strip())
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("模型输出里没有找到 JSON")
    return json.loads(cleaned[start : end + 1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(ROOT / "data_raw"), help="存放脱敏病历文本的目录")
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default=str(ROOT / "data" / "candidates_v2.csv"))
    parser.add_argument("--max-files", type=int, default=0)
    args = parser.parse_args()

    source_dir = Path(args.dir)
    if not source_dir.exists():
        raise SystemExit(
            f"目录不存在：{source_dir}\n"
            "请先把脱敏后的病历文本（一份一个 .txt 文件）放进去。"
            "注意：病历原件含患者信息，不要放进仓库。"
        )

    files = sorted([p for p in source_dir.glob("*") if p.suffix.lower() in (".txt", ".md")])
    if args.max_files:
        files = files[: args.max_files]
    if not files:
        raise SystemExit(f"{source_dir} 里没有 .txt / .md 文件")

    template = read_text(PROMPT_DIR / "gen_case_prompt.md")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not out_path.exists()

    print(f"模型：{model_name(args.model)}｜待处理病历 {len(files)} 份")
    with out_path.open("a", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        for index, path in enumerate(files, 1):
            record = read_text(path)
            prompt = render(template, {"record_text": record})
            try:
                text, _ = chat(
                    [{"role": "user", "content": prompt}],
                    model=args.model,
                    temperature=0.3,
                    max_tokens=1500,
                )
                data = parse_json_block(text)
            except Exception as exc:
                print(f"[{index}/{len(files)}] {path.name} ❌ {exc}")
                continue
            writer.writerow(
                {
                    "候选编号": f"D{index:03d}",
                    "来源文件": path.name,
                    "question": data.get("question", ""),
                    "severity": data.get("severity", ""),
                    "severity_reason": data.get("severity_reason", ""),
                    "expected_points": " | ".join(data.get("expected_points") or []),
                    "forbidden": " | ".join(data.get("forbidden") or []),
                    "red_flag": data.get("red_flag", ""),
                    "人工审核结论": "",
                    "参考答案（人工补写）": "",
                }
            )
            print(f"[{index}/{len(files)}] {path.name} ✅ 生成候选 {index}")

    print(
        f"\n候选写入：{out_path}\n"
        "下一步（必须人工做完）：\n"
        "  1. 逐条审核 question / 期望要点 / 禁忌项 / 分级是否合理；\n"
        "  2. 补写参考答案；\n"
        "  3. 「人工审核结论」填 采纳 / 修改后采纳 / 丢弃；\n"
        "  4. 采纳的条目补进 data/evalset_v2.jsonl，并把 source 标为「机器构造」。"
    )


if __name__ == "__main__":
    main()
