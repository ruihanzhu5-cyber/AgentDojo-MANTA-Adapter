# Research Output Manifest

> Tracks generated research planning artifacts. Existing experiment reports remain in their original publication directory.

2026-10-28 更新：GPT-4o 跨模型复现已完成，报告、160 行配对表、三个轨迹案例和 933 个留存文件的脱敏日志归档见 [交付目录](reports/2026-10-28-gpt4o-agentdojo/README.md)。[全部实验](reports/README.md) / [全部日志](reports/LOGS.md) / [仓库架构](docs/REPOSITORY_ARCHITECTURE.md)。阶段性的 GPT4O_PREFLIGHT / IMPLEMENTATION / PILOT_REPORT 已集中到该交付目录；原始数据保持原位。

| Timestamp | Skill | File | Stage | Description |
|-----------|-------|------|-------|-------------|
| 2026-10-19 13:13:20 +08:00 | /experiment-plan | refine-logs/EXPERIMENT_PLAN_20261019_131320.md | implementation | Context 传播机制分阶段实验计划；未启动 API 运行 |
| 2026-10-19 13:13:20 +08:00 | /experiment-plan | refine-logs/EXPERIMENT_PLAN.md | implementation | latest copy |
| 2026-10-19 13:13:20 +08:00 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER_20261019_131320.md | implementation | 先验收，再做 24 次局部重放，图干预另设门槛 |
| 2026-10-19 13:13:20 +08:00 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER.md | implementation | latest copy |
| 2026-10-19 13:32:54 +08:00 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER_20261019_133254.md | implementation | 第一阶段实现和零 API 验收完成，真实运行尚未启动 |
| 2026-10-19 13:32:54 +08:00 | /experiment-plan | refine-logs/EXPERIMENT_TRACKER.md | implementation | latest copy |
| 2026-10-19 13:32:54 +08:00 | implementation | docs/manta/CONTEXT_REPLAY.md | implementation | 局部重放启动、结果字段和续跑说明 |
| 2026-10-19 13:32:54 +08:00 | self-review | docs/manta/CONTEXT_REPLAY_REVIEW.md | implementation | 自查修正与 24 项测试通过记录；未调用真实模型 |
| 2026-10-19 13:52:36 +08:00 | /analyze-results | results/v1/context_replay_slack07_MxT/EXPERIMENT_REPORT.md | implementation | 本地原始结果报告；24/24 有效，25 尝试，含一次基础设施失败补跑 |
| 2026-10-19 13:52:36 +08:00 | /analyze-results | refine-logs/EXPERIMENT_TRACKER_20261019_135236.md | implementation | 第一阶段完成；Graph-only 阶段尚未实施 |
| 2026-10-19 13:52:36 +08:00 | /analyze-results | refine-logs/EXPERIMENT_TRACKER.md | implementation | latest copy |
| 2026-10-19 14:30:13 +08:00 | implementation | docs/manta/GRAPH_CHECKPOINT_EXPERIMENT.md | implementation | 新 commit_once 图干预配置、状态恢复、最多 12 采集 + 36 续跑协议 |
| 2026-10-19 14:30:13 +08:00 | self-review | docs/manta/GRAPH_CHECKPOINT_REVIEW.md | implementation | 41 项测试与完整原图恢复等价性、结构化环境 alias 验收 |
| 2026-10-19 14:30:13 +08:00 | implementation | refine-logs/EXPERIMENT_TRACKER_20261019_143013.md | implementation | 第二阶段工程验收完成，真实执行未启动 |
| 2026-10-19 14:30:13 +08:00 | implementation | refine-logs/EXPERIMENT_TRACKER.md | implementation | latest copy |
| 2026-10-19 14:50:00 +08:00 | /analyze-results | results/v1/graph_checkpoint_commit_once/EXPERIMENT_REPORT.md | analysis | 12 次采集、1 合格状态、6 有效续跑；两图均 0/3 攻击、3/3 任务成功 |
| 2026-10-19 14:50:00 +08:00 | offline-audit | results/v1/graph_checkpoint_commit_once/analysis_evidence.json | analysis | 原始日志校验、实际图/调度、context packet 命中及预算一致性 |
| 2026-10-19 14:50:00 +08:00 | /analyze-results | refine-logs/EXPERIMENT_TRACKER_20261019_145000.md | analysis | 第二阶段运行完成，记录合格率与结论范围 |
| 2026-10-19 14:50:00 +08:00 | /analyze-results | refine-logs/EXPERIMENT_TRACKER.md | analysis | latest copy |
| 2026-10-19 | publication | reports/2026-10-19-context-mechanisms/README.md | publication | 两轮机制实验报告、配置、综合分析；166 个新增留存文件的脱敏压缩包与校验清单 |
