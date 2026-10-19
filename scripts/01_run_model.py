#!/usr/bin/env python3
"""① 批量调用被测模型，把回答落盘（支持断点续跑）。

用法：
    python3 scripts/01_run_model.py --tag doubao_v1 --prompt-version v1
    python3 scripts/01_run_model.py --tag deepseek_v1 --model deepseek-chat --limit 5
"""

import argparse
import time
from pathlib import Path

from common import (
    DEFAULT_DATASET,
    OUT_DIR,
    PROMPT_DIR,
    append_jsonl,
    chat,
    model_name,
    read_jsonl,
    read_text,
    write_manifest,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="本次运行的标签，决定输出文件名")
    parser.add_argument("--prompt-version", default="v1", help="system prompt 版本，如 v1 / v2")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--model", default=None, help="覆盖环境变量里的模型")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（调试用）")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=800)
    args = parser.parse_args()

    dataset = read_jsonl(args.dataset)
    if not dataset:
        raise SystemExit(f"评测集为空或不存在：{args.dataset}")
    if args.limit:
        dataset = dataset[: args.limit]

    system_prompt = read_text(PROMPT_DIR / f"system_prompt_{args.prompt_version}.md")
    out_path = OUT_DIR / f"answers_{args.tag}.jsonl"
    done = {row["id"] for row in read_jsonl(out_path)}

    print(f"模型：{model_name(args.model)}｜SP：{args.prompt_version}｜用例 {len(dataset)} 条｜已完成 {len(done)} 条")
    ok = failed = tokens_in = tokens_out = 0
    returned_models = set()

    for index, item in enumerate(dataset, 1):
        if item["id"] in done:
            print(f"[{index}/{len(dataset)}] {item['id']} 已完成，跳过")
            continue

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": item["question"]},
        ]
        row = {
            "id": item["id"],
            "tag": args.tag,
            "model": model_name(args.model),
            "model_requested": model_name(args.model),
            "prompt_version": args.prompt_version,
            "question": item["question"],
        }
        started = time.time()
        try:
            answer, meta = chat(
                messages, model=args.model, temperature=args.temperature, max_tokens=args.max_tokens
            )
            row["answer"] = answer
            row["latency_ms"] = int((time.time() - started) * 1000)
            # 以接口实际返回的模型名为准；拿不到才退回配置里的名字
            row["model"] = meta.get("model") or row["model_requested"]
            row["usage"] = {k: v for k, v in meta.items() if k != "model"}
            returned_models.add(row["model"])
            tokens_in += int(meta.get("prompt_tokens") or 0)
            tokens_out += int(meta.get("completion_tokens") or 0)
            ok += 1
            print(f"[{index}/{len(dataset)}] {item['id']} ✅ {row['latency_ms']}ms")
        except Exception as exc:
            row["answer"] = ""
            row["error"] = str(exc)
            failed += 1
            print(f"[{index}/{len(dataset)}] {item['id']} ❌ {exc}")
        append_jsonl(out_path, row)

    manifest = write_manifest(
        f"{time.strftime('%Y%m%d-%H%M%S')}_{args.tag}",
        {
            "stage": "run_model",
            "tag": args.tag,
            "model": model_name(args.model),
            "model_returned": sorted(returned_models),
            "prompt_version": args.prompt_version,
            "dataset": {"name": Path(args.dataset).name, "n": len(dataset)},
            "params": {"temperature": args.temperature, "max_tokens": args.max_tokens},
            "usage": {"prompt_tokens": tokens_in, "completion_tokens": tokens_out},
            "result": {"ok": ok, "failed": failed},
        },
    )
    print(f"\n完成：成功 {ok} 条，失败 {failed} 条\n回答文件：{out_path}\n运行快照：{manifest}")


if __name__ == "__main__":
    main()
