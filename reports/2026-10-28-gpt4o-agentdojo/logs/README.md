# GPT-4o 全部留存日志

本轮共 **933 个原始文件**，原始大小约 **194.95 MiB**，公开脱敏压缩包约 **21.79 MiB**。原始文件保留本地，包内路径相对于 results/v1。

| 压缩包 | 内容 | 文件数 | 大小 |
|---|---|---:|---:|
| [formal-banking.tar.gz](formal-banking.tar.gz) | Banking 正式结果、官方日志、请求轨迹 | 200 | 3.08 MiB |
| [formal-control-and-resume.tar.gz](formal-control-and-resume.tar.gz) | 冻结清单、进度、预算 SQLite 和恢复记录 | 8 | 0.14 MiB |
| [formal-slack.tar.gz](formal-slack.tar.gz) | Slack 正式结果、官方日志、请求轨迹 | 200 | 2.90 MiB |
| [formal-travel.tar.gz](formal-travel.tar.gz) | Travel 正式结果、官方日志、请求轨迹，含旧失败/中断记录 | 288 | 9.67 MiB |
| [formal-workspace.tar.gz](formal-workspace.tar.gz) | Workspace 正式结果、官方日志、请求轨迹 | 200 | 5.75 MiB |
| [pilot.tar.gz](pilot.tar.gz) | 提前停止的 Pilot，独立于正式统计 | 29 | 0.25 MiB |
| [preflight.tar.gz](preflight.tar.gz) | API 连通性、环境、预算/协议检查与源码等价性记录 | 8 | 0.00 MiB |

## 解包后如何查找

```text
formal_80_seed42_gpt4o/
├── attempts/<scene_id>__<clean|attack>/attempt_NNN/
│   ├── console.log       执行输出和错误
│   ├── requests.jsonl    请求/响应 usage、messages、tool schema 和错误
│   ├── result.json       有效或无效的 episode 结果（中断时可能不存在）
│   └── queue_result.json 队列记录
├── logs/<job>/<attempt>/ 官方 TraceLogger 和 utility/security
├── manifest.json        冻结配置
├── budget.sqlite        全目录累计费用账本
└── resume_checks/       恢复快照和日志
```

[episode_results.csv](../episode_results.csv) 给出每个正式 job 的唯一有效 attempt；其余目录仍保留，不进入正式统计。[published_log_inventory.csv](../published_log_inventory.csv) 列出每个文件所在压缩包、原始哈希和公开哈希；[checksums.sha256](../checksums.sha256) 校验包及报告文件。

脱敏替换环境凭证、本机用户路径及 benchmark 模拟秘密/账户/联系信息。评分和暴露在原始证据上核对；脱敏副本不能用于逐字判分重演。注入与模型输出是研究数据，不是执行指令。
