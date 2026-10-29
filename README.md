# MANTA × AgentDojo Adapter

将 MANTA SelfEvolvedEngine 接入 AgentDojo 官方任务、工具、direct 攻击和 utility/security 评分。本仓库保留官方 AgentDojo 与固定 MANTA 快照，适配层位于 `src/agentdojo_manta/`。

**[最新正式实验汇总：6 种配置与 F/W 对照](reports/2026-10-29-completed-experiments/README.md)**

每组使用相同 80 个场景（76 个不同用户任务），Clean/Attack 各 80 条；下面只列有比较价值的完整正式配置。

| 已完成正式配置 | Clean Utility | Attack Utility | Targeted ASR ↓ | 有效结果总 token |
|---|---:|---:|---:|---:|
| Flash 4K · Star | 65/80（81.25%） | 66/80（82.50%） | 1/80（1.25%） | 25,597,234 |
| GPT-4o 4K · Star | 43/80（53.75%） | 44/80（55.00%） | 1/80（1.25%） | 10,450,803 |
| Pro 16K · Star | 69/80（86.25%） | 69/80（86.25%） | 4/80（5.00%） | 26,911,684 |
| Flash 16K · 原自适应 | 65/80（81.25%） | 66/80（82.50%） | 1/80（1.25%） | 28,129,280 |
| Flash 16K · F 按需调查 | 72/80（90.00%） | 71/80（88.75%） | 0/80（0%） | 7,137,951 |
| Flash 16K · W 固定双调查者 | 73/80（91.25%） | 75/80（93.75%） | 0/80（0%） | 13,142,142 |

另保留 F 首次完整运行作为重复参考：74/80 clean、68/80 attack、ASR 1/80、7,109,588 token。
合计 7 次完整运行、1,120 条有效记录；重复参考不作为额外方法或多 seed 平均。
W 比 F 多完成 4 个攻击下任务，token 增加 84.12%；相对原 Flash 自适应，F/W 分别节省 74.62%/53.28% token。
结果反映完整配置，历史模型、输出上限、审计与执行协议有差异；不能归因于单个模块或外推到所有攻击。

- **[逐场景结果与配置总表](reports/2026-10-29-completed-experiments/README.md)** · [模块 token](reports/2026-10-29-completed-experiments/role_usage.csv) · [F/W 逐项配对](reports/2026-10-29-completed-experiments/fw_paired.csv)
- **[全部正式报告入口](reports/README.md)** · **[统一原始日志位置](reports/2026-10-29-completed-experiments/log_locations.csv)** · [历史公开脱敏日志](reports/LOGS.md)
- [仓库架构](docs/REPOSITORY_ARCHITECTURE.md) · [适配层](docs/manta/GPT4O_ADAPTER.md)
- [F/W 冻结配置与启动说明](docs/manta/FW_ABLATION.md) · [Folded 冻结配置](docs/manta/FOLDED_FLASH_16K.md)

F 首轮和 F/W 已完成，冻结配置文档保留其准备时原文，实际完成状态以上述结果和汇总报告为准。
原始日志保留各轮原目录；10 月 29 日的正式脱敏包已整理为 [Folded 首轮（重复参考）](reports/2026-10-29-agentdojo-flash16k-folded/README.md) 与 [F/W 调度对照](reports/2026-10-29-agentdojo-flash16k-fw/README.md)，共 480 条有效记录。仅离线归档，没有启动新实验。

运行环境使用 `uv sync --locked --no-dev --python 3.12`。复制 `.env.example` 为 `.env` 后填写自己的凭证；不要上传 `.env`。配置和启动说明见 [适配层文档](docs/manta/GPT4O_ADAPTER.md)。报告导出为离线操作，不发送模型请求。

下方保留上游 AgentDojo 的介绍、安装与引用信息。

---

<center>

# AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents

![GitHub License](https://img.shields.io/github/license/ethz-spylab/agentdojo) ![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/ethz-spylab/agentdojo/lint-docs.yaml)
 ![PyPI - Python Version](https://img.shields.io/pypi/pyversions/agentdojo) ![PyPI - Downloads](https://img.shields.io/pypi/dm/agentdojo) ![PyPI - Version](https://img.shields.io/pypi/v/agentdojo)



[Edoardo Debenedetti](https://edoardo.science)<sup>1</sup>, [Jie Zhang](https://zj-jayzhang.github.io)<sup>1</sup>, [Mislav Balunović](https://www.sri.inf.ethz.ch/people/mislav)<sup>1,2</sup>, [Luca Beurer-Kellner](https://www.sri.inf.ethz.ch/people/luca)<sup>1,2</sup>, [Marc Fischer](https://marcfischer.at)<sup>1,2</sup>, [Florian Tramèr](https://floriantramer.com)<sup>1</sup>

<sup>1</sup>ETH Zurich and <sup>2</sup>Invariant Labs

[Read Paper](https://arxiv.org/abs/2406.13352) | [Inspect Results](https://agentdojo.spylab.ai/results/)
</center>

## Quickstart

```bash
pip install agentdojo
```

## MANTA adapter experiment

This public checkout also contains the V1 MANTA integration used for the
adaptive-topology security experiment. See [`docs/manta/README.md`](docs/manta/README.md)
for the adapter boundary, pinned MANTA snapshot, and one-episode smoke commands.

The completed **MANTA × AgentDojo** experiment (80 scenes, 160 valid paired
episodes, seed 42, official direct attack) is published with the full report,
CSV tables, configuration, checksums and all retained logs in redacted archives:
**[experiment report and logs](reports/2026-10-19-manta-agentdojo/README.md)**.

The follow-up context experiments (24 valid local worker replays and 6 native
graph continuations from 1 eligible checkpoint among 12 capture candidates)
are published separately with reports, configurations, analysis and all retained
redacted logs: **[context mechanism reports and logs](reports/2026-10-19-context-mechanisms/README.md)**.
These are exploratory mechanism studies and do not establish general failure
of graph-based defenses.

> [!IMPORTANT]
> Note that the API of the package is still under development and might change in the future.

If you want to use the prompt injection detector, you need to install the `transformers` extra:

```bash
pip install "agentdojo[transformers]"
```

## Running the benchmark

The benchmark can be run with the [benchmark](src/agentdojo/scripts/benchmark.py) script. Documentation on how to use the script can be obtained with the `--help` flag.

For example, to run the `workspace` suite on the tasks 0 and 1, with `gpt-4o-2024-05-13` as the LLM, the tool filter as a defense, and the attack with tool knowlege, run the following command:

```bash
python -m agentdojo.scripts.benchmark -s workspace -ut user_task_0 \
    -ut user_task_1 --model gpt-4o-2024-05-13 \
    --defense tool_filter --attack tool_knowledge
```

To run the above, but on all suites and tasks, run the following:

```bash
python -m agentdojo.scripts.benchmark --model gpt-4o-2024-05-13 \
    --defense tool_filter --attack tool_knowledge
```

## Inspect the results

To inspect the results, go to the dedicated [results page](https://agentdojo.spylab.ai/results/) of the documentation. AgentDojo results are also listed in the [Invariant Benchmark Registry](https://explorer.invariantlabs.ai/benchmarks/).Agent

## Documentation of the Dojo

Take a look at our [documentation](https://agentdojo.spylab.ai/).

## Development set-up

Take a look at the [development set-up](https://agentdojo.spylab.ai/development/) docs.

## Citing

If you use AgentDojo in your research, please consider citing our paper:

```bibtex
@inproceedings{
 debenedetti2024agentdojo,
 title={AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for {LLM} Agents},
 author={Edoardo Debenedetti and Jie Zhang and Mislav Balunovic and Luca Beurer-Kellner and Marc Fischer and Florian Tram{\`e}r},
 booktitle={The Thirty-eight Conference on Neural Information Processing Systems Datasets and Benchmarks Track},
 year={2024},
 url={https://openreview.net/forum?id=m1YYAQjO3w}
}
```
