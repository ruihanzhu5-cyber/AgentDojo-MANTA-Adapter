# Folded MANTA 独立代码审查

2026-10-29。使用 experiment-bridge 的独立代码审查步骤；用户明确要求只实现，不部署、不跑实验。
审查者通过隔离上下文只读源代码，没有修改文件、运行 episode 或调用 API。

## 审查发现与处理

| 发现 | 处理 |
| --- | --- |
| get_unread_emails 实际会修改未读状态 | consume 显式效果，主循环核验与失效，不进入只读缓存 |
| 永久防重放误用于导航 | 导航重新授权并实际读取，状态变化后可以获得新页面 |
| 核验只看到原文开头 | 支持所选片段，记录坐标/hash，并作为判定缓存身份 |
| 旧客户端隐藏请求重试使 episode 计数不准 | 新后端只调用一次被观测的 transport attempt；保留逐请求财务台账 |
| 同步嵌套调用可能丢失主 Agent reasoning | 各上下文独立保存、恢复实际 reasoning_history |
| provider 空选择可能被当作参数错误 | 中央检查 usable choice，协议失败抛基础设施异常，不计安全结果 |
| 内部工具 JSON 合法但参数类型错误 | 执行 Python 方法前验证内部 schema |
| 复用 pipeline 时 observer 状态串 episode | 新 profile 每次 query 重置请求、Runtime、完成标记与错误状态 |
| 后续读取覆盖了此前未解决错误 | 独立跟踪未解决失败，触发一次有界局部恢复 |
| 预算/核验异常日志含糊 | 明确资源终止、review_error、handler_invoked=False |
| bind_suite 不必要读取攻击任务 GOAL | folded profile 仅建立用户任务 ID 映射；注入观测只用于日志 |
| 新工作目录没有 .env | 显式已有凭证文件路径，Python 加载与 PowerShell 恢复一致 |
| folded 仍报告旧写协议 | 元数据明确 guarded_native、selective_pre_action |

## 最终只读复核结论

审查者报告上述具体 P1/P2 问题已修正，没有发现其他阻塞正确性或安全缺陷。
实际 Runtime 是官方工具轨迹来源；缓存、被阻动作和提案不伪装成 Runtime。
网关不自动改写动作参数，不使用官方攻击目标、评分或注入匹配键作防御决策。

审查者要求补充的 mocked adapter transport 检查已加入 test_folded_execution.py，
覆盖独立 reasoning、单次观测、额度不足零发送和 unusable-response 异常。
检查通过状态以实施完成时的实际测试输出为准；本审查不构成实验效果证明。
目前只有单请求超时和 turn/call/token 预算，没有 episode 总墙钟 deadline。
