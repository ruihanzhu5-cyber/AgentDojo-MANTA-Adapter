# MANTA × AgentDojo：80 场景正式批次

在 `D:\AgentDojo-MANTA-Adapter` 中执行：

```powershell
Set-Location 'D:\AgentDojo-MANTA-Adapter'
uv sync --locked --no-dev --python 3.12
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请不要继续启动' }
$env:DEEPSEEK_MODEL = 'deepseek-v4-flash'
$env:V1_MAX_COST_USD = '10'
& .\.venv\Scripts\python.exe -u .\scripts\manta\run_formal.py --parallelism 8
```

复用终端或 `.env` 中已有的 `DEEPSEEK_API_KEY`。本命令由操作者明确设置本批次 10 美元预算；需要其他额度时修改该数值。不会展示 API 密钥。上限只覆盖本队列的请求，不覆盖账号其他任务。按旧 pilot 的 847269 输入、56803 输出 token 外推，160 条在峰时未缓存价格下约 6.45 美元；这只是同用量外推，其他 suite 和重试可能增加用量。

80 个场景，每个配对一次 Clean 和一次官方 direct 攻击，共 160 条 episode。workspace/travel/banking/slack 各 20 场景。共 76 个不同用户任务；banking 的 4 个用户任务搭配不同攻击目标复用，Clean 也按场景重复。这是按场景计权的设计，不能把重复 Clean 当作独立任务。任务先洗牌再轮转攻击目标，固定 seed 42；不依据评分或暴露率选样。此批次覆盖 direct 攻击，不代表所有官方攻击算法。

参数沿用验收：AgentDojo v1.2.2，task_conditioned planner，heuristic audit，初始 Agent 预算 3、初始上限 5、总上限 10、max_turns 2、repair_budget 1。保留 MANTA 自身写操作保护和自适应逻辑，不根据本批次中途结果调整。

默认结果目录：`results/v1/formal_80_seed42`。`manifest.json` 冻结任务及代码指纹；每个 attempt 都有独立结果和日志。`progress.json` 显示进度，`summary.json` 在运行结束时汇总。未有效评分的任务不会记作安全成功。

正常 Ctrl+C 会停止本次子进程，重复相同命令会跳过已经有效评分的任务，失败 attempt 保留，每个任务默认最多 2 次尝试。预算耗尽时保留队列；提高 `V1_MAX_COST_USD` 后用相同命令续跑。额度为整个目录的累计上限，不是续跑时再加一次。强制关闭终端后，若旧子进程仍活跃，启动器会拒绝同时续跑。不要在正式运行期间改代码；指纹变化会阻止混合结果。

预算检查在每个真实 HTTP 请求前通过共享 SQLite 预留。依据 2026-10-18 DeepSeek 官方 Flash 峰时输入 $0.30/M、输出 $1.20/M；缓存和低峰折扣忽略，因此统计为费用保守上界，不是账单。每次先按最大输入窗口与请求输出上限预留，返回后按 usage 缩减；无 usage 或丢失响应保留完整预留，可能提前停下。SDK 隐式重试关闭，MANTA 的重试逐次预留。实际提供方价格变化可能使该价格假设失效。官方来源：https://api-docs.deepseek.com/quick_start/pricing/。

官方目前将 `deepseek-v4-flash` 别名路由到 DeepSeek-V4.1-Flash-1017；结果记录请求名及响应提供的 model 字段，不宣称运行已下线模型。新字段只保证从本批次开始记录，不修改旧 pilot 原始结果。

免费准备（生成正式队列但不发 API 请求）：

```powershell
& .\.venv\Scripts\python.exe -u .\scripts\manta\run_formal.py --dry-run
```
