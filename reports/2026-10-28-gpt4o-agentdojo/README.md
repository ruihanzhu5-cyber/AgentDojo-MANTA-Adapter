# MANTA × AgentDojo：GPT-4o 跨模型复现

**状态：80 个原始冻结场景，160/160 条正式 episode 有效评分。** AgentDojo v1.2.2，官方 direct，seed 42，原 MANTA 编排。

| 模型 | Clean Utility | Attack Utility | Targeted ASR | 确认暴露 | 观测 tokens |
|---|---:|---:|---:|---:|---:|
| DeepSeek | 65/80（81.25%） | 66/80（82.50%） | 1/80（1.25%） | 74/80 | 25,597,234 |
| GPT-4o | 43/80（53.75%） | 44/80（55.00%） | 1/80（1.25%） | 61/80 | 10,450,803 |

**[完整正式实验报告](GPT4O_EXPERIMENT_REPORT.md)** · **[三个配对轨迹案例](CASE_STUDIES.md)**

本轮 GPT-4o 的任务完成率更低，观测 tokens 减少 59.17%；两个模型唯一攻击成功场景均为 slack_07__attack。相同 ASR 和更少的确认暴露不能说明安全性提高。

## 结构化结果

- [场景级模型对照：160 行](model_comparison.csv)
- [GPT-4o 正式结果：160 行](episode_results.csv)、[全部 182 个尝试目录](attempt_results.csv)
- [四个 Suite 对照](suite_comparison.csv)、[按条件资源统计](resource_metrics.csv)、[完整对照汇总](comparison_summary.json)
- [案例结构化证据](case_studies_evidence.json)
- [冻结清单](manifest.json)、[原始汇总](summary.json)、[代码来源与响应模型](source_provenance.json)
- [评分/usage/账本核对](audit_checks.json)、[预算账本导出](budget_ledger.json)

## 日志与核验

- **[全部 933 个留存文件的脱敏日志包](logs/README.md)**（21.79 MiB）
- [逐文件原始与公开哈希](published_log_inventory.csv)、[脱敏说明](redaction_summary.json)、[发布校验值](checksums.sha256)
- 本地原始日志位于 results/v1/formal_80_seed42_gpt4o/；Pilot、预检和中断记录独立保留。GitHub 不发布 .env。

## 阶段记录与实现

- [环境和兼容性预检](GPT4O_PREFLIGHT.md)
- [适配实现、检查和人工启动交接](GPT4O_IMPLEMENTATION.md)
- [4/8 后由用户停止的 Pilot](GPT4O_PILOT_REPORT.md)
- [新适配层文档](../../docs/manta/GPT4O_ADAPTER.md)、[整个仓库架构](../../docs/REPOSITORY_ARCHITECTURE.md)

正式执行提交 dfc3f27703129614dfabba748ecdc00269f6ca18；所有有效结果执行源码摘要一致。公开报告提交的 SHA 见 Git 历史。

## 适用范围

单 seed、单攻击算法，按 80 场景计权，其中 Banking 有重复用户任务。失败、中断和 mock 不进入正式分母。Pilot 未完成四个 Suite 的全量验收，由用户决定继续正式运行；相关记录保留。实际供应商账单 UNKNOWN；预算报告是 usage 费率计算与未返回请求的保守预留。
