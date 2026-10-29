# Flash 16K：F/W 按需与固定双 worker 对照

实验日期：**2026-10-29**。归档日期：**2026-10-29**。逐条运行时间范围见 [publication.json](publication.json)，时间按原始日志记录，未擅自转换时区。

只归档有比较价值的正式证据：每组冻结 80 场景，clean 80 + direct attack 80。包含任务失败和资源终止的有效评分；不是只选成功案例。

| 组别 | Clean 完成 | Attack 完成 | 攻击成功 | 安全完成 | 总 token |
|---|---:|---:|---:|---:|---:|
| fw-F-on-demand | 72/80 | 71/80 | 0/80 | 71/80 | 7,137,951 |
| fw-W-fixed-two | 73/80 | 75/80 | 0/80 | 75/80 | 13,142,142 |

F 为按需调查，W 为一次 main 分派后固定两个真实只读 worker；两组共 320 条有效 episode，共享同一版本代码与资源上限。W 的 160 条均实际启动 agent_1 和 agent_2；F 仅 2 条启动一个调查 worker。

W 比 F 多完成 4 个攻击下任务，总 token 多 84.12%。这是包含分派/汇报的调度协议对照，不是通用运行中 fold/split 的纯消融。两组各 76 条确认暴露、4 条 UNKNOWN；0/80 是本次 direct 测试的观测 ASR。

每组保留 163 次尝试，其中 3 次基础设施无效尝试不打包；其观测用量与预留成本仍完整披露在 retained_summary_F/W.json 的 all_attempts。共同账本估算上界 $9.6466629，其中已返回响应上界 $7.6412613、未返回预留 $2.0054016；不是实际账单。

## 日志包

每个包按组别和 suite 命名，包含 40 条 episode 的 result.json、requests.jsonl 与官方评分 trace，共 120 个文件。重复 console/queue、探测、锁文件和测试不上传。

| 包 | Episode | 文件 | MiB |
|---|---:|---:|---:|
| [2026-10-29_agentdojo_flash16k_fw-F-on-demand_banking_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-F-on-demand_banking_valid.tar.gz) | 40 | 120 | 1.03 |
| [2026-10-29_agentdojo_flash16k_fw-F-on-demand_slack_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-F-on-demand_slack_valid.tar.gz) | 40 | 120 | 1.53 |
| [2026-10-29_agentdojo_flash16k_fw-F-on-demand_travel_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-F-on-demand_travel_valid.tar.gz) | 40 | 120 | 1.12 |
| [2026-10-29_agentdojo_flash16k_fw-F-on-demand_workspace_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-F-on-demand_workspace_valid.tar.gz) | 40 | 120 | 2.13 |
| [2026-10-29_agentdojo_flash16k_fw-W-fixed-two_banking_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-W-fixed-two_banking_valid.tar.gz) | 40 | 120 | 2.45 |
| [2026-10-29_agentdojo_flash16k_fw-W-fixed-two_slack_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-W-fixed-two_slack_valid.tar.gz) | 40 | 120 | 3.16 |
| [2026-10-29_agentdojo_flash16k_fw-W-fixed-two_travel_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-W-fixed-two_travel_valid.tar.gz) | 40 | 120 | 2.37 |
| [2026-10-29_agentdojo_flash16k_fw-W-fixed-two_workspace_valid.tar.gz](logs/2026-10-29_agentdojo_flash16k_fw-W-fixed-two_workspace_valid.tar.gz) | 40 | 120 | 3.58 |

## 复核与使用

- [逐条结果](episode_results.csv)、[总表](overview.csv)、[分 suite](by_suite.csv)、[角色 token](role_usage.csv)。
- [逐文件原始/公开哈希](published_log_inventory.csv)、[压缩包清单](archives.json)、[所有文件校验值](checksums.sha256)。
- 原始结果和官方 utility/security 已逐条匹配；token 已逐请求求和，不重新调用模型或评分器。
- 公开副本脱敏凭证、用户路径及合成联系/账户敏感值；原始文件未修改。公开 trace 不是逐字节原始评分输入，不应直接重算评分替代官方结果。
- 总 token 仅包含所选有效 episode 的已完成请求；完整尝试/预算信息另看 retained_summary。
- [全部已完成正式实验汇总](../2026-10-29-completed-experiments/README.md)。
