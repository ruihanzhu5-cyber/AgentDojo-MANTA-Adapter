# MANTA × AgentDojo：实验报告与全部留存日志

状态：**80 个场景，160/160 条正式 episode 有效评分**。AgentDojo v1.2.2，官方 direct 攻击，seed 42。

## 正式结果

| Clean 完成 | Attack 下任务完成 | 攻击目标达成 | 确认暴露 |
|---:|---:|---:|---:|
| 65/80（81.25%） | 66/80（82.50%） | 1/80（1.25%） | 74/80（92.50%），另 6 条 UNKNOWN |

**[阅读完整实验报告](EXPERIMENT_REPORT.md)**

## 数据入口

- [160 条正式 episode CSV](episode_results.csv)
- [168 次正式 attempt CSV，含预算中断旧尝试](attempt_results.csv)
- [E2 MANTA 结果表及 suite 细分](table_e2_agentdojo.csv)
- [冻结清单](manifest.json)、[汇总](summary.json)、[资源统计](resource_metrics.csv)
- [机械一致性检查](audit_checks.json)、[源码来源](source_provenance.json)
- [全部留存日志的脱敏压缩包](logs/)
- [逐文件目录和原始/公开校验值](published_log_inventory.csv)
- [脱敏说明和压缩包大小](redaction_summary.json)、[发布文件校验值](checksums.sha256)

归档含正式运行、pilot/mock、预检及失败尝试。正式结果只使用冻结清单中 160 个 job 的唯一有效 attempt；其他日志不进入正式分母。原始敏感日志仅保留本地。

## 全部留存日志压缩包

| 压缩包 | 文件数 | 大小 |
|---|---:|---:|
| [formal_80_seed42.tar.gz](logs/formal_80_seed42.tar.gz) | 679 | 27.79 MiB |
| [formal_launcher_smoke_20261018.tar.gz](logs/formal_launcher_smoke_20261018.tar.gz) | 37 | 0.45 MiB |
| [formal_resume_smoke_20261018.tar.gz](logs/formal_resume_smoke_20261018.tar.gz) | 13 | 0.10 MiB |
| [metric_audit.tar.gz](logs/metric_audit.tar.gz) | 10 | 0.06 MiB |
| [paired_pilot.tar.gz](logs/paired_pilot.tar.gz) | 54 | 0.60 MiB |
| [root_files.tar.gz](logs/root_files.tar.gz) | 1 | 0.00 MiB |

合计 794 个留存文件；原始数据 245972909 字节。原始副本保留本地，公开包为脱敏副本。
