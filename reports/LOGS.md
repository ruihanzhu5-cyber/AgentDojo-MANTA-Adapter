# 全部公开实验日志

最新 7 次完整正式运行的原始目录统一见 [log_locations.csv](2026-10-29-completed-experiments/log_locations.csv)，结果比较见 [正式汇总](2026-10-29-completed-experiments/README.md)。最近的 F 首次运行及 F/W 原始日志保留在 D 盘；2026-10-29 正式脱敏包见下表。历史包清单保持原样。

## 2026-10-29 新增正式日志

| 实验日期 | 正式实验 | 有效记录 | 日志与校验 |
|---|---|---:|---|
| 2026-10-29 | Flash 16K Folded 首轮（重复参考） | 160 | [4 个 suite 包、报告与哈希](2026-10-29-agentdojo-flash16k-folded/README.md) |
| 2026-10-29 | Flash 16K F/W 调度对照 | F 160 + W 160 | [8 个分组 suite 包、配对与哈希](2026-10-29-agentdojo-flash16k-fw/README.md) |

每个包包含正式有效 episode 的 `result.json`、`requests.jsonl` 与官方评分轨迹；包括任务失败和资源终止结果。探测、smoke/pilot、重复 console/queue 和无效尝试轨迹不上传；无效尝试用量及共同预算汇总保留披露。全部压缩包按实际实验日期、组别和 suite 命名。

## 历史公开归档

Flash 自适应轮的全部正式日志见 [本轮日志索引](2026-10-28-deepseek-flash-adaptive/logs/README.md)，实际逐轮图与阶段顺序见 [execution_graphs.csv](2026-10-28-deepseek-flash-adaptive/execution_graphs.csv)，原始/脱敏哈希见 [inventory](2026-10-28-deepseek-flash-adaptive/published_log_inventory.csv)。原始文件保留在本机 D 盘。

DeepSeek Pro 16K 的全部正式日志见 [本轮日志索引](2026-10-28-deepseek-pro-16k/logs/README.md)，按 Banking、Slack、Travel、Workspace 和控制记录分包。逐文件原始/脱敏哈希见 [inventory](2026-10-28-deepseek-pro-16k/published_log_inventory.csv)，共享累计预算另见 [ledger](2026-10-28-deepseek-pro-16k/shared_budget_ledger.json)。

公开日志统一通过本索引查找，各轮归档保持独立，避免混入其他实验分母。原始日志仅保留本地；下列均为脱敏副本。

| 实验目录 | 压缩包 | 文件数 | 大小 |
|---|---|---:|---:|
| [2026-10-19-context-mechanisms](2026-10-19-context-mechanisms/README.md) | [context_replay_qa_preflight_01.tar.gz](2026-10-19-context-mechanisms/logs/context_replay_qa_preflight_01.tar.gz) | 1 | 0.00 MiB |
| [2026-10-19-context-mechanisms](2026-10-19-context-mechanisms/README.md) | [context_replay_qa_preflight_02.tar.gz](2026-10-19-context-mechanisms/logs/context_replay_qa_preflight_02.tar.gz) | 4 | 0.01 MiB |
| [2026-10-19-context-mechanisms](2026-10-19-context-mechanisms/README.md) | [context_replay_slack07_MxT.tar.gz](2026-10-19-context-mechanisms/logs/context_replay_slack07_MxT.tar.gz) | 86 | 0.16 MiB |
| [2026-10-19-context-mechanisms](2026-10-19-context-mechanisms/README.md) | [graph_checkpoint_commit_once.tar.gz](2026-10-19-context-mechanisms/logs/graph_checkpoint_commit_once.tar.gz) | 67 | 3.10 MiB |
| [2026-10-19-context-mechanisms](2026-10-19-context-mechanisms/README.md) | [graph_checkpoint_qa_preflight_01.tar.gz](2026-10-19-context-mechanisms/logs/graph_checkpoint_qa_preflight_01.tar.gz) | 2 | 0.00 MiB |
| [2026-10-19-context-mechanisms](2026-10-19-context-mechanisms/README.md) | [qa_root_logs.tar.gz](2026-10-19-context-mechanisms/logs/qa_root_logs.tar.gz) | 6 | 0.01 MiB |
| [2026-10-19-manta-agentdojo](2026-10-19-manta-agentdojo/README.md) | [formal_80_seed42.tar.gz](2026-10-19-manta-agentdojo/logs/formal_80_seed42.tar.gz) | 679 | 27.79 MiB |
| [2026-10-19-manta-agentdojo](2026-10-19-manta-agentdojo/README.md) | [formal_launcher_smoke_20261018.tar.gz](2026-10-19-manta-agentdojo/logs/formal_launcher_smoke_20261018.tar.gz) | 37 | 0.45 MiB |
| [2026-10-19-manta-agentdojo](2026-10-19-manta-agentdojo/README.md) | [formal_resume_smoke_20261018.tar.gz](2026-10-19-manta-agentdojo/logs/formal_resume_smoke_20261018.tar.gz) | 13 | 0.10 MiB |
| [2026-10-19-manta-agentdojo](2026-10-19-manta-agentdojo/README.md) | [metric_audit.tar.gz](2026-10-19-manta-agentdojo/logs/metric_audit.tar.gz) | 10 | 0.06 MiB |
| [2026-10-19-manta-agentdojo](2026-10-19-manta-agentdojo/README.md) | [paired_pilot.tar.gz](2026-10-19-manta-agentdojo/logs/paired_pilot.tar.gz) | 54 | 0.60 MiB |
| [2026-10-19-manta-agentdojo](2026-10-19-manta-agentdojo/README.md) | [root_files.tar.gz](2026-10-19-manta-agentdojo/logs/root_files.tar.gz) | 1 | 0.00 MiB |
| [2026-10-28-gpt4o-agentdojo](2026-10-28-gpt4o-agentdojo/README.md) | [formal-banking.tar.gz](2026-10-28-gpt4o-agentdojo/logs/formal-banking.tar.gz) | 200 | 3.08 MiB |
| [2026-10-28-gpt4o-agentdojo](2026-10-28-gpt4o-agentdojo/README.md) | [formal-control-and-resume.tar.gz](2026-10-28-gpt4o-agentdojo/logs/formal-control-and-resume.tar.gz) | 8 | 0.14 MiB |
| [2026-10-28-gpt4o-agentdojo](2026-10-28-gpt4o-agentdojo/README.md) | [formal-slack.tar.gz](2026-10-28-gpt4o-agentdojo/logs/formal-slack.tar.gz) | 200 | 2.90 MiB |
| [2026-10-28-gpt4o-agentdojo](2026-10-28-gpt4o-agentdojo/README.md) | [formal-travel.tar.gz](2026-10-28-gpt4o-agentdojo/logs/formal-travel.tar.gz) | 288 | 9.67 MiB |
| [2026-10-28-gpt4o-agentdojo](2026-10-28-gpt4o-agentdojo/README.md) | [formal-workspace.tar.gz](2026-10-28-gpt4o-agentdojo/logs/formal-workspace.tar.gz) | 200 | 5.75 MiB |
| [2026-10-28-gpt4o-agentdojo](2026-10-28-gpt4o-agentdojo/README.md) | [pilot.tar.gz](2026-10-28-gpt4o-agentdojo/logs/pilot.tar.gz) | 29 | 0.25 MiB |
| [2026-10-28-gpt4o-agentdojo](2026-10-28-gpt4o-agentdojo/README.md) | [preflight.tar.gz](2026-10-28-gpt4o-agentdojo/logs/preflight.tar.gz) | 8 | 0.00 MiB |

GPT-4o 逐文件位置和校验值见 [本轮日志导航](2026-10-28-gpt4o-agentdojo/logs/README.md)。历史 DeepSeek 和 context/graph 实验的文件清单与 checksums 保持原样。

解包时保留原相对路径；选择有效结果应依据该轮 episode_results.csv 与 manifest，而不是把所有 attempt 合计当成独立任务。
