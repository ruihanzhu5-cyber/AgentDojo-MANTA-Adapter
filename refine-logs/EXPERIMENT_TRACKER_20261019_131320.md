# 实验执行清单

日期：2026-10-19。计划已形成，以下均未启动；上一轮只读核查不记为本计划验收完成。

| Run ID | 里程碑 | 目的 | 配置/数据 | 规模 | 主要输出 | 优先级 | 状态 |
|---|---|---|---|---:|---|---|---|
| CTX-000 | M0 | 导出 context 来源与图的对应关系 | 已有 160 有效日志，重点 slack_07 与 17 mutation | 0 API | context_sources、证据路径、UNKNOWN | MUST | TODO |
| CTX-001 | M0 | 验收两个 worker 的局部重放夹具 | 冻结初始 prompt、官方模拟工具、M×T 差异 | 0 API | fixture hash、字段 diff、确定性检查 | MUST | TODO |
| CTX-002 | M0 | 完整恢复及原生图调度能力审计 | context/队列/env/memory/controller/随机状态/去重状态 | 0 API | B2 READY/BLOCKED 及原因 | MUST | TODO |
| CTX-010 | M1a | 第一轮 2×2 | 2 workers × 4 条件 × repeat 1 | 8 局部续跑 | 新增目标调用、正常读取、tokens、错误 | MUST | TODO，依赖 CTX-001 |
| CTX-011 | M1b | 完成预定重复 | 2 workers × 4 条件 × repeats 2/3 | 16 局部续跑 | 同上，按 worker 汇总 | MUST | TODO，依赖工程验收 |
| CTX-020 | M2 | 严格 Graph-only 探索 | 6 合格状态 × 2 图条件 × 3 重复 | 36 续跑 | 成对官方攻击/效用、实际 context 来源 | CONDITIONAL | 尚未排期，依赖 CTX-002 与冻结干预清单 |

M1 合计 24 次 worker 续跑；M2 不包含在立即执行量中。API 金额上限须在运行前写入独立 manifest/预算账本。
