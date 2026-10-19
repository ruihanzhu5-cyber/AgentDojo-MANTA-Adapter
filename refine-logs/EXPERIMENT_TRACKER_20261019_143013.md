# 实验执行清单

日期：2026-10-19。第二阶段实现完成，通过 41 项零付费回归；尚未采集真实 checkpoint。

| Run ID | 内容 | 状态 | 证据/范围 |
|---|---|---|---|
| CTX-000 | 160 条 context 来源统一导出 | PARTIAL | 不阻碍当前局部机制分析；仍没有新的统一全量来源表 |
| CTX-001 | 局部重放执行器 | PASSED | 第一阶段验收完成 |
| CTX-010/011 | 24 次局部 worker 重放 | COMPLETE | 24/24 有效，25 次尝试全部保留；计数 0/6、0/6、1/6、5/6 |
| CTX-002 | 当前原生轮次边界的完整状态保存/恢复 | PASSED_ENGINEERING | 原图恢复与不中断运行完整 metadata 相同；结构化环境与引用测试通过；待真实采集 |
| CTX-020A | 固定 12 候选采集 | READY，未启动 | commit_once 新配置；实际暴露且尚未达到目标的 repair 后状态才合格 |
| CTX-020B | 同状态 G0/G1 原生图续跑 | READY，等待采集 | 最多 6 状态 × 2 条件 × 3 重复；实际合格状态数决定最终规模 |

独立目录：results/v1/graph_checkpoint_commit_once；4 并发；建议启动命令显式设置 5 美元保守记账上限。
计划修订发生在付费采集前：本轮仅覆盖 runtime-evolved checkpoints，未再声称 3 有 mutation + 3 无 mutation。

说明：docs/manta/GRAPH_CHECKPOINT_EXPERIMENT.md。
自查：docs/manta/GRAPH_CHECKPOINT_REVIEW.md。
