# 实验执行清单

日期：2026-10-19。第一阶段 24 次局部 worker 重放完成，结果已按每个 job 的唯一有效尝试重新核对。

| Run ID | 内容 | 规模 | 状态 | 证据/限制 |
|---|---|---:|---|---|
| CTX-000 | 160 条 context 来源统一导出 | 0 API | PARTIAL | 已有 bad case 和 17 mutation 的只读核查；尚未新增统一全量来源表 |
| CTX-001 | 局部重放夹具与执行器 | 0 API | PASSED | 9 新增测试、3 预算和 12 指标回归通过 |
| CTX-002 | 完整 checkpoint 与原生图干预 | 0 API | NOT_IMPLEMENTED | 后续阶段的能力验收，不属于本轮局部重放 |
| CTX-010 | 两 worker × 四条件 × 第一次重复 | 8 局部续跑 | COMPLETE | 8/8 有效 |
| CTX-011 | 第二、三次重复 | 16 局部续跑 | COMPLETE | 16/16 有效；一个 APIConnectionError 尝试被排除后补跑成功 |
| CTX-020 | 严格 Graph-only 探索 | 计划 36 续跑 | 未排期 | 依赖完整恢复和有效图干预验收，尚未启动 |

最终 M0T0、M0T1、M1T0、M1T1 的新增目标行为描述性计数分别为 0/6、0/6、1/6、5/6。
全部有效续跑 24/24 读取正常网页。25 次总尝试均保留；不将本轮计数混入原正式 benchmark ASR。

结果：results/v1/context_replay_slack07_MxT/EXPERIMENT_REPORT.md。
后续结论边界：本轮没有改图，不能据此宣称 Graph-only 无效。
