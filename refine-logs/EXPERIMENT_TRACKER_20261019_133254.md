# 实验执行清单

日期：2026-10-19。第一阶段代码与零 API 验收完成；真实模型运行等待用户在终端启动。

| Run ID | 里程碑 | 目的 | 规模 | 状态 | 证据/限制 |
|---|---|---|---:|---|---|
| CTX-000 | M0 | 160 条 context 来源统一导出 | 0 API | PARTIAL | 已有 bad case 和 17 mutation 的只读核查；尚未新增统一全量来源表 |
| CTX-001 | M0 | 两个 worker 局部重放夹具与执行器 | 0 API | PASSED | 9 项新增无网络测试、3 预算与 12 指标回归通过；命令行 preflight 通过 |
| CTX-002 | M0 | 完整 checkpoint 与原生图干预 | 0 API | NOT_IMPLEMENTED | 不属于当前 24 次重放入口，不能宣称完整状态恢复 |
| CTX-010 | M1a | 两 worker × 四条件，第一次重复 | 8 局部续跑 | READY，未启动 | 输出 results/v1/context_replay_slack07_MxT；4 并发、独立保守预算上限 3 美元 |
| CTX-011 | M1b | 完成第二、三次重复 | 16 局部续跑 | WAITING | 首轮工程有效后自动继续，不根据攻击结果筛选 |
| CTX-020 | M2 | 严格 Graph-only 探索 | 36 续跑 | 未排期 | 依赖 CTX-002 和合格状态清单，不在本次启动命令中 |

源码、工具前缀、输入和差异保存在冻结 manifest/fixtures；旧正式实验运行器指纹验证未变。
参阅 docs/manta/CONTEXT_REPLAY.md 与 docs/manta/CONTEXT_REPLAY_REVIEW.md。
