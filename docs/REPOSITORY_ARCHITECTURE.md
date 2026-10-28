# 仓库架构与阅读路线

本仓库 `AgentDojo-MANTA-Adapter` 把 MANTA 多智能体执行层接入 AgentDojo 官方任务、工具、攻击与评分。复现实验以冻结场景为单位，模型通过独立 provider 配置选择。当前已有 DeepSeek、GPT-4o、DeepSeek Pro 16K 三轮正式结果，以及 context/graph 机制实验。

DeepSeek Pro 相关入口：`src/agentdojo_manta/deepseek_pro.py` 保留 reasoning 工具历史，`budget.py` 提供 Pro 独立价格档案，`scripts/manta/start_deepseek_pro_16k.ps1` 为人工启动入口。16K 运行在独立工作树，预算与此前中断的 4K 批次共用累计 $100 台账；配置说明见 [PRO_16K.md](manta/PRO_16K.md)，结果和脱敏日志见 [本轮报告](../reports/2026-10-28-deepseek-pro-16k/README.md)。

## 目录结构

```text
AgentDojo-MANTA-Adapter/
├── README.md                         项目入口、结果摘要与导航
├── .env.example                      不含凭证的本地配置样例
├── pyproject.toml / uv.lock           Python 包与锁定依赖
├── src/
│   ├── agentdojo/                    官方 AgentDojo 实现
│   │   ├── default_suites/           Banking / Slack / Travel / Workspace 等任务
│   │   ├── task_suite/               创建环境、任务执行、utility/security 评分
│   │   ├── attacks/                  官方攻击注册、direct payload 构造
│   │   ├── agent_pipeline/           官方 pipeline 接口和各类模型组件
│   │   ├── functions_runtime.py      官方工具执行与状态变更
│   │   ├── benchmark.py              官方任务/攻击运行入口
│   │   └── logging.py                官方 TraceLogger
│   └── agentdojo_manta/              本仓库适配层
│       ├── adapter.py                官方 pipeline ↔ MANTA engine 桥接
│       ├── providers.py              DeepSeek / OpenAI / QDD 显式路由
│       ├── budget.py                 SQLite 请求预算、预留与 usage 结算
│       ├── metrics.py                官方评分语义、暴露、交接与资源指标
│       └── replication.py            原清单/哈希核对及 Pilot 验收
├── upstreams/manta/                  固定 MANTA 源码快照及原许可证
│   ├── MAS/llm.py                    模型客户端、工具循环和原有上下文整理
│   ├── MAS/self_evolved/             Planner、审计、自适应拓扑、修复算法
│   └── config/                       冻结 playbook 与 topology skill
├── scripts/
│   ├── manta/                        正式队列、单 episode 与连接验证入口
│   │   ├── run_formal.py             冻结队列、独立子进程、续跑、累计预算
│   │   ├── run_agentdojo_manta.py    单 episode，调用官方 runner 并保存结果
│   │   ├── start_gpt4o_formal.ps1    本轮人工启动配置：8 进程、$100 累计上限
│   │   ├── check_gpt4o_route.py      只读路由、价格和账单元数据取证
│   │   └── probe_gpt4o.py            单次真实 API 连通性取证
│   ├── reporting/                    离线核算、案例、脱敏归档与校验清单
│   ├── run_context_replay.py         历史局部 worker 重放实验
│   └── run_graph_experiment.py       历史图状态采集/续跑实验
├── tests/
│   ├── manta/                        适配层预算、协议、指标和历史机制检查
│   └── ...                           上游 AgentDojo 测试
├── docs/
│   ├── REPOSITORY_ARCHITECTURE.md     本文
│   └── manta/                        适配边界、指标、启动及机制实验说明
├── reports/                          统一的公开实验交付入口
│   ├── README.md                     实验总索引
│   ├── LOGS.md                       全部公开日志包索引
│   ├── 2026-10-19-manta-agentdojo/    DeepSeek 正式结果与脱敏日志
│   ├── 2026-10-19-context-mechanisms/ 历史 context / graph 实验报告与日志
│   ├── 2026-10-28-gpt4o-agentdojo/    GPT-4o 正式结果、配对比较、阶段报告、日志
│   └── 2026-10-28-deepseek-pro-16k/   Pro 16K 结果、三模型比较、脱敏日志与预算台账
├── results/v1/                       本机私有原始证据，Git 忽略
│   ├── formal_80_seed42_gpt4o/       正式运行原始结果和完整 API 请求轨迹
│   ├── pilot_4_seed42_gpt4o/         提前停止的 Pilot，与正式结果隔离
│   └── gpt4o_preflight/              连通性、环境及零成本检查记录
├── refine-logs/                      历史研究计划与进度材料
├── MANIFEST.md                       研究交付与历史阶段索引
├── runs/                            上游/历史运行材料，不进入本轮统计
├── examples/ / notebooks/            上游示例与探索材料
├── util_scripts/                     上游数据表和结果处理辅助脚本
├── LICENSE / CITATION.bib            许可证和上游引用信息
└── .github/ / .devcontainer/          CI 与开发环境配置
```

## 一条正式 episode 的数据流

```text
run_formal.py：原始冻结 manifest → 选择未有效完成的 job
    ↓ 独立子进程、独立目录、共享累计费用账本
run_agentdojo_manta.py：官方创建任务环境与 direct 攻击
    ↓ BasePipelineElement.query
MantaAgentDojoPipeline：任务映射、官方函数 → MANTA 工具 schema/handler
    ↓
SelfEvolvedEngine：规划 Agent → 执行与交接 → heuristic audit → 原生修复/拓扑 mutation
    ├── provider 客户端 → 预算预留 → GPT-4o/DeepSeek API → usage/错误持久化
    └── 工具 handler → 官方 FunctionsRuntime → 独立任务环境的真实状态变更
    ↓
适配层构造官方 assistant/tool messages，并转交 TraceLogger
    ↓
AgentDojo 官方 utility/security → result.json → 唯一有效结果 → 离线汇总
```

## 适配层的职责边界

| 层 | 负责 | 主要文件 |
|---|---|---|
| AgentDojo | 场景、环境、工具、攻击构造与官方判分 | `src/agentdojo/` |
| MANTA | Agent 规划、通信、原生审计、修复和自适应拓扑 | `upstreams/manta/MAS/` |
| Adapter | 两边接口与消息格式衔接、真实工具调用记录、provider 与预算观测 | `src/agentdojo_manta/` |
| 队列 | 隔离进程、冻结配置、失败保留、恢复、目录累计预算 | `scripts/manta/` |
| 报告 | 选取有效结果、核对原始评分、配对分析、脱敏导出 | `scripts/reporting/`、`reports/` |

GPT-4o 适配未重写 MANTA 的核心算法，也未修改官方任务、工具与 judge。模型相关改动和记录字段见 [GPT-4o 适配层说明](manta/GPT4O_ADAPTER.md)。

## 如何阅读实验日志

正式目录下 `attempts/<scene_id>__<condition>/attempt_NNN/` 保存每次尝试；完成且有效的结果才进入主表。单次 API 失败、余额不足和进程中断都作为独立执行证据保留。`logs/<job>/<attempt>/` 是官方 logger；`requests.jsonl` 是 API 请求前后的持久化记录；`result.json` 同时保存官方结果、runtime calls、交接和拓扑元数据。

公开归档统一位于各报告目录的 `logs/`，入口为 [日志总索引](../reports/LOGS.md)。包内使用原始 `results/v1` 相对路径。原始数据的 SHA256 与公开脱敏副本的 SHA256 分别列在 `published_log_inventory.csv`；包和报告文件的校验值列在 `checksums.sha256`。完整原始日志保留在本机，不提交 `.env` 或本机数据库外的凭证配置。
