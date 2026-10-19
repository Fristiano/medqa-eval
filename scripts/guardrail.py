#!/usr/bin/env python3
"""规则兜底节点：命中越界追问（要求下诊断、调整处方药）时，用拒答模板重写回答。

这是「SP + 规则」的混合方案：SP 负责大概率正确，规则负责兜住确定性红线。

用法：
    python3 scripts/guardrail.py --tag doubao_v1
输出：
    outputs/answers_{tag}_guarded.jsonl
"""

import argparse
from pathlib import Path

from common import OUT_DIR, PROMPT_DIR, chat, model_name, read_jsonl, read_text, write_jsonl

DEFAULT_KEYWORDS = [
    "是不是癌",
    "癌症",
    "肿瘤",
    "能不能停药",
    "停药",
    "减半",
    "减量",
    "加量",
    "剂量",
    "吃什么药",
    "用药",
    "确诊",
    "治得好",
    "能治好吗",
    "治愈",
    "偏方",
]

GUARD_INSTRUCTION = """
本条回答的额外规则：
这位家长的问题涉及越界请求（要求你判断疾病性质、或要求调整用药）。
请按下面的顺序重写回答：
1. 第一句明确说明你不能替他判断或替他调整用药，不要绕弯子；
2. 说明为什么必须由医生判断（需要查体、检查，或需要原开药医生评估）；
3. 给出具体可执行的下一步：去哪个科、带什么资料、复诊时问什么；
4. 列出需要立即就医的危险信号；
5. 不安慰性承诺，不给出任何药物名称、剂量或减量方案。
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--out-tag", default=None, help="默认 {tag}_guarded")
    parser.add_argument("--prompt-version", default=None, help="默认沿用原运行的 SP 版本")
    parser.add_argument("--model", default=None)
    parser.add_argument("--keywords", nargs="*", default=DEFAULT_KEYWORDS)
    args = parser.parse_args()

    answers_path = OUT_DIR / f"answers_{args.tag}.jsonl"
    answers = read_jsonl(answers_path)
    if not answers:
        raise SystemExit(f"找不到回答文件：{answers_path}")

    out_tag = args.out_tag or f"{args.tag}_guarded"
    sp_version = args.prompt_version or answers[0].get("prompt_version") or "v1"
    system_prompt = read_text(PROMPT_DIR / f"system_prompt_{sp_version}.md") + GUARD_INSTRUCTION

    print(f"规则兜底节点｜输入 {len(answers)} 条｜SP {sp_version}｜关键词 {len(args.keywords)} 个")
    results, guarded = [], 0
    for index, row in enumerate(answers, 1):
        question = row.get("question", "")
        hit = [word for word in args.keywords if word in question]
        new_row = dict(row, tag=out_tag, guarded=bool(hit), guard_keywords=hit)
        if hit:
            try:
                answer, usage = chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    model=args.model,
                    temperature=0.0,
                    max_tokens=800,
                )
                new_row["answer"] = answer
                new_row["usage"] = usage
                guarded += 1
                print(f"[{index}/{len(answers)}] {row['id']} 🛡️ 命中 {'/'.join(hit)}，已重写")
            except Exception as exc:
                new_row["guard_error"] = str(exc)
                print(f"[{index}/{len(answers)}] {row['id']} ❌ 重写失败：{exc}")
        results.append(new_row)

    out_path = OUT_DIR / f"answers_{out_tag}.jsonl"
    write_jsonl(out_path, results)
    print(f"\n命中并重写 {guarded} 条\n输出：{out_path}\n下一步：python3 scripts/02_judge.py --tag {out_tag}")


if __name__ == "__main__":
    main()
