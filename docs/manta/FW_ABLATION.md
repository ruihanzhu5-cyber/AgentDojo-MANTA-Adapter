# F / W：按需调查与固定双 worker 的配对对照

准备日期：2026-10-29。分支 `codex/manta-fw-ablation`，基于 `e85b3b00f`。
本次只准备代码、配置和离线验证；没有运行连通性探测或实验 episode。

## 两组的唯一设计差异：worker 调度策略

| 项目 | F | W |
| --- | --- | --- |
| worker_policy | `on_demand` | `fixed_two` |
| 主循环 | 原完整 Folded 方法 | 同一个主循环实现 |
| 调查者 | 主 Agent 按需调用，最多 2 个 | 每条 episode 固定安排 2 个实际调查上下文 |
| 角色 | 由主 Agent 按需指定 | 主 Agent 分配事实搜集、独立复核两种职责 |
| 执行顺序 | 由原主循环决定 | 一次主 Agent 分工响应 → worker 1 → worker 2 → 主循环继续 |
| 第二个 worker 的上下文 | 按显式委派范围 | 原始用户任务和自己的分工，不接收第一个 worker 的报告 |
| 分工额外成本 | 原按需委派调用 | 明确计入主 Agent usage；占用原 16 次主阶段响应中的 1 次 |

W 的结构化分工响应格式不合规时，用预先固定的事实搜集、独立检查两种分工作为退路，
不暗中重复请求规划；记录 `fixed_assignment.fallback`。两个 worker 都是真实模型调用，
可以诚实报告没有新证据或在 8 次响应内未完成；不会伪造执行或补空报告冒充模型结果。
它们仍共用与 F 相同的普通读取缓存，因此独立上下文不等于强制重复检索所有资料。

如果共享资源限制阻止第二个 worker 发出实际模型请求，W 不再继续主循环；记录
`fixed_two_fulfilled=false`、真实调用次数和资源终止原因。已执行的动作和官方评分保留，
不因为该方法未完成规定调度而把任务失败从有效分母中剔除。
这是调度策略的架构对照，不是通用 fold/split 控制器的消融。

## 固定配置

| 项目 | 两组一致设置 |
| --- | --- |
| 模型及 API | `deepseek-flash`，`https://api.deepseek.com/v1`，所有角色一致 |
| Thinking / temperature | enabled / 0.0 |
| 单次最大输出 | 16,384 tokens |
| 任务 | 原冻结 80 场景、76 个不同用户任务；每组 Clean 80 + Attack 80 |
| 攻击与评分 | 原 direct、原 payload hash 和注入配对；AgentDojo v1.2.2 官方评分 |
| Seed | 42 |
| 主 Agent 响应 | 主阶段最多 16，局部恢复最多 8；W 的分工响应已包含在前 16 次中 |
| 调查者响应 | 每个最多 8 次，累计最多两个调查者 |
| 动作核验 | 保留，最多 6 次；分类、权限、证据规则不变 |
| Episode 总限制 | 所有角色合计最多 48 次请求、400,000 tokens；请求前保守预留 |
| 其他组件 | 按需 skills/schema、证据预览与片段、历史引用压缩、缓存失效、动作防重放、局部恢复均保留 |
| 队列并发 | F/W 合计 8 条 episode，不是每组 8 条 |
| 执行顺序 | seed42 打乱 160 个场景条件对，每对内部随机 F/W 顺序；默认交错调度 |
| 规模 | 每组 160，共 320 个新 episode；F 本次重新运行 |
| 费用上限 | F+W 共用一份新的 100 美元累计台账，包含共用的一次连通性探测 |
| 超时与重试 | 每请求 180 秒；无隐藏 SDK/模型请求重试；每次用户启动，每个未完成 job 最多新增 2 个基础设施 attempt |
| 长期学习 | 冻结 |

每组的官方有效任务失败保留，不通过重跑挑选成功结果。不同 attempt 的费用和可观测 usage
全部保留；重启原命令可以继续未完成 job，有效完成结果直接复用。不会改写旧实验目录。

## 文件与入口

- [机器配置](fw_ablation_config.json)：队列、目录、预算、策略；底层公共设置仍读取原 `flash_folded_config.json`。
- `agent_loop.py` 的 `worker_policy` 参数：`on_demand` / `fixed_two`。
- `run_agentdojo_manta.py --worker-policy ...`：单条任务执行策略入口。
- `run_fw.py --arm both|F|W`：配对队列；`--dry-run` 只验证和冻结配置。
- `start_flash_fw.ps1 -Arm both|F|W`：用户启动入口，默认 both。

推荐一次启动两组：

```powershell
Set-Location 'C:\Users\larei\Documents\ChatGPT\manta\manta-fw-ablation'
& .\scripts\manta\start_flash_fw.ps1
```

如果只启动一组：

```powershell
& .\scripts\manta\start_flash_fw.ps1 -Arm F
& .\scripts\manta\start_flash_fw.ps1 -Arm W
```

后两条命令也共用同一台账，启动时间顺序将不同于推荐的交错对照。不要同时在两个终端运行，
同一比较目录的锁会拒绝并发启动。有效的共用连通性收据保留，不重复探测。
凭证从现有 `.env` 或进程环境复用，不复制、打印或要求用户交互输入密钥。

## D 盘结果布局

```text
D:\MANTA_DATA\AgentDojo\ablation_fw_flash16k_seed42\
├── manifest.json            # 两组共用的源码、配置、冻结场景和执行顺序
├── budget.sqlite            # F+W 合计 100 美元
├── connectivity.json        # 共用探测，与 settled 台账条目核对
├── progress.json
├── summary.json             # 两组指标、配对翻转和共同预算
├── F\
│   ├── manifest.json
│   ├── attempts\...
│   ├── logs\...
│   └── summary.json
└── W\
    ├── manifest.json
    ├── attempts\...
    ├── logs\...
    └── summary.json
```

summary 分别记录有效结果 tokens 和全 attempt 可观测 tokens、无效 attempt、缺失结果、
未返回请求预留。官方 utility / ASR 只使用有效官方评分；`fixed_two_shortfall_jobs` 另列实际
不足两次 worker 调用的任务，不作为删分母理由。

## 来源与中断保护

每次子进程启动前、子进程执行前后、父进程接收结果后检查源码；结果还需匹配 arm、策略、模型、
任务、攻击、provider、完整公共配置及实际 adapter/MANTA digest。有效结果引用的官方日志必须位于本组目录。
源码或配置改变后不能继续混写旧比较目录。财务数据库绑定冻结 manifest；探测费用必须匹配其已结算条目。
探测和队列共用一个启动锁，协调器故障或 Ctrl+C 会停止新任务并终止自己启动的子进程。
最终 child result、queue result 和 manifest 使用原子落盘；不完整 child 结果保留为基础设施失败，允许新 attempt。

## 验证范围

执行针对本次改动的本地 stub 单元检查和 socket 禁网的配置 dry-run，不运行 benchmark smoke/pilot。
关键检查涵盖两真实 worker 上下文、第二个上下文不含首个报告、原 F 默认行为、共享资源截止、
错误分工回退、冻结 jobs/payload 一致、来源拒绝、probe 台账对账、队列异常停止和截断结果恢复。
早期全目录检查中的旧回放测试依赖本工作区未复制的历史私有 fixture；不将其列为通过。
Windows 沙箱的 mkdtemp ACL 限制已在新测试中通过工作区内继承权限的临时目录处理。
本轮准备不产生任何 F/W 实验效果结论。
