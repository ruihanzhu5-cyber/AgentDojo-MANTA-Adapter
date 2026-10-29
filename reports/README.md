# 正式实验结果入口

**[最新统一汇总（2026-10-29）](2026-10-29-completed-experiments/README.md)** 收录 6 种有效正式配置；F 的首次完整运行作为重复参考。共 7 次完整运行、1,120 条有效结果，同一批 80 场景、76 个不同用户任务。
只把完整正式配置放在比较主表，诊断和未完成跑次不进入排名。

| 正式配置 | 有效记录 | 报告与结果 |
|---|---:|---|
| Flash 4K / Star | 160 | [原始报告](2026-10-19-manta-agentdojo/README.md) |
| GPT-4o 4K / Star | 160 | [原始报告](2026-10-28-gpt4o-agentdojo/README.md) |
| Pro 16K / Star | 160 | [原始报告](2026-10-28-deepseek-pro-16k/README.md) |
| Flash 16K / 原自适应 | 160 | [原始报告](2026-10-28-deepseek-flash-adaptive/README.md) |
| Flash 16K / F 按需调查 | 160 | [正式报告与日志](2026-10-29-agentdojo-flash16k-fw/README.md)、[F/W 配对](2026-10-29-completed-experiments/fw_paired.csv) |
| Flash 16K / W 固定双调查者 | 160 | [正式报告与日志](2026-10-29-agentdojo-flash16k-fw/README.md)、[F/W 配对](2026-10-29-completed-experiments/fw_paired.csv) |

[F 首次运行的正式脱敏日志](2026-10-29-agentdojo-flash16k-folded/README.md) 另有 160 条有效结果，作为重复参考保留在 [总表](2026-10-29-completed-experiments/overview.csv) 的 `repeat_reference` 行；不当成另一种方法。

- [逐场景指标：1,120 行](2026-10-29-completed-experiments/episode_results.csv)
- [分 suite 结果](2026-10-29-completed-experiments/by_suite.csv)、[角色模块用量](2026-10-29-completed-experiments/role_usage.csv)
- [统一原始日志位置索引](2026-10-29-completed-experiments/log_locations.csv)、[原始结果与官方评分日志哈希](2026-10-29-completed-experiments/source_inventory.json)
- [全部公开脱敏包](LOGS.md)：2026-10-29 新增 F 首轮及 F/W 的 480 条有效正式日志；原始文件仍在 D 盘。

旧报告和发布校验值保持原样；[旧四组联合分析](2026-10-28-four-experiment-analysis/README.md) 可作历史参考。正式结果只选冻结 manifest 中唯一有效、非 mock 的结果，基础设施失败不混入任务分母。`security=True` 表示攻击者目标达成；暴露 UNKNOWN 不等于未暴露。
