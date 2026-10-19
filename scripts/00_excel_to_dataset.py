#!/usr/bin/env python3
"""⓪ 把 Excel 评测表转成数据集（jsonl + csv）。仓库已带好 evalset_v1，此脚本用于复现与更新。

用法：
    python3 scripts/00_excel_to_dataset.py --xlsx "/路径/医疗测评.xlsx" --version v1

字段映射见 docs/methodology.md 附录与 data/README.md。
"""

import argparse
import csv
import json
import re
from pathlib import Path

from common import DATA_DIR

COLUMN_MAP = {
    "编号": "id",
    "类别": "category",
    "用户原话": "question",
    "期望要点": "expected_points",
    "禁忌项": "forbidden",
    "严重程度（1-5）": "severity",
    "红旗信号": "red_flag",
    "题源类型": "source",
    "参考答案": "reference_answer",
}

CSV_FIELDS = list(COLUMN_MAP.values())


def split_numbered(text: str):
    """「1. xxx；2. yyy」→ ['xxx', 'yyy']；没有序号时按分号拆。"""
    text = str(text or "").strip()
    if not text:
        return []
    if re.search(r"(?:^|；)\s*1[.、]", text):
        parts = re.split(r"(?:^|；)\s*\d+[.、]\s*", text)
    else:
        parts = text.split("；")
    return [p.strip() for p in parts if p.strip()]


def clean(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", required=True, help="Excel 评测表路径")
    parser.add_argument("--version", default="v1", help="输出文件名后缀，如 v1 / v2")
    parser.add_argument("--sheet", default=0)
    args = parser.parse_args()

    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("需要 pandas 与 openpyxl：pip3 install pandas openpyxl")

    frame = pd.read_excel(args.xlsx, sheet_name=args.sheet)
    missing = [col for col in COLUMN_MAP if col not in frame.columns]
    if missing:
        raise SystemExit(f"Excel 缺少这些列：{missing}\n现有列：{list(frame.columns)}")

    rows = []
    for _, raw in frame.iterrows():
        item_id = clean(raw["编号"])
        if not re.match(r"^[A-Za-z]\d{2,}$", item_id):
            continue  # 跳过空行与非用例行
        rows.append(
            {
                "id": item_id,
                "category": clean(raw["类别"]),
                "source": clean(raw["题源类型"]),
                "severity": int(float(raw["严重程度（1-5）"])),
                "red_flag": clean(raw["红旗信号"]) or "无",
                "question": clean(raw["用户原话"]),
                "expected_points": split_numbered(raw["期望要点"]),
                "forbidden": split_numbered(raw["禁忌项"]),
                "reference_answer": clean(raw["参考答案"]),
            }
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = DATA_DIR / f"evalset_{args.version}.jsonl"
    csv_path = DATA_DIR / f"evalset_{args.version}.csv"

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["expected_points"] = " | ".join(row["expected_points"])
            flat["forbidden"] = " | ".join(row["forbidden"])
            writer.writerow(flat)

    counts = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    print(f"共 {len(rows)} 条用例\n写入：{jsonl_path}\n写入：{csv_path}")
    print("类别分布：" + "，".join(f"{k} {v} 条" for k, v in sorted(counts.items())))
    print("请人工抽查 3 条，确认要点拆分正确（少数要点内部含分号，拆出 6 条属正常）。")


if __name__ == "__main__":
    main()
