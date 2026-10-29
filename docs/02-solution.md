# 方案与技术取舍

## 调用流程

`CLI → 输入校验 → 有上限的 Agent 循环 → 模型动作 JSON → 工具白名单 → 实际观察 → 下一轮模型`

`src/scheduler/agent.py` 只负责循环和动作格式校验，不通过固定分支替真实模型决定业务动作。模型收到原始请求与此前全部工具观察，每次选择下一项动作。程序执行工具后把实际观察送入下一轮；模型可结束，最终报告由工具层重建。

`OpenAICompatibleModel` 请求兼容 Chat Completions 服务。采用 JSON 动作协议而非厂商 function calling，减少 SDK 依赖；目标服务必须支持 JSON object 输出。动作严格含 `tool`、`arguments`、`reason`。服务返回格式错误、HTTP 错误或超时会产生明确 `model_error`，不伪装 Mock 成功。完整真实服务兼容性尚待验证。

`MockModel` 是固定规则的离线替身，独立标记 `mode=mock`。它会根据观察生成不同动作，但不算真实模型 ReAct 验证。真实模式不会调用该替身。

## 工具及事实来源

| 工具 | 功能与限制 |
|---|---|
| `read_asset` | 只读请求中的素材，不能访问其他素材 |
| `lookup_metadata` | 从补充元数据库填充缺失字段，不覆盖已有字段 |
| `check_rules` | 检查必填字段、版权、禁用短语、人工复核标记 |
| `query_slots` | 查询同日时段，可返回资料中列出的替代候选 |
| `save_draft` | 重审规则、校验已查到的空闲时段、确认授权、事务持久化 |
| `finish` | 结束循环；不能提供保存结果或覆盖最终状态 |

正常路径示例：读取 → 审核 → 查询原时间 → 保存 → 观察成功 → 结束。

冲突路径示例：读取 → 审核 → 查询原时间发现占用 → 查询替代 → 保存待确认建议 → 观察 pending 回执 → 结束。

资料不足路径示例：读取发现缺字段 → 补查 → 审核仍不足 → 结束，不保存。保存失败路径观察错误后可以选择重试或结束；重试仍受统一上限控制。

## 草稿一致性

SQLite 的 `drafts.request_id` 为主键。请求规范化后产生 SHA-256 摘要，排除后续的 `confirmed_slot` 授权字段；素材、原要求或软硬约束改变则摘要改变，禁止复用同一 ID。重复请求返回已存在的草稿。

同一请求精确确认替代时间时，pending 更新为 confirmed，`draft_id` 不变，不新增第二份草稿。已存在草稿的建议时间与本轮建议不同则返回 `existing_draft_time_mismatch`，避免暗中移动草稿。

`reservations.slot` 唯一。只有 confirmed 草稿持有时段，pending 建议不预占。保存采用 `BEGIN IMMEDIATE`，在同一事务中复查时段、写草稿与占位；并发重复请求返回同一份草稿，并发不同请求无法占用同一时段。连接显式提交/回滚并关闭，兼容 Windows 临时文件清理。

保存前重新读取合成素材及已补查元数据，并重新审核当前规则；不能仅依赖前面通过的检查。已有占用表是本次调用的资料快照，真实外部排期变化须通过重新加载资料或接入真实工具体现；本例没有文件监听或跨服务事务。

## 状态与确认

`completed` 需要持久化成功且无待确认；`pending_confirmation` 表示建议草稿已保存但硬性替代时段待用户确认。`incomplete`、`blocked`、`review_required`、`save_failed`、`model_error`、`step_limit` 分别暴露未完成原因。

CLI 输入被视为可信调用者提交，确认只能由该输入提供，工具参数无法伪造；这不是一个生产身份认证方案。原 `requested_slot` 始终保留。确认后仍只是草稿，`published=false`。

## 技术选择

Python 标准库使评审离线即可运行；SQLite 提供可审查的本地事务。原生循环保持逻辑直观，不使用 Agent 框架，不需要框架版本说明。测试使用 `unittest`，HTTP 使用 `urllib`；只有可选的可编辑安装需要 setuptools，源码运行无需安装。

相较参考项目，本项目改用 Python、一个动作一轮的 JSON 协议、单素材输入，并增加显式元数据补查工具。独立编写代码而非复制 TypeScript 项目，具体来源范围见 `06-reference-and-changes.md`。
