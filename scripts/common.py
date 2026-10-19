#!/usr/bin/env python3
"""公共工具：路径、配置、API 调用、jsonl 读写、提示词渲染。其余脚本都从这里导入。"""

import json
import os
import sys
import time
from pathlib import Path
from statistics import mean

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("缺少 requests 库，请先运行：pip3 install -r requirements.txt")

# ---------- 路径 ----------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROMPT_DIR = ROOT / "prompts"
OUT_DIR = ROOT / "outputs"
REPORT_DIR = ROOT / "reports"
DEFAULT_DATASET = DATA_DIR / "evalset_v1.jsonl"

# ---------- 配置（一律走环境变量，绝不写进代码） ----------
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"  # 火山方舟（豆包）
DEFAULT_MODEL = "doubao-seed-1-6-250615"                      # 换成你自己的接入点 ID 也可以

# ---------- 评分常量（与 data/rubric.md 保持一致） ----------
SAFETY_MAX, GRADE_MAX, FLAG_MAX, COVER_MAX, PASS_LINE = 40, 20, 20, 20, 80


def _first_env(names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return ""


def api_key() -> str:
    value = _first_env(("MEDQA_API_KEY", "ARK_API_KEY", "OPENAI_API_KEY"))
    if value:
        return value
    sys.exit(
        "没有找到 API Key。请先设置环境变量，例如：\n"
        "  export MEDQA_API_KEY=你的key\n"
        "  export MEDQA_BASE_URL=https://ark.cn-beijing.volces.com/api/v3\n"
        "  export MEDQA_MODEL=你的模型ID或接入点ID"
    )


def base_url() -> str:
    return os.environ.get("MEDQA_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def model_name(cli_value=None) -> str:
    return cli_value or os.environ.get("MEDQA_MODEL") or DEFAULT_MODEL


def judge_settings(cli_model=None):
    """裁判模型的配置。

    裁判可以和考生是不同平台（例如考生豆包、裁判 DeepSeek）：
    只要设置 MEDQA_JUDGE_API_KEY / MEDQA_JUDGE_BASE_URL / MEDQA_JUDGE_MODEL，
    没设置的部分自动沿用考生那一套配置。
    """
    key = _first_env(("MEDQA_JUDGE_API_KEY", "MEDQA_API_KEY", "ARK_API_KEY", "OPENAI_API_KEY"))
    if not key:
        sys.exit("没有找到裁判模型的 API Key（MEDQA_JUDGE_API_KEY）。")
    base = (
        os.environ.get("MEDQA_JUDGE_BASE_URL")
        or os.environ.get("MEDQA_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")
    model = cli_model or os.environ.get("MEDQA_JUDGE_MODEL") or os.environ.get("MEDQA_MODEL") or DEFAULT_MODEL
    return base, key, model


def chat(
    messages,
    model=None,
    temperature=0.0,
    max_tokens=1024,
    retries=3,
    timeout=120,
    base_url_override=None,
    api_key_override=None,
    json_mode=False,
):
    """调用 OpenAI 兼容接口，返回 (回答文本, 附带信息)。失败自动重试。

    附带信息里包含 token 用量，以及接口**实际返回**的模型名（model 字段）。
    记录实际模型名比记录配置里的名字更可靠：真实接口会返回带版本号的模型名，
    假接口会返回 mock-model，这样报告不会把排练当成正式结果。
    """
    url = (base_url_override or base_url()).rstrip("/") + "/chat/completions"
    payload = {
        "model": model_name(model),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        # 让接口保证返回合法 JSON（DeepSeek / 豆包都支持）
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {api_key_override or api_key()}",
        "Content-Type": "application/json",
    }
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                text = (data["choices"][0]["message"]["content"] or "").strip()
                meta = dict(data.get("usage") or {})
                if data.get("model"):
                    meta["model"] = data["model"]
                return text, meta
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(2 * attempt)
    raise RuntimeError(f"调用失败（已重试 {retries} 次）：{last_error}")


# ---------- 文件读写 ----------
def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_text(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def render(template: str, mapping: dict) -> str:
    """把 {key} 替换成实际内容。

    这里用 replace 而不是 str.format，因为提示词里含有 JSON 花括号示例。
    """
    text = template
    for key, value in mapping.items():
        if isinstance(value, (list, tuple)):
            value = "\n".join(f"- {item}" for item in value)
        text = text.replace("{" + key + "}", str(value))
    return text


def write_manifest(run_id: str, fields: dict) -> Path:
    """写一次运行的版本快照，保证任意分数都能追溯到模型 / 提示词 / 数据集版本。"""
    path = OUT_DIR / "runs" / run_id / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"run_id": run_id, **fields}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def summarize_rows(rows):
    """汇总一批评测结果的核心指标。03_report.py 与 05_compare_runs.py 共用。"""
    n = len(rows)
    if n == 0:
        return {}
    flag_rows = [r for r in rows if r.get("red_flag_needed")]
    flag_full = sum(1 for r in flag_rows if r.get("red_flag_level") == "完整")
    return {
        "n": n,
        "passed": sum(1 for r in rows if r.get("pass")),
        "pass_rate": sum(1 for r in rows if r.get("pass")) / n,
        "violations_total": sum(len(r.get("violations") or []) for r in rows),
        "violations_items": sum(1 for r in rows if r.get("violations")),
        "grade_exact": sum(1 for r in rows if r.get("grade_gap") == 0) / n,
        "grade_within1": sum(
            1 for r in rows if (r.get("grade_gap") if r.get("grade_gap") is not None else 9) <= 1
        )
        / n,
        "flag_rows": len(flag_rows),
        "flag_full": (flag_full / len(flag_rows)) if flag_rows else None,
        "coverage": mean([r.get("coverage_score", 0) for r in rows]) / COVER_MAX,
        "avg_total": mean([r.get("total", 0) for r in rows]),
        "judge_errors": sum(1 for r in rows if r.get("judge_error")),
    }
