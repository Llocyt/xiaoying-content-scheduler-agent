# 参考来源与实现差异

## 来源

提交者在本地 Python 初版已实现后，提供 [JasonLiu0826/xiaoying-content-scheduler-agent](https://github.com/JasonLiu0826/xiaoying-content-scheduler-agent) 并要求参考改进。读取的参考版本为 `b72786554cd7fd11628d25aa8b451be10f4557dd`。

查阅了公开 README、`docs/02-solution.md`、`docs/03-evaluation.md`、`docs/04-ai-usage.md`、`package.json` 及目录。目录未见 LICENSE。本次没有复制源码、素材数据、文档段落、测试代码或真实运行文件，也不将来源项目表述为本次提交者原创。

## 对当前实现的具体影响

| 参考设计 | 当前落实及变化 |
|---|---|
| 同一草稿从 pending 确认成 confirmed | 原 Python 初版要求新请求；现改为同请求授权更新，复用 draft_id，补充确认竞争测试 |
| 保存时重新校验规则与占用 | 当前在 SQLite 写事务内重新查询占位，在写入边界重新读取合成素材并审核 |
| 每组保留资料与数据库审计 | 评估器新增 catalog、trace、audit 文件；审计由 SQLite 直接读出 |
| 最终状态由业务事实产生 | 保留原实现的事实字段，进一步去除模型自然语言对用户摘要的影响 |

## 独立实现的选择

参考项目为 TypeScript/Node，当前使用 Python 3.11+ 标准库；参考项目支持多素材，当前明确限制单素材。当前提供独立的元数据补查工具，以演示“缺信息→补查成功继续”和“补查失败停止”两条路径。

模型动作采用单动作 JSON 协议，不是源码层移植参考项目的工具调用适配器。SQLite 表结构、Python 工具实现、测试与数据均为本工作区独立编写。版本证据使用源码 SHA-256，不引用对方测试数或模型成功率。

所有当前测试和离线运行记录均在本工作区重新生成。后续获得复用授权或采用其他第三方代码时，应按实际情况更新来源与许可文件。
