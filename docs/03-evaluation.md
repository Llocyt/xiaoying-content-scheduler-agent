# 效果验证、失败与限制

## 实际结果

2026-10-30（北京时间）在 Windows / Python 3.13.12 执行：**49 项自动化测试、13 组离线验收、13 组真实 deepseek-flash 验收全部通过**。离线命令：`python scripts/verify.py`（源码环境设置 `PYTHONPATH=src`）；真实命令：`python scripts/verify.py --mode live --out examples/live`。

原始证据：[机器可读汇总](../examples/mock/verification.json)、[测试输出](../examples/mock/tests.txt)。汇总中的 UTC 时间对应北京时间，文件保存源码、评估器及测试的 SHA-256，便于核对证据对应的实现版本。运行耗时以原始输出为准，不将执行测试的时间当作人工开发耗时。

用户随后提供真实网关与可用密钥，模型列表查询返回 `deepseek-flash`、`deepseek-v4-pro`，本次选择前者。真实 API 调用产生的记录与离线测试分开保存。模型适配器的序列化单元测试仍使用模拟 HTTP 回包，不能替代真实调用证据。CI 已配置 Python 3.11/3.13；远程执行结果需以 GitHub Actions 为准。

## 真实模型结果

修复后完整复跑的[真实汇总](../examples/live/verification.json)记录 `real_model_verified=true`、13/13 通过、49 项测试通过。13 个实际执行报告共记录 61 轮模型选择、49 次业务工具执行；本轮没有触发格式纠正。这是一次固定合成样本验收，不是生产成功率。

| 路径 | 真实模型证据 | 观察到的行为 |
|---|---|---|
| 正常 | [Trace](../examples/live/normal.trace.json) | 读取、审核、查询原时段、保存后观察回执再结束 |
| 缺资料 | [Trace](../examples/live/missing.trace.json) | 补查仍无版权资料，规则返回 incomplete，模型停止 |
| 风险 | [输出](../examples/live/risk.output.json) | 规则阻断，0 草稿 |
| 时段冲突 | [Trace](../examples/live/conflict.trace.json)、[审计](../examples/live/conflict.audit.json) | 18:00 占用，模型补查 19:00，保存待确认草稿且不占位 |
| 重复提交 | [审计](../examples/live/duplicate.audit.json) | 草稿仍为 1 份，返回 existing |
| 补充确认 | [输出](../examples/live/confirm_pending.output.json)、[审计](../examples/live/confirm_pending.audit.json) | 与冲突场景同一草稿更新为 confirmed，仍为 1 份 |
| 保存失败 | [Trace](../examples/live/save_failure.trace.json)、[审计](../examples/live/save_failure.audit.json) | 模型观察保存失败后有限重试并结束；最终 save_failed，0 草稿 |

其余补全资料、人工审核、自带授权、无可用时段、更换占用及步数上限的输入、资料、输出、Trace 和审计均存放于同目录的同名前缀文件。原始记录没有密钥，也没有使用参考项目的模型日志。

## 必须验收点

每组前缀对应 `.input.json`、`.catalog.json`、`.output.json`、`.trace.json`、`.audit.json`。资料快照包含本轮实际占用数据，审计直接读取本轮 SQLite，而非从模型文本推测。

| 要求 | 实际输出与动作证据 | 预期及本次实际结果 |
|---|---|---|
| 正常排期 | [normal 输出](../examples/mock/normal.output.json)、[Trace](../examples/mock/normal.trace.json) | 19:00 空闲，审核通过，保存 confirmed 草稿 |
| 信息缺失 | [missing 输出](../examples/mock/missing.output.json)、[Trace](../examples/mock/missing.trace.json) | 补查仍缺 rights，incomplete，0 草稿 |
| 规则风险 | [risk 输出](../examples/mock/risk.output.json)、[审计](../examples/mock/risk.audit.json) | 禁用文案被 blocked，0 草稿 |
| 时段冲突 | [conflict 输出](../examples/mock/conflict.output.json)、[Trace](../examples/mock/conflict.trace.json) | 18:00 占用，查到 19:00，pending_confirmation，原时间保留 |
| 重复提交 | [duplicate 输出](../examples/mock/duplicate.output.json)、[审计](../examples/mock/duplicate.audit.json) | 与 normal 共享库，existing，草稿数仍为 1 |
| 保存失败 | [save_failure 输出](../examples/mock/save_failure.output.json)、[审计](../examples/mock/save_failure.audit.json) | 注入写入前故障，save_failed，0 草稿 |

## 额外路径

| 用例 | 证据 | 本次实际结果 |
|---|---|---|
| 对原草稿补充确认 | [confirm_pending 输出](../examples/mock/confirm_pending.output.json)、[审计](../examples/mock/confirm_pending.audit.json) | 与 conflict 共享库，updated，同一 draft_id，草稿数仍为 1 |
| 元数据可补全 | [metadata_recovery Trace](../examples/mock/metadata_recovery.trace.json) | 补到版权资料后继续排期并保存 |
| 人工复核 | [human_review 输出](../examples/mock/human_review.output.json) | review_required，不保存 |
| 请求自带明确授权 | [confirmed_alternative 输出](../examples/mock/confirmed_alternative.output.json) | 替代时间已被请求确认，保存 confirmed 草稿 |
| 所有时间占用 | [no_available_slot 输出](../examples/mock/no_available_slot.output.json) | incomplete，0 草稿 |
| 更换占用数据 | [changed_occupancy 资料](../examples/mock/changed_occupancy.catalog.json)、[输出](../examples/mock/changed_occupancy.output.json) | 改为 19:00 占用后，原 18:00 可用并保存 |
| 步数上限 | [step_limit 输出](../examples/mock/step_limit.output.json) | 1 轮后 step_limit，明确未完成 |

不同观察导致不同动作的记录已实际生成：正常路径查询后保存；冲突路径追加替代查询；缺资料路径补查后停止。上表链接为离线证据；真实模型同名文件位于 `examples/live/`，可逐步对照工具参数与观察。

## 自动化测试覆盖

除上述路径，还测试同 ID 改输入、并发重复保存、两个请求竞争同一时段、确认时被其他请求占用、查询后资料版权改变、直接越过审核或查询保存、未知发布工具、非法参数、跨天时段、模型提前虚报成功、错误模型动作、回执被外部修改、跨进程重放和报告输出失败。

## 实际发现与修复

- 初次验证在 Windows 清理临时目录时失败：SQLite 的上下文管理只负责事务，没有自动关闭连接。改为显式关闭连接后，重新执行全量测试通过。
- 早期方案为确认使用新的请求 ID，会产生独立草稿。参考公开项目的确认设计后，改为相同请求的授权更新，补充“同一草稿确认”和“确认竞争”测试。
- 复核发现模型的结束理由可能声称“保存并发布”，即使事实字段正确也会误导用户。最终摘要改由业务状态生成，原始动作理由仅作为 Trace 保留。
- CLI 报告写入失败发生在草稿成功保存之后。现在先输出真实业务结果到 stdout，再尝试写报告；写失败明确返回 artifact_error，不把草稿回执丢失。
- 真实网关首轮实际验收仅 7/13 通过：5 组结束动作格式错误，1 组看到人工复核标记后跳过了规则检查。保留[首轮汇总](../examples/live-initial/verification.json)及其中六组完整失败报告，没有用重跑结果覆盖这些历史证据。收紧结束动作格式、增加预算内的一次格式纠正机会，并在缺少审核观察时拒绝提前结束，补充回归测试。

## 限制

- 真实模型运行仅覆盖一个模型的一套固定合成用例，未做大样本、多次随机重复或生产效果验证。Mock 全通过仍不代表真实模型能力。
- 单素材、单频道、同日整点窗口；不支持跨日自动改期和批量任务的部分成功聚合。
- 版权、短语与人工复核标记是合成规则，无视觉/语义审核。
- 待确认建议不占位；最终确认必须重查。已确认草稿没有撤销或重新排期工具。
- 同 ID 重复请求须保持原素材、原要求、软硬限制；不同 ID 不视为同一请求。
- 模拟保存故障是写入前注入，不是磁盘损坏、断电或文件系统故障实验。
- 资料为调用时快照，SQLite 保证本地草稿一致性，不保证与外部排期服务同步。
- CLI 以调用者提供的确认字段作为授权，无生产级身份认证。HTTP 超时后直接报错，不做自动网络重试。

## 补充真实证据

配置 README 中三个模型环境变量后，执行 `python scripts/verify.py --mode live --out examples/live`。检查每组工具参数、观察、后续动作及数据库审计；若失败，保留失败证据并修改实现后重新验证。使用本项目新生成的结果更新本文件，不能沿用参考项目的模型名、测试数或成功结论。
