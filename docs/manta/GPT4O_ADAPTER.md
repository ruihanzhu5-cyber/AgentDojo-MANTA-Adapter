# GPT-4o 适配层与复现入口

实现位于 `src/agentdojo_manta/`；正式结果见 [GPT-4o 实验报告](../../reports/2026-10-28-gpt4o-agentdojo/GPT4O_EXPERIMENT_REPORT.md)。

## 新增和修改的接口

| 组件 | 行为与实际调用位置 |
|---|---|
| `providers.provider_config()` | `adapter._make_llm_client()` 和 pipeline 初始化调用。明确选择 provider、endpoint、credential、所有角色的模型；GPT-4o 请求名固定 `gpt-4o` |
| `providers.gpt4o_sampling()` | 绑定到已有 MANTA 客户端采样入口；保留 baseline 生效的 `max_tokens=4096`，避免继承 OpenRouter 环境覆盖 |
| `providers.validate_gpt4o_response()` | 每次实际 HTTP 返回后校验响应模型和完整 usage；不允许换成其他模型后继续统计 |
| `budget.GPT4oBudget` | 继承 SQLite 共享预留机制，独立使用 GPT-4o 输入/输出费率；provider、费率和证据哈希固定到账本 |
| `adapter._make_llm_client()` | 保留原工具循环，关闭 SDK 隐式重试和 OpenRouter 路由扩展；每次 MANTA 重试分别观测和预算预留 |
| `replication.load_replication_plan()` | 正式启动前读取历史 manifest，逐一检查 80 场景、160 job、task/injection ID 和官方 direct payload hash |
| `replication.check_pilot()` | 检查 8 条 Pilot 的有效评分、usage、交接、拓扑及账本；本轮用户在 4 条后停止，并明确选择跳过剩余验收 |
| `run_formal.py` | 沿用独立 episode 进程和恢复逻辑，增加 GPT-4o provider、独立输出、预算与 Pilot gate |

`MANTA_PROVIDER` 为 `deepseek` 时保留原 DeepSeek 路由与费率；`openai` 对应官方 endpoint；本轮实际使用 `qdd` 和已配置的 GPT-4o 连接。`OPENAI_API_KEY` 从未使用 DeepSeek 变量承载。实际 endpoint 和模型响应 ID 保存在 provenance 与日志中。

## 不变的执行设置

| 设置 | 值 |
|---|---|
| 四个 Suite | Banking / Slack / Travel / Workspace，各 20 场景 |
| 条件、攻击、seed | Clean + 官方 direct；42 |
| Initial / Max Initial / Max Total Agents | 3 / 5 / 10 |
| Planner / Audit | task_conditioned / heuristic |
| max_turns / repair_budget / max_tool_iterations | 2 / 1 / 8 |
| 单请求输出上限 / 请求超时 | 4096 tokens / 180 秒 |
| Episode 进程并发 | 8 |
| 工具协议 | `parallel_tool_calls=False`；官方 runtime 实际执行 |

MANTA 原有 tool-memory/context 整理逻辑保留；未新增为适应 GPT-4o 而进行的上下文截断。当前正式有效请求的最大输入为 13,314 tokens，未接近声明的 128K 窗口。自适应过程中可超过初始 3 Agent，例如增长到 6，但仍受总上限约束。保存的拓扑形态受原生 transactional_star 协议限制。

## 请求记录与费用

每次 HTTP 调用前后写入本次 attempt 的 `requests.jsonl`，包括 request/generation ID、Agent ID/type、retry index、请求模型、实际响应模型、完整 input/output usage、latency、错误类型/HTTP status，以及匹配到的官方 injection key。请求前保存 messages、tool schema、输出上限；成功后保存模型响应。日志可能含 benchmark 模拟凭证，因此仅公开脱敏副本。

调用前按声明的最大输入窗口和请求输出上限在共享 SQLite 中预留，成功后按返回 usage 结算。没有可靠返回的请求保留预留；进程恢复时 pending 变为 uncertain。额度对整个目录累计，重启不会清零。本轮配置输入 $2.50/M、输出 $10/M，忽略缓存优惠；这些数值是基于核验费率的核算上界，实际供应商账单保持 UNKNOWN。

## 本地运行与证据复核

先复制 `.env.example` 为本机忽略的 `.env` 并填入自己的 key；不要将 `.env` 提交到 Git。路由证据由只读脚本生成。下面给出接口入口供复现，不会在打开文档时自动执行：

```powershell
uv sync --locked --no-dev --python 3.12
.\.venv\Scripts\python.exe scripts\manta\check_gpt4o_route.py
.\.venv\Scripts\python.exe scripts\manta\probe_gpt4o.py
.\.venv\Scripts\python.exe scripts\manta\run_formal.py --provider qdd --pilot --parallelism 1
```

正式启动要求显式累计 cap。`start_gpt4o_formal.ps1` 保留本轮用户选择的 $100、8 进程和跳过剩余 Pilot 的记录。已完成结果所在目录再次调用启动器会复用唯一有效结果；需要在**新目录**做独立重复实验，不能清除旧结果后复用旧目录。

离线发布不发送 API 请求：

```powershell
.\.venv\Scripts\python.exe scripts\reporting\publish_gpt4o_results.py `
    --baseline-results D:\AgentDojo-MANTA-Adapter\results\v1
```

该命令读取本地历史 DeepSeek 原始数据和 GPT-4o 完整轨迹，核对官方评分、响应 usage、SQLite 账本与代码摘要，再导出 CSV、案例、脱敏日志包和逐文件哈希。源码与运行的冻结指纹不同会停止，而不是悄悄混合结果。
