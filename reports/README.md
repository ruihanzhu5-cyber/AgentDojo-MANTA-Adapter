# 实验报告与日志总入口

本目录统一收纳可公开的实验报告、配置、结构化指标和脱敏日志包。原始证据保留在各轮本地结果目录，Flash 自适应轮位于 D 盘，其余历史运行位于各自工作区的 `results/v1/`；旧报告及其发布哈希保持原样。

| 实验 | 范围与状态 | 报告 | 日志 |
|---|---|---|---|
| 2026-10-19 MANTA × AgentDojo / DeepSeek | 80 场景，160/160 有效配对 episode | [报告入口](2026-10-19-manta-agentdojo/README.md) | [历史脱敏包](2026-10-19-manta-agentdojo/logs/) |
| 2026-10-19 Context / Native Graph 机制实验 | 24 有效局部重放；12 个 capture 候选中 1 个合格状态，6 有效续跑 | [报告入口](2026-10-19-context-mechanisms/README.md) | [历史脱敏包](2026-10-19-context-mechanisms/logs/) |
| 2026-10-28 MANTA × AgentDojo / GPT-4o | 原始相同 80 场景，160/160 有效配对 episode | [报告、配对表与案例](2026-10-28-gpt4o-agentdojo/README.md) | [本轮脱敏包](2026-10-28-gpt4o-agentdojo/logs/README.md) |
| 2026-10-28 MANTA × AgentDojo / DeepSeek Pro 16K | 原始相同 80 场景，160/160 有效；输出上限 16384 | [报告与三模型比较](2026-10-28-deepseek-pro-16k/README.md) | [本轮脱敏包](2026-10-28-deepseek-pro-16k/logs/README.md) |
| 2026-10-28 MANTA × AgentDojo / Flash 自适应 16K | 原始相同 80 场景，160/160 有效；真实执行图与 50 次修复 | [报告与四组比较](2026-10-28-deepseek-flash-adaptive/README.md) | [本轮脱敏包](2026-10-28-deepseek-flash-adaptive/logs/README.md) |
| 2026-10-28 四组联合分析（未新增实验） | 四种配置、640 条有效记录；共同资源与安全机制 | [统一分析与证据边界](2026-10-28-four-experiment-analysis/README.md) | [640 条特征](2026-10-28-four-experiment-analysis/episode_features.csv)、各轮原日志入口见报告 |

**[全部公开日志压缩包索引](LOGS.md)** · [仓库架构](../docs/REPOSITORY_ARCHITECTURE.md) · [新适配层](../docs/manta/GPT4O_ADAPTER.md)

读取结果时按每轮冻结 manifest 匹配场景。失败、中断、mock 和 Pilot 是保留证据的一部分，但不进入正式有效评分分母。`security=True` 表示攻击者目标达成；暴露 UNKNOWN 不能解释为未暴露。
