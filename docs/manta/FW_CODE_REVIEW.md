# F/W 实现独立代码审查

2026-10-29。依据 experiment-bridge 实现流程进行独立只读审查。
审查者未修改代码、运行脚本、调用模型 API 或启动实验。

## 执行后端

审查确认 F 默认提示与控制路径保留，仅增加记录字段；W 的一次主 Agent 分工请求被计入预算，
随后运行两个真实只读上下文。第二个 worker 不接收第一个报告；主循环收到两份报告后继续。
未发现新攻击目标/ground-truth 泄露或伪造 assistant/tool 调用历史。

## 已修问题

| 问题 | 修正 |
| --- | --- |
| 续跑只匹配场景，没有真实源码凭证 | child 执行前后 fingerprint；父进程前后校验；实际 adapter/MANTA digest 与完整配置匹配 |
| future 异常后仍继续付费队列 | worker 异常立即 stop；协调器 cancel、终止自有 children、保存错误与汇总 |
| probe 费用没有与数据库核对 | manifest 绑定新 ledger；已有 probe request 必须存在；完成收据按 usage 对账到 settled SQL 条目 |
| 两个启动器可能并发探测 | probe 移入同一个持有队列锁的 run_fw 进程 |
| 配置可声明其他文件而后端仍读固定文件 | 固定 canonical 配置路径，校验完整公共限额与生成设置 |
| 汇总遗漏失败 attempt 的使用量 | 单独统计全 attempt journal、失败/缺失、账面预留，与有效结果评分分开 |
| 中断可能留下截断 child JSON，阻塞恢复 | child 原子写入；残缺文件保留计入 malformed，不伪装有效，可新增 attempt |

复核确认前六项有实质修正；最终指出的 child JSON 中断边界也已修正，并加入专项本地检查。
队列和调度单元检查通过状态见 offline verification receipt。审查和离线检查不证明实验效果。
