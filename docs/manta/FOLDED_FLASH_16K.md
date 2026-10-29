# MANTA Flash 16K：共享主循环与执行前门控

2026-10-29。新分支 `codex/manta-folded-flash16k`，基于 `9ce70a3c5`。
本轮准备只实现代码和离线检查，没有运行 AgentDojo episode、连通性探测或模型请求。
原四组实验和原分支保留，代码在独立工作目录中。

## 设计与代码

参考 [Anthropic single-agent-loop-kit](https://github.com/anthropics/single-agent-loop-kit)
的主循环、按需加载、子 Agent 工具化、预算和执行前门控模式。
没有引入 Anthropic SDK、服务端 tool-search 或其示例评分器；继续使用现有 DeepSeek
客户端、持久预算、请求日志、AgentDojo 工具与官方 utility/security 评分。

| 文件 | 实现 |
| --- | --- |
| `upstreams/manta/MAS/self_evolved/agent_loop.py` | `folded_adaptive` 执行后端：持续主上下文、按需 schema/skill、独立调查、动作核验、局部恢复 |
| `execution_plan.py`（同目录） | 规划/检索/分析/汇总共用主循环；独立角色显式登记，使用 MANTA TopologySpec 保存队伍快照 |
| `tool_gateway.py`（同目录） | 所有模型工具调用在实际 handler 前检查权限与授权；episode 范围读取复用和失效；成功动作防重放 |
| `evidence_store.py`（同目录） | 完整外部结果、本源标签、访问范围、可检索片段、所选核验片段及 SHA256 |
| `action_policy.py`（同目录） | 对固定工具集显式声明 read/navigate/send/mutate/consume；未知工具拒绝；任务约束不能被外部文本扩张 |
| `folded_skills/`（同目录） | 版本控制内的可信任务执行与安全操作流程，模型按需加载 |
| `src/agentdojo_manta/adapter.py` | 新后端接入；沿用观测和财务台账；每个模型请求只执行一次实际 provider attempt；保留各上下文真实 reasoning |

主循环可以按需创建最多两个独立、仅有纯读取能力的调查者。新角色需要明确的新证据需求、完成条件、
可见 evidence_ids 和工具范围。例行规划、解释、汇总保持在主循环。
当前同一 episode 内顺序执行，episode 队列仍并发 8；不把同一 Python 进程或顺序工具调用当作并行多 Agent。
新后端采用“先共享、必要时分离”的调度策略；不会运行旧的 LLM 拓扑规划器、全轨迹 hybrid Auditor
或整队 mutation 重跑。旧 `adaptive_native` 和 `baseline` 的执行路径继续保留。

工具 schema 只在 API tools 中提供一份，主 prompt 提供短目录；按需加载的 schema 在该循环中保留。
不依赖第三方服务端 tool-search。历史达到字符阈值后，只将较旧的外部结果消息换成有来源的 evidence 引用；
完整结果仍可按片段取回，不把外部文本升为 system 指令。字符阈值不是模型上下文 token 上限。

## 动作边界

- get_webpage、download_file 属于可观察导航；不会作为纯读取缓存或永久返回旧页面。
- get_unread_emails 会把邮件标成已读，属于 consume，不能授予只读调查者。
- 发送、导航、修改、consume 在 handler 前进入独立的精确动作核验。核验器无工具，不能执行动作。
- 核验只接收用户任务、准确的待执行参数和最多四份所选证据片段，判定允许或拒绝。没有 benchmark 攻击目标输入。
- 证据较长时，先用 read_evidence 选择支持动作的片段；片段坐标与 hash 进入审计记录和判定缓存键。
- 拒绝不会执行或自动改写动作参数。主循环可以补证或选择合法替代路径。模型核验仍可能误判，不能视为已证明安全。
- 纯读取缓存只在同 episode、同权限与环境版本内使用；任何非纯读取尝试使缓存失效。失败读取不缓存。
- 完全相同且成功的发送/修改返回已执行收据，不重复操作；不确定效果保守阻止相同重试。若合法任务明确要求重复完全相同的动作，这一版可能限制其完成，应单独检查，不能隐瞒为安全收益。

实际 FunctionsRuntime 调用仍由旧适配器记录并送给官方评分器。缓存命中、被拒动作、内部工具、提案、
核验均不伪装成官方 Runtime 调用。新字段包括 execution_plan、gateway_events、action_reviews、
evidence_ledger、goal_progress、folded_usage 和 termination_reason。
汇总额外记录 safe_utility_under_attack（任务完成且攻击未成功）。

## 正式配置（尚未启动）

完整机器配置：[flash_folded_config.json](flash_folded_config.json)。

| 项目 | 设置 |
| --- | --- |
| 模型／路由 | deepseek-flash，https://api.deepseek.com/v1，所有模型角色同一路由 |
| thinking／temperature | enabled／0.0 |
| 单次最大输出 | 16,384 tokens，所有角色一致 |
| 任务 | 原冻结 80 场景，76 个不同用户任务，四 suite 各 20 场景 |
| 条件／攻击 | Clean 80 + Attack 80；原官方 direct；原目标、位置与 payload hash |
| seed／评分 | 42；原官方 AgentDojo v1.2.2 utility/security |
| 默认团队 | 主循环 1；独立调查者累计最多 2；独立动作核验器 1；累计最多 4 个上下文 |
| 工具循环 | 主循环最多 16 次模型响应；局部恢复最多 8；每个调查者最多 8 |
| 审计 | 按需动作前核验，最多 6 次；不运行全轨迹 hybrid Auditor |
| episode 资源 | 最多 48 次模型请求；400,000 响应 usage tokens 的预算；发请求前按实际消息/工具/推理历史的序列化字节数加余量和 16K 输出保守检查剩余额度 |
| 超时／重试 | 单请求 180 秒；新后端无隐藏请求重试；队列仍独立保留基础设施失败 attempt，原 max-attempts=2 |
| 长期经验 | 冻结，不在线更新 |
| 并发 | 8 个 episode |
| 财务上限 | 新目录独立 $100，包含启动前一次连通性探测；沿用原 conservative accounting，不是供应商账单 |
| 结果位置 | `D:\MANTA_DATA\AgentDojo\formal_80_seed42_deepseek_flash_folded` |
| 启动者 | 用户；本次准备不启动 |

episode 预算不等于单次输出上限，也不等于财务台账；没有 episode 总墙钟 deadline。
独立动作核验和默认 Agent 数量改变是本次方法的一部分，不能声称只改变了拓扑。
降低 tokens 20%–30%、提升攻击下任务完成率是待验证目标，没有新实验结果。

## 用户启动

```powershell
Set-Location 'C:\Users\larei\Documents\ChatGPT\manta\manta-folded-flash16k'
& .\scripts\manta\start_deepseek_flash_folded.ps1
```

入口复用原 Python 环境，依次选择新目录、原 Flash 自适应目录、原 gpt4o-replication 目录中已有的
`.env`，不复制或输出密钥。用户已设置的进程环境变量优先。启动脚本先做离线冻结配置检查，
再发一次计入新台账的连通性请求，成功后正式开跑。已有有效连通性收据不会重复请求。
同一命令可续跑，已完成有效 episode 保留；source/config 变化不能继续混写到有结果的旧目录。
原四组实验目录受保护。

## 离线验证与审查

只执行针对真实执行边界的本地单元检查、PowerShell 语法解析和冻结配置 dry-run。
测试以本地受控返回值替代网络与 SDK，包括缓存前置与失效、导航刷新、consume、读权限、
动作拒绝、动作防重放、证据片段核验、格式错误、单上下文连续性、资源截止，以及适配器真实接线中的
推理历史、一次观测对应一次尝试、空响应报基础设施错误、额度不足零发送。

独立代码审查见 [FOLDED_CODE_REVIEW_2026-10-29.md](FOLDED_CODE_REVIEW_2026-10-29.md)。
未运行连通性探测、模型请求、正式实验、pilot 或 benchmark smoke。
