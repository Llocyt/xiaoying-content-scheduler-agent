# 素材审核与发布排期 Agent

小影校招 AI Agent 开发项目题 **第 1 题**。审核素材、补查元数据、发现时段冲突并保存排期草稿；所有结果均为草稿，没有真实发布入口。

**当前验证：49 项自动化测试、13 组离线验收、13 组真实 deepseek-flash 验收全部通过。** 真实调用使用提交者指定的网关。Mock 只证明工具和流程，真实模型结果单独保存在 `examples/live/`；首轮真实验收失败记录保留在 `examples/live-initial/`。

## 评审入口

- [需求与成功标准](docs/01-requirements.md)
- [决策循环、确认与防重复设计](docs/02-solution.md)
- [验收矩阵与已知限制](docs/03-evaluation.md)
- [AI 使用、参考来源与个人贡献](docs/04-ai-usage.md)
- [开发复盘](docs/05-retrospective.md)
- [设计参考与实现差异](docs/06-reference-and-changes.md)
- [本次实际验证汇总](examples/mock/verification.json)、[测试原始输出](examples/mock/tests.txt)
- [真实模型验证汇总](examples/live/verification.json)、[真实模型冲突路径](examples/live/conflict.trace.json)

本项目参考了 [JasonLiu0826/xiaoying-content-scheduler-agent](https://github.com/JasonLiu0826/xiaoying-content-scheduler-agent) 的公开设计说明。当前仓库为独立 Python 实现，未复制其源码、文档、个人贡献表述或真实模型运行记录。参考版本与具体影响见 [来源说明](docs/06-reference-and-changes.md)。

## 环境与安装

Python **3.11+**，运行和测试只用标准库，不需要 Agent 框架、外部数据库或模型 SDK。所有命令从仓库根目录执行。

```sh
git clone https://github.com/Llocyt/xiaoying-content-scheduler-agent.git
cd xiaoying-content-scheduler-agent
python -m pip install -e .
python -m unittest discover -s tests -v
```

离线环境不安装包也可运行，PowerShell 先执行 `$env:PYTHONPATH='src'`，bash 先执行 `export PYTHONPATH=src`。之后同样使用下方 Python 命令。

## 三分钟演示

```sh
# 正常排期：19:00 可用，保存已确认草稿
python -m scheduler --input examples/mock/normal.input.json --db .runtime/normal.sqlite --output .runtime/normal.json

# 重复执行同一命令：save_status=existing，仍只有一份草稿
python -m scheduler --input examples/mock/normal.input.json --db .runtime/normal.sqlite

# 硬性 18:00 已占用，建议 19:00，仅保存待确认草稿
python -m scheduler --input examples/mock/conflict.input.json --db .runtime/conflict.sqlite

# 用户明确确认 19:00；同一数据库、同一 request_id，更新原草稿
python -m scheduler --input examples/mock/confirm_pending.input.json --db .runtime/conflict.sqlite

# 保存故障：明确 save_failed，不声称保存成功，退出码 2
python -m scheduler --input examples/mock/save_failure.input.json --db .runtime/failure.sqlite --fail-save

# 执行上限：step_limit，退出码 2
python -m scheduler --input examples/mock/normal.input.json --db .runtime/limit.sqlite --max-steps 1
```

重跑演示时，已确认的原草稿不会降级回待确认状态；需要全新实验请使用不同的 `--db` 路径。普通的“重复提交”定义为相同 `request_id` 与相同基本请求；不同请求 ID 视为不同业务请求，但已确认草稿仍受时段唯一约束保护。

## 输入与输出

```json
{
  "request_id": "content-team-001",
  "asset_id": "M01",
  "requested_slot": "2026-11-01T18:00+08:00",
  "hard_requirement": true
}
```

`hard_requirement` 缺省为 `true`。确认替代时段时，由用户在上述同一个请求中加入 `"confirmed_slot": "2026-11-01T19:00+08:00"`；Agent 的工具参数无法提供这份授权。CLI 将调用者视为已授权用户，本例没有登录系统。

程序输出 JSON，包含 `review_status`、`risk_reasons`、`requested_slot`、`suggested_slot`、`pending_items`、`save` 与逐步 `trace`。每一步记录模型动作、工具参数、真实观察、简短理由及实际后续动作。没有采集模型内部思维过程。

只有收到持久化回执，才报告 `saved`、`updated` 或 `existing`。模型说“成功”不能改变最终状态；`published` 始终为 `false`。待确认草稿不会预占时段，后续确认可能因其他请求抢先占位而失败。

退出码：`0` 表示有明确处理结果（草稿保存、待确认、规则阻断或人工复核）；`2` 表示资料不足、工具/模型错误、保存失败、执行未完成或报告写入错误。自动化评审还应读取 JSON 的业务状态，不只看退出码。

## 真实模型接入

支持提供 `/chat/completions`、`response_format: json_object` 的兼容服务。模型每轮生成一个 JSON 动作，实际工具结果进入下一轮上下文。没有任何运行时自动降级成 Mock 的行为。

将 `.env.example` 复制为 `.env`，填写 `MODEL_API_KEY`、`MODEL_BASE_URL`、`MODEL_NAME`。真实模式自动读取当前目录的 `.env`，也可指定 `--env-file PATH`；已有进程环境变量优先。Mock 不读取密钥文件。配置文件只支持四个示例变量与整行注释、可选的成对引号，不执行命令或变量展开。

为用户明确指定的远程 HTTP 网关设置 `MODEL_ALLOW_HTTP=1`；未明确启用时仍拒绝远程 HTTP。网关地址可写 origin（例如 `http://your-gateway:8000`，自动追加 `/v1`），也可填写完整 API 前缀。示例本机配置：

```dotenv
MODEL_API_KEY=仅在本机填写
MODEL_BASE_URL=http://your-gateway:8000/v1
MODEL_NAME=deepseek-flash
MODEL_ALLOW_HTTP=1
```

`MODEL_NAME` 需使用网关 `/v1/models` 实际返回的模型名，不能凭空假定 `deepseek-chat` 是有效别名。`.env` 被 Git 忽略；密钥不进入 Trace 或提交。

PowerShell 示例（请在本机填写，密钥不要提交）：

```powershell
$env:MODEL_API_KEY = '在本机填写'
$env:MODEL_BASE_URL = 'https://你的兼容服务地址/v1'
$env:MODEL_NAME = '你的模型名'
python -m scheduler --mode live --input examples/mock/conflict.input.json --db .runtime/live.sqlite --output .runtime/live-conflict.json
python scripts/verify.py --mode live --out examples/live
```

bash 使用 `export MODEL_API_KEY=...`、`export MODEL_BASE_URL=...`、`export MODEL_NAME=...` 设置相同变量。默认使用 HTTPS；本机回环服务允许 HTTP，用户选择的远程 HTTP 须设置上述显式开关。请求超时 45 秒，不自动重试，不跟随重定向。

真实模型评估会调用模型并产生费用。完成后检查 `examples/live/verification.json`，确认用例、Trace 和审计均符合预期，再更新评估文档和提交 SHA。对方仓库的真实模型成功率不能替代本项目的验证。

## 重新生成证据

```sh
# 建议写入新目录，保留仓库中的原始证据
python scripts/verify.py --mode mock --out .runtime/review-mock

# 有意更新仓库证据时使用默认目录
python scripts/verify.py
```

每组记录包含 `.input.json`、`.catalog.json`、`.output.json`、`.trace.json` 和 `.audit.json`。汇总保存实际运行时间和源码 SHA-256。评估使用临时数据库，重复提交和确认场景共享对应数据库，结束后关闭连接并清理。

## 目录

```text
src/scheduler/       模型适配、决策循环、工具、CLI、输入校验
tests/              业务不变量、并发、模型协议与 CLI 跨进程测试
data/fixtures.json  合成素材、审核规则、占用时段
examples/mock/      本次真实执行的离线输入、输出、Trace、数据库审计
scripts/verify.py   可复现验收与测试报告生成
docs/               需求、方案、评估、AI 使用和复盘
```

边界：单素材、单频道、同日整点时段。审核规则是合成短语/版权规则，不替代真实审核服务。不实现发布、UI 或多 Agent。提交者亲自完成的验证和学习记录仍须如实补充。
