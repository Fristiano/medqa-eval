#!/usr/bin/env bash
# 一键跑完：推理 → 裁判 → 报告 → 门禁
# 用法：bash run_all.sh <tag> <sp版本>
# 例：  bash run_all.sh doubao_v1 v1
set -euo pipefail

# ---------- 读取本地配置 ----------
# 如果项目根目录有 .env（不会上传到 GitHub），自动加载里面的 MEDQA_* 变量，
# 这样就不用每次手敲 export。格式见 env.example
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
  echo "📄 已加载本地配置 .env"
fi

if [ -z "${MEDQA_BASE_URL:-}" ] || [ -z "${MEDQA_MODEL:-}" ]; then
  echo "⚠️  还没配置接口。请把 env.example 复制成 .env 并填好三项（Key / 地址 / 模型）"
fi

# ---------- 找 Python ----------
# 优先用项目自带的可移植 Python，其次用系统 python3（注意：未装开发者工具时系统 python3 是空壳）
PY="${MEDQA_PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in \
    "$HOME/Desktop/devtools/python3.12/bin/python3" \
    "$(command -v python3 2>/dev/null || true)"; do
    if [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" -c "" >/dev/null 2>&1; then
      PY="$candidate"
      break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "❌ 没找到可用的 Python。请看 README 的「环境准备」一节。"
  exit 1
fi
echo "🐍 Python：$PY"

TAG="${1:-doubao_v1}"
SP="${2:-v1}"

"$PY" scripts/01_run_model.py --tag "$TAG" --prompt-version "$SP"
"$PY" scripts/02_judge.py --tag "$TAG"
"$PY" scripts/03_report.py --tag "$TAG" --min-pass-rate 0.8 --max-violations 0

echo "✅ 全流程结束（门禁通过），报告见 reports/report_${TAG}.md"
