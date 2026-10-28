# MANTA × AgentDojo Adapter

将 MANTA SelfEvolvedEngine 接入 AgentDojo 官方任务、工具、direct 攻击和 utility/security 评分。本仓库保留官方 AgentDojo 与固定 MANTA 快照，适配层位于 `src/agentdojo_manta/`。

| 已完成正式实验 | Clean Utility | Attack Utility | Targeted ASR | 确认暴露 |
|---|---:|---:|---:|---:|
| DeepSeek：80 场景 / 160 episode | 65/80（81.25%） | 66/80（82.50%） | 1/80（1.25%） | 74/80 |
| GPT-4o：相同场景 / 160 episode | 43/80（53.75%） | 44/80（55.00%） | 1/80（1.25%） | 61/80 |

- **[整个仓库架构](docs/REPOSITORY_ARCHITECTURE.md)** · **[GPT-4o 适配层](docs/manta/GPT4O_ADAPTER.md)**
- **[GPT-4o 正式报告与配对比较](reports/2026-10-28-gpt4o-agentdojo/README.md)** · [160 行模型对照 CSV](reports/2026-10-28-gpt4o-agentdojo/model_comparison.csv)
- **[全部实验报告](reports/README.md)** · **[全部公开日志包](reports/LOGS.md)**

每轮正式统计仅选取冻结 job 的唯一有效结果。API 余额不足、进程中断、Pilot 和 mock 均单独保留，不作为攻击失败。原始日志在本机忽略的 `results/v1/`，GitHub 只发布脱敏包和校验清单。单 seed、重复 Banking 任务与有限攻击覆盖限制了结论的外推。

## 本地入口

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
