# SA-00 · Contract & Spec Sync

## What
落地 `deep_research/AGENTS.md` §10 要求的最小合同改动：新增 `ReportKind` 枚举、扩展 `ChatMessage.kind` 与 `SendTeachingMessageRequest.report_kind`，并在 chat 路由层加上 mode×report_kind 的组合校验，把 `module_interaction_spec.md` §13 的 deep_research import 白名单与 AGENTS.md §11.1 对齐。

## Files
- mod  new_kernel/contracts.py:+7  ReportKind 枚举 + ChatMessage.kind + SendTeachingMessageRequest.report_kind
- mod  new_kernel/module_interaction_spec.md:+8/-1  §13 deep_research 白名单与 AGENTS.md §11.1 对齐 + 表后禁止清单段落
- mod  new_kernel/api/routes/chat.py:+29  ReportKind import + `_validate_mode_report_kind` 路由层校验，在 start_turn 之前调用
- new  new_kernel/tests/test_contracts.py:48  3 条契约默认值与组合校验单测
- new  new_kernel/deep_research/.reports/README.md:21  报告索引
- new  new_kernel/deep_research/.reports/SA-00-contracts.md:本报告

## Decisions
- 路由层校验拒绝错误组合时统一使用 `ErrorStage.CHAT`（按本次任务硬约束指定），即便 `mode=deep` 误用也归 CHAT 阶段，避免在 stage 选择上引入新分支。
- `_validate_mode_report_kind` 放在 `_stage_for_mode` 之后、`get_session` 之前调用，保证不触达 session 层；使用既有 `ApiModuleError` + `api_error()` 模式，未引入新 helper。
- 测试用 `==` 比较 `ReportKind.X.value`（字符串）而非枚举本身：`ContractModel` 配置 `use_enum_values=True`，序列化后字段值是字符串，必须按字符串断言，否则会因为 `"answer" == ReportKind.ANSWER` 在 StrEnum 下虽然成立但不直观；显式 `.value` 让意图清晰。
- 表后禁止段落同时附了两条额外解耦补丁（EventSink/EventFactory 与 RepoOverview/repo_root 仅参数注入），与 AGENTS.md §11.1 的"不直接 import events/repo"对齐，没有偏离。
- 与 AGENTS.md 的偏离：无。

## Verification
- python -m compileall new_kernel\contracts.py new_kernel\api\routes\chat.py — 通过（静默退出）
- python -m pytest -q new_kernel\tests\test_contracts.py — 通过（3 passed in 0.27s）
- 已知问题 / TODO：无

## Spec Alignment
- AGENTS.md §0、§10、§11.1
- 上层规约 module_interaction_spec.md §13
