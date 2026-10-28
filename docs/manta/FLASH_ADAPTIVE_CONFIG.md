# DeepSeek Flash：任务内自适应拓扑实验配置

状态：操作者已确认配置，启动脚本已准备；必要离线检查通过，未启动实验、未发送 API 请求。操作者自行在终端启动。此文档不是已完成实验或启动成功的记录。

目标：在原 AgentDojo 配对场景上执行任务驱动的拓扑规划与轨迹驱动修复，保留实际接受的组模式、嵌套子团队、连边及上下文策略，不再让写工具保护路径将它们统一改回 star。合理的 star 可以保留，不强制制造非 star 或 mutation。

人工启动入口：`scripts/manta/start_deepseek_flash_adaptive.ps1`。脚本复用相邻 `gpt4o-replication/.venv` 和本工作树忽略的 `.env`，先核对冻结清单，再在独立台账下验证连通性，最后进入正式队列。再次运行同一入口会复用成功的连通性记录并跳过有效完成的 episode。所有源代码应在正式运行期间保持冻结。

| 项目 | 配置 |
|---|---|
| 模型及所有模型角色 | 官方 `deepseek-flash`；Planner、任务 Agent、LLM Auditor 均相同 |
| 官方路由 | `https://api.deepseek.com/v1`；复用本机已有凭证，不在文档中保存 |
| 当前文档列出的服务版本 | DeepSeek-V4.1-Flash-1017；启动和请求记录仍以真实返回模型为准 |
| 推理模式 | enabled；保留工具对话实际 reasoning_content |
| 输出上限 | 16384 tokens/请求，包含 reasoning |
| 温度 | 0.0 |
| 任务与攻击 | 原冻结 manifest 的 80 场景；四套件各 20；每场景 Clean/direct 各一条，共 160 |
| 判分 | 官方 AgentDojo utility/security；不修改任务、工具效果、攻击 payload 或 judge |
| 随机种子及重复 | seed42，一轮；同一个 job 只选唯一有效结果 |
| 初始团队 | task_conditioned；Planner 在 1–5 个 Agent 内选择；解除非检索工具任务隐含 3 人上限 |
| 团队总上限 | 10 个 Agent |
| 组模式 | singleton/star/chain/debate/voting，支持嵌套子团队 |
| 单任务自适应 | 最多两轮执行、一次修复；每次 mutation 最多三个合法操作 |
| 修复操作 | add_agent、expand_agent_to_group、set_group_pattern、add_edge、remove_edge、set_context_policy |
| 审计 | hybrid：确定性过程检查与有证据约束的 LLM 观察 |
| 写工具行为 | 新的显式实验策略 `adaptive_native`：保留官方工具即时改变模拟环境的语义；不强制 star、不延迟为最终统一提交 |
| 修复门控 | 不因一次成功写操作直接禁用后续审计修复；仍遵守轮数、修复数、停滞和原生停止条件 |
| 工具循环 | 每个 stage 最多 8 次工具循环 |
| 长期经验 | 固定起始 playbook/skill，不在跨任务间在线更新；避免把学习与组织结构变化同时引入 |
| 并发 | 最多 8 条 episode 同时运行；各自独立环境和子进程 |
| 累计预算 | 独立 $100；覆盖连通性、规划、执行、审计及修复；不复用旧 Pro 台账 |
| 预算费率 | 冻结峰时未缓存估算：输入 $0.30/M、输出 $1.20/M；缓存/非峰时折扣忽略；不是实际账单 |
| 启动前连通性 | 用户启动脚本后先做一次同模型、同路由的真实最小请求，计入本轮台账；成功后才进入正式队列 |
| 证据 | 保存 planner 提案、接受后的 TopologySpec、实际逐轮执行图与 stage 顺序、消息可见性、工具结果、官方评分、响应模型与用量 |
| 结果目录 | `results/v1/formal_80_seed42_deepseek_flash_adaptive/`（本独立工作树） |
| 分支 | `codex/deepseek-flash-adaptive`（本地） |

## 与论文及历史实验的边界

这是 MANTA 论文式任务内拓扑自适应在 AgentDojo 上的适配实验，不是原论文全部设置的精确复现。论文使用 Gemma 4、五个能力 benchmark、三次重复，并包含每 12 次运行更新经验库；本轮使用用户指定 Flash、AgentDojo direct 配对攻击、单 seed，并冻结长期经验。

论文没有明确披露与本轮相同的写协议字段设置。`adaptive_native` 是为恢复实际拓扑执行空间而增加的明确代码改动，不冒充作者的已核对原始实验开关；冻结清单和每条结果记录源码哈希。相比旧 Flash，此轮还改变输出上限、初始团队预算和审计模式，不将差异解释为单一因素的因果效果。

离线检查覆盖实际执行器中的 chain → voting 修复、5 人初始预算、即时本地工具效果及写后修复可达性；同时检查 baseline 仍保留 3 人工具任务上限和 transactional_star 行为。测试使用专用本地 harness，不构造模型网络客户端、不进入正式评分目录。

验收以实际执行图为准：提案被拒绝或未执行时，不计为成功拓扑变更。无变化也照实记录，不强制修复、不筛掉 star，不以攻击成败选择图。

参考：[论文配置与修复算子](https://arxiv.org/html/2607.28527#A1.SS2)、[官方模型与价格](https://api-docs.deepseek.com/quick_start/pricing/)。
