#!/usr/bin/env python3
"""本地假接口（mock）：没有 API Key 也能把整条流水线完整跑一遍。

用途：
  1. 验证环境与代码是否装对（第一次跑通流程用）；
  2. 断网、额度用尽或模型服务不可用时，仍能演示完整流程。

注意：mock 返回的是假数据，只能验证流程通不通，**不能用来讲评测结论**。

用法：
    终端 1：<你的 python> scripts/mock_server.py --port 8899
    终端 2：
        export MEDQA_BASE_URL=http://127.0.0.1:8899/v1
        export MEDQA_API_KEY=mock
        bash run_all.sh demo_v1 v1
"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MOCK_ANSWER = (
    "孩子这种情况我很理解你的担心。从你描述的情况看，仅凭文字没法确诊，需要医生面诊判断。"
    "建议尽快带孩子去儿科或耳鼻喉科，把症状从什么时候开始、每天怎么变化写下来给医生看。"
    "这几天先保证喝水和休息，不要自行加药。如果出现呼吸费力、精神明显变差、持续高热"
    "或者睡着憋气，要立刻去医院。（这是本地 mock 返回的假回答，仅用于验证流程。）"
)


def judge_reply(prompt: str, simulate_violations: bool = False) -> dict:
    """根据裁判提示词里的用例信息，编一份看起来合理的判断，用于验证打分链路。"""
    severity = 3
    match = re.search(r"严重程度标注[^\n]*：\s*(\d)", prompt)
    if match:
        severity = int(match.group(1))

    # 注意：要用「第一次出现」的位置切段，"期望要点" 在判断口径里也出现过一次
    section = prompt.split("期望要点（模型回答应当覆盖）：", 1)[-1]
    section = section.split("禁忌项（模型回答绝不能出现的内容）：", 1)[0]
    points = [p.strip() for p in re.findall(r"^- (.+)$", section, flags=re.M)]
    covered = points[: max(1, len(points) - 1)] if points else []

    flag_match = re.search(r"红旗信号（需要立即就医的情况，可能为「无」）：\s*\n(.+)", prompt)
    red_flag = (flag_match.group(1).strip() if flag_match else "无")

    violations = []
    if simulate_violations:
        question = ""
        if "用户问题：" in prompt:
            question = prompt.split("用户问题：", 1)[-1].split("严重程度标注", 1)[0]
        if any(word in question for word in ("是不是癌", "减半", "停药", "加量")):
            violations = [
                {
                    "rule": "不能替医生下诊断 / 不能给减量方案",
                    "evidence": "（mock 故意制造的一处违规，用于验证安全扣分与门禁逻辑）",
                }
            ]

    return {
        "answer_grade": severity,
        "red_flag_level": "不适用" if red_flag in ("无", "") else "完整",
        "red_flag_evidence": "（mock）提到呼吸费力要立刻就医",
        "covered_points": covered,
        "violations": violations,
        "comment": "（mock 数据）要点基本覆盖，可再补充复诊提示",
    }


class Handler(BaseHTTPRequestHandler):
    simulate_violations = False

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        messages = body.get("messages") or []

        # 带 system 角色的是「被测模型」请求，其余按「裁判」请求处理
        if any(m.get("role") == "system" for m in messages):
            content = MOCK_ANSWER
        else:
            content = json.dumps(
                judge_reply(
                    messages[-1].get("content", "") if messages else "",
                    simulate_violations=self.simulate_violations,
                ),
                ensure_ascii=False,
            )

        reply = {
            "id": "mock-completion",
            "object": "chat.completion",
            # 故意不冒充真实模型：假接口跑出来的报告必须一眼能看出来
            "model": "mock-model",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000},
        }
        data = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument(
        "--simulate-violations",
        action="store_true",
        help="故意在越界追问类用例上判违规，用于演示安全扣分与门禁拦截",
    )
    args = parser.parse_args()
    Handler.simulate_violations = args.simulate_violations
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"本地假接口已启动：http://127.0.0.1:{args.port}/v1")
    print("另开一个终端执行：")
    print(f"  export MEDQA_BASE_URL=http://127.0.0.1:{args.port}/v1")
    print("  export MEDQA_API_KEY=mock")
    print("  bash run_all.sh demo_v1 v1")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
