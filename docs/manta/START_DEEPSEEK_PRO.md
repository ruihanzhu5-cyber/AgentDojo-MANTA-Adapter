# DeepSeek Pro：相同 160 条冻结任务

准备日期：2026-10-28。用户指定累计费用上限 **$100**，由用户本人在终端启动。准备过程中未发送 DeepSeek Pro 生成请求。

## 固定配置

| 项目 | 设置 |
|---|---|
| 请求模型 / 所有模型角色 | deepseek-v4-pro |
| API / credential | https://api.deepseek.com/v1 / 现有 DEEPSEEK_API_KEY |
| 场景 | 直接读取原 DeepSeek Flash manifest，80 场景及 160 job，核对全部 payload hash |
| Benchmark / 攻击 / seed | AgentDojo v1.2.2 / 官方 direct / 42 |
| Agent 初始预算 / 初始上限 / 总上限 | 3 / 5 / 10 |
| Planner / Audit | task_conditioned / heuristic |
| max_turns / repair_budget / max_tool_iterations | 2 / 1 / 8 |
| 请求输出上限 / 超时 | 4096 tokens / 180 秒，沿用历史生效设置 |
| Episode 进程并发 | 8 |
| 思考模式 | enabled，保持供应商默认模式；effort 不覆盖，供应商当前默认 high |
| 费用累计上限 | $100，包含启动连通性请求和失败预留 |
| 新结果目录 | results/v1/formal_80_seed42_deepseek_pro/ |

## 最小适配

- Pro 的预算独立于 Flash 与 GPT-4o，SQLite 固定模型/费率身份，不能复用其他模型账本。
- 保留原 MANTA 工具循环，只在 adapter 中把真实返回的 reasoning_content 回填到仍保留的 assistant turn。缓存按一次 generate 和所在线程隔离，不生成空白推理占位，不改变工具内容、Agent 通信或规划修复。
- 各请求持久化保存 messages、响应模型、完整 usage、错误类型、retry index 和执行状态。400/401/403/404 或模型/usage 校验失败时停止后续队列。
- 真实连通性检查由启动脚本发起；首次成功后保留 receipt，续跑不额外反复探测。其 usage 留在独立 connectivity.json，同时计入正式目录共享预算；不作为正式 episode。

## 费率与运行前估算

2026-10-28 核验的 [DeepSeek 官方价格](https://api-docs.deepseek.com/quick_start/pricing/)：Pro 峰时未缓存输入 **$1.32/M**、输出 **$3.96/M**；预算忽略缓存和低峰折扣。上下文 1M，最大输出 384K。请求仍按历史生效的 4096 输出上限运行。

按历史 Flash 的 22,200,124 输入、3,397,110 输出 tokens 等量推算，峰时核算约 **$42.75671928**。Pro 实际用量、思考长度、修复和重试未知，不能把这一预测填入实验结果或当作账单。保守预留可能使队列早于真实账单上限暂停。

官方 [Thinking Mode 文档](https://api-docs.deepseek.com/guides/thinking_mode/) 要求携带 tools 的后续请求回传完整 reasoning_content；缺失可能产生 400。该字段保留是协议兼容，未修改原 MANTA 核心算法，未通过关闭思考或提高输出额度改变配置。

## 启动

```powershell
Set-Location 'C:\Users\larei\Documents\ChatGPT\manta\gpt4o-replication'
& .\scripts\manta\start_deepseek_pro_formal.ps1
```

脚本依次完成：冻结场景核对（零 API）→ 1 次真实 Pro 连通性请求（计入 $100）→ 160 条正式运行。任一前置步骤失败即停止。用户的 API key 已从已有本地配置私下复用，未写入本文件或 Git。

准备检查仅包括 3 个针对性零 API 检查：Pro 与 Flash 价格/账本隔离、真实 reasoning 元数据回填、错误模型/usage 拒绝；另核对原冻结场景。尚未宣称通过真实 Pro API 验证或完成任何 Pro episode。
