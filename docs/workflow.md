# Workflow 说明

这条流水线的定位不是「一堆脚本」，而是一条**可复现、可追溯、有卡点、有回流**的评测 workflow。

## 节点表

**主链路（每一轮评测必跑）**

| 节点 | 脚本 | 输入 | 输出 | 失败处理 |
| --- | --- | --- | --- | --- |
| ⓪ 数据准备 | `00_excel_to_dataset.py` | Excel 评测表 | `data/evalset_v*.jsonl` / `.csv` | 列缺失直接报错；非用例行跳过 |
| ① 推理 | `01_run_model.py` | 评测集 + `system_prompt_v*.md` + 接口配置 | `outputs/answers_{tag}.jsonl` | 单条失败重试 3 次，仍失败则记 `error` 字段继续跑，不阻塞全量；已完成的 id 自动跳过（断点续跑） |
| ② 规则兜底（可选） | `guardrail.py` | `answers_{tag}.jsonl` | `answers_{tag}_guarded.jsonl` | 未命中关键词原样透传；重写失败记 `guard_error` |
| ③ 裁判打分 | `02_judge.py` | answers + 评测集 + `judge_prompt.md` | `outputs/judged_{tag}.jsonl` | JSON 解析失败重试 2 次；仍失败按 0 分计并标 `judge_error` |
| ④ 聚合与报告 | `03_report.py` | `judged_{tag}.jsonl` | `reports/report_{tag}.md` + `reports/figs/*.png` | 纯计算；未装 matplotlib 时自动跳过图表 |
| ⑤ 门禁判定 | `03_report.py --min-pass-rate --max-violations` | `judged_{tag}.jsonl` | 退出码 + 是否放行 | 不达标返回非零退出码，可卡住 CI / 发布 |

**支路与回流（跨轮次，不在主链路上顺序执行）**

| 节点 | 脚本 / 角色 | 输入 | 输出 | 说明 |
| --- | --- | --- | --- | --- |
| ⑥ 裁判抽检 | 人工（每轮） | `judged_{tag}.jsonl` 中按固定种子抽 10 条 | `reports/review_sample_v{轮次}.csv` | 校验**尺子**准不准：分级、违规认定、总分是否合理 |
| ⑦ 对比与消融 | `05_compare_runs.py` | 多个 `judged_*.jsonl` | `reports/prompt_ablation.md` | 跨轮次比较；必须同一评测集版本 |
| ⑧ 扩样 | `04_generate_cases.py` | `data_raw/*.txt` + `gen_case_prompt.md` | `data/candidates_v2.csv`（含「人工审核结论」空列） | 单份病历解析失败则跳过并提示 |
| ⑨ 数据回流 | 人工（累积） | 抽检分歧 + badcase 清单 + 扩样候选 | 审核后的新用例进 `evalset_v2` | 评测集自己长大；改动必须登记修订记录 |

> 一轮评测的完整闭环是：主链路 ⓪→⑤，然后 ⑥ 抽检裁判、⑦ 对比本轮与基线、⑧ 扩样补短板、⑨ 回流成新用例；下一轮从 ⓪ 重新开始。

## 运行配置

| 配置 | 变量 | 说明 |
| --- | --- | --- |
| 考生模型 | `MEDQA_API_KEY` / `MEDQA_BASE_URL` / `MEDQA_MODEL` | 必填 |
| 裁判模型 | `MEDQA_JUDGE_API_KEY` / `MEDQA_JUDGE_BASE_URL` / `MEDQA_JUDGE_MODEL` | 可选；不填则沿用考生配置 |
| 裁判输出预算 | `MEDQA_JUDGE_MAX_TOKENS` | 推理型裁判会先「思考」再输出；默认 3000 偏小，实测 `deepseek-flash` 需要 8000，否则返回空内容 |

模板见 `env.example`；真实值写在本地 `.env`（不提交）。

## 运行快照（run manifest）

每次运行都会写一份版本快照，保证**任意一个分数都能追溯到当时的模型版本、提示词版本、数据集版本与参数**：

```json
{
  "run_id": "20261017-2130_doubao_v1",
  "stage": "run_model",
  "tag": "doubao_v1",
  "model": "doubao-seed-2-1-lite-260915",
  "prompt_version": "v1",
  "dataset": {"name": "evalset_v1.jsonl", "n": 25},
  "params": {"temperature": 0.0, "max_tokens": 800},
  "usage": {"prompt_tokens": 12000, "completion_tokens": 9000},
  "result": {"ok": 25, "failed": 0}
}
```

存放位置：`outputs/runs/{run_id}/manifest.json`。
manifest 只记录 token 用量；如需折算成本，按所用平台的价目表相乘即可（单价随平台调整，因此不写死在仓库里）。

`outputs/` 默认被 `.gitignore` 排除；如果要展示某次运行，可以挑一份提交：

```bash
git add -f outputs/runs/20261017-2130_doubao_v1/manifest.json
```

## 版本化规则

| 对象 | 版本方式 |
| --- | --- |
| System Prompt | `prompts/system_prompt_v1.md`、`v2` …，每次改动追加，不覆盖旧版本 |
| 改动记录 | `prompts/prompt_changelog.md`：改了什么 / 为什么 / 分数怎么变 / 是否保留 |
| 数据集 | `data/evalset_v1.jsonl` → `evalset_v2.jsonl`，v2 增加短板场景用例 |
| 运行 | `--tag`，如 `doubao_v1`（模型 + SP 版本），所有产物文件名都带 tag |
| 数据集修订 | 任何改动都要登记到 `data/README.md` 的「修订记录」；若改动可能影响分数，必须在同一版本上重跑基线后再做对比 |

**跨版本比较的铁律**：不同评测集版本的分数不能直接比。换数据集就要重跑基线，并在对比表里注明所用版本；否则「通过率从 16% 涨到 40%」可能只是题目变简单了。

## 门禁用法

```bash
python3 scripts/03_report.py --tag doubao_v1 --min-pass-rate 0.8 --max-violations 0
```

不达标时输出 `❌ 门禁未通过` 并以非零退出码结束。`run_all.sh` 用了 `set -e`，所以一条命令就能演示「评测卡住上线」这个动作：

```bash
bash run_all.sh doubao_v1 v1 && echo "可以上线" || echo "被评测卡住了"
```

## 人工回流闭环

1. 每轮评测后从 `outputs/judged_*.jsonl` 按固定随机种子抽 10 条（可复现），由有医学背景的人核对裁判的分级、违规认定与总分是否合理，结论记入 `reports/review_sample_v{轮次}.csv` 并随仓库公开；首轮抽样见 `reports/review_sample_v1.csv`；
2. 裁判判错的，先修 `prompts/judge_prompt.md`（裁判本身也要迭代）；
3. 模型答错的，进 `docs/badcase_analysis.md` 做归因；
4. 归因结果反过来变成新用例（`evalset_v2`）——评测集自己会长大。

## 名词对照（讲项目时可以直接用这几种说法）

| 做法 | 业界名词 |
| --- | --- |
| 节点顺序 + 依赖 | DAG / 流水线 |
| 已完成的用例跳过 | 幂等、断点续跑 |
| 单条失败不阻塞全量 | 错误隔离、重试 |
| 不达标返回非零退出码 | 质量门禁（quality gate） |
| 人工抽检 | 人工在环（human-in-the-loop） |
| badcase 变新用例 | 数据回流 / 数据飞轮 |
