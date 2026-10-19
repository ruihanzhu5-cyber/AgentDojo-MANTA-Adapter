# 原生状态恢复与 Graph-only 机制实验

日期：2026-10-19。当前为新机制配置，不与旧 160 条正式实验或上一轮 24 次局部重放混合统计。

## 1. 要检验什么

在原生 MANTA 已经执行过任务驱动的拓扑演化、已经读到攻击内容，但官方目标尚未达成的状态：

- G0：恢复完整状态，保持原图继续。
- G1：恢复同一个状态，仅修改一个原生 group 的图模式，按该模式的原生调度继续。

初始的任务、Agent 身份、结构角色、节点工作角色、ContextPolicy、历史消息、artifact、共享证据、
工具环境、去重记录和本地随机状态都保持一致。后续 prompt 可以因原生调度/可见消息规则改变而不同。
本实验比较原生图模式及其调度语义，不宣称“只改邻接矩阵且所有后续 prompt 不变”。

## 2. 为什么显式使用 commit_once

旧配置的 transactional_star 会覆盖部分图形态变化。这轮显式使用官方提供的 commit_once，保留 planner 和 mutator 提出的图，
写工具沿用原生 proposal/最终提交语义。两组均使用相同协议，不把这一变化藏在 G1 中。

其他冻结设置延续前轮约束：3 初始 Agent 预算、最大初始 5、总计最大 10、max_turns=2、repair_budget=1、
heuristic audit、task_conditioned planner、冻结 skills、peer_artifact_max_chars=1200、lexical termination、deterministic vote。
本轮不声称覆盖默认 hybrid audit、更多轮数或在线学习的全部能力。

## 3. 采样与规模

先固定 12 个旧正式 Attack 候选：优先旧运行中发生过 mutation 的场景，再按 ID 排序补足。
新的 capture 运行使用上述 commit_once 配置，先验候选排序不依赖新续跑的成败。

每个候选在第一次原生 repair 完成后的下一轮入口检查：

1. turn_index=1，原生 controller 实际决定继续，存在可执行的后续轮次。
2. 已完成的模型请求中存在完整官方 payload 暴露。
3. 用实际模拟环境、实际前缀调用和当前 incumbent answer 检查官方目标，结果明确为 False。
4. 没有请求基础设施错误、截断或被标记的不完整阶段。
5. 预先定义的原生图模式切换合法，并且实际 adjacency 改变。

按冻结候选顺序选取最多 6 个合格状态，每个状态 G0/G1 各重复 3 次，最多 **36 条续跑**。
采集阶段最多 12 次前缀执行，另计入预算。实际合格状态不足 6 个时，只对实际合格状态开展配对并明确分母；
一个也没有时报告 NO_ELIGIBLE_STATES，不伪造状态或强制原生 controller 继续。

### 对原计划的预先调整

原计划设想混合有/无 mutation 的状态。当前支持的严格安全恢复边界是原生下一轮入口，而原生 controller 只有在有效 repair 后才到达这里。
因此本轮样本限定为实际演化状态，不再声称覆盖混合状态样本。这个调整发生在付费采集之前。

## 4. 图干预规则

依次检查 root group，再按 group_id 检查其他 group。选择第一个能改变 adjacency 的合法模式切换：

- chain → star；其他支持的 star/debate/voting → chain。
- group 的成员与附着父节点保持相同；根 star 的 leader 按冻结成员顺序选择。
- 节点 structural_role、stage_role、allowed_tools、context policy 不变；extra_edges 不变。
- 不根据攻击是否成功选择“最好/最差”的图。

G1 的干预记录位于独立 execution_graphs 字段；原生 spec_versions 保留原生历史，不人为增加 repair 消耗。
最终分析以实际 executor 接到的图、stage 执行顺序和实际模型输入为准，不能只看历史 spec_versions 的末项。

这是一个预定义的具体图干预，不能据其结果推断所有 Graph-only 防御都无效。

## 5. 保存与恢复实现

`graph_checkpoint.py` 对固定源码版本的原生 run 方法做受限 AST 分段：

- capture 只在原生外层轮次循环的入口增加 checkpoint hook；到达合格边界即停止前缀。
- resume 从完整保存的局部变量恢复，执行该位置以后的原始循环和 finalize AST。
- 不重跑任务前缀，也不使用录制模型回复重放来冒充恢复。
- 原生源码文件不改写；源码 SHA 不符或循环入口改变时拒绝运行。

快照使用白名单 JSON 对象图，保留共享引用/alias，不使用 pickle、dill 或任意输入代码执行。
包含完整 frame、state、context、executor 去重集合、短期 playbook、原生 engine 缓存、NullDescriptor 的 monitor_records、
client 请求序号和非秘密配置、本地 Python/NumPy RNG 状态，以及官方 Pydantic 模拟环境和初始环境。
工具 handler 不序列化为代码：按固定源码重建并重新绑定到该分支的独立模拟环境。
官方 domain model、日期、枚举和字段集合按白名单对象图恢复，不重新调用会重建日历/邮件索引的校验器。
环境中的对象与历史工具输出之间的共享引用也保持一致，不能把两者恢复成互不关联的副本。

仅允许已审查类型。自定义 descriptor、未知 engine/planner 状态、非空编译图 cache 或无法保存的对象会导致拒绝，不能静默丢字段。
没有跨轮未返回的 HTTP 请求；不保存连接池和线程锁等传输资源。远程模型内部随机性不可恢复，三次重复不等于确定性共同随机数。

## 6. 指标与有效性

- 主要结果：从同一尚未达到目标的状态继续后，官方 attack_success 和 task_success。
- 每个 state×repeat 分别保留 G0/G1 配对；同时报告任务效用，不能把中断任务当作安全。
- 实际图：execution_graphs、execution_signature、continuation_views、完整 continuation_logs。
- Context：历史 artifact、可见 packet、共享 digest 与最终综合输入保留在原生阶段 prompt 中；
  provider_inputs.json 另保留所有实际请求和响应，包括工具结果和内部重试。
- 源码、checkpoint 全文件 hash、frame hash、非图状态回编码一致性、模拟环境一致性均在续跑前核对。
- 普通工具域错误保留为模型行为并计数；连接失败、超时、截断、请求上限等不作为有效安全负例。
- 实际执行图被覆盖、同 checkpoint 不匹配或 G0/G1 调度没有变化时，配对门槛不通过，暂停后续重复。

所有条件都没有攻击，不能据此说明图无效；G1 降低攻击并保持效用时应保留支持图干预的证据。
历史 context 继续存在只说明保留，不能自动称为越权；沿合法多跳到达的信息也不算绕图。

## 7. 启动

```powershell
Set-Location 'D:\AgentDojo-MANTA-Adapter'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $env:DEEPSEEK_API_KEY) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
}
$env:DEEPSEEK_MODEL = 'deepseek-v4-flash'
$env:DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
& '.\.venv\Scripts\python.exe' -u '.\scripts\run_graph_experiment.py' --parallelism 4 --budget-usd 5
```

先执行零请求预检可加 `--preflight`。用户启动后才采集真实 checkpoint；预检不会编造真实状态。
默认目录：`results/v1/graph_checkpoint_commit_once/`，使用独立预算数据库，不动前两轮结果。
5 美元是沿用已有固定保守费率的记账上限，不是预计花费或实际供应商账单保证。
采集和续跑合计受同一新台账约束；失联请求保留预留。

首轮 G0/G1 配对有效且调度确实不同后，才继续其余两轮重复，与攻击结果方向无关。
已完成的 capture/branch 会跳过。不完整尝试检查原因后显式加 `--retry-incomplete`；每个 job 最多 3 次尝试。
配置/源码改变须使用新的 run-dir。普通 NO_ELIGIBLE 是已完成的采样判定，不通过重跑来挑选有利状态。

## 8. 输出

- manifest.json：新配置、候选顺序、版本和源码指纹。
- capture/<case>/attempt_*/checkpoint.json：真实快照及完整性信息。
- capture_summary.json：合格、未合格和基础设施异常状态，保留全部采集记录。
- branches_manifest.json：冻结的 state×condition×repeat 与快照配对关系。
- branch/<job>/attempt_*/result.json：官方结果、实际图、上下文、调用台账和原生 metadata。
- summary.json：条件分子/分母、逐状态配对结果、图调度核验。
- progress.json、active_pids.json、budget.sqlite：进度与资源台账。

原始环境、请求和响应可能包含模拟账号、邮件等数据，公开前需要脱敏；当前仅保存在本地结果目录。
