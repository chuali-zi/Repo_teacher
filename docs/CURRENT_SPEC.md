# Repo Tutor — 当前规范入口

后续脚手架 Agent 必须以本文件列出的文档作为当前有效规范。

## 当前有效文档

1. `PRD_v5_agent.md`
2. `interaction_design_v1.md`
3. `technical_architecture_v4.md`
4. `data_structure_design_v3.md`
5. `interface_hard_spec_v3.md`
6. `spec_audit_report_v2.md`

## 实现与使用补充文档

- 根目录 `README.md`：当前实现范围、验证状态、联调结论。
- `docs/USAGE_GUIDE.md`：面向使用者的启动、操作流程、常见问题与排障说明。该文档是使用说明，不是接口或 DTO 裁决来源。
- 根目录 `llm_config.json`：当前 M6 大模型调用配置文件，属于运行时配置，不属于接口或 DTO 规范文档。
- 后端 `backend/llm_tools`：当前实现已将文件树、教学状态和只读工具能力包装为 LLM 可消费的工具上下文；该实现细节以 `technical_architecture_v4.md`、`data_structure_design_v3.md` 和 `interface_hard_spec_v3.md` 的最新章节为准。

## 版本裁决

- `PRD_v1.txt` 到 `PRD_v4_agent.md` 仅作历史参考，产品口径以 `PRD_v5_agent.md` 为准。
- 架构口径以 `technical_architecture_v4.md` 为准；`technical_architecture_v3.md` 及更早版本仅保留为历史参考，不再作为当前实现依据。
- 数据结构口径以 `data_structure_design_v3.md` 为准，不得从 v1/v2 生成 enum 或 schema。
- 接口口径以 `interface_hard_spec_v3.md` 为准，不得从 v1/v2 生成路由、DTO 或 SSE 事件。
- 二次审计结论以 `spec_audit_report_v2.md` 为准；已补齐会话进度快照、`sub_status` 空值规则和 `POST /api/repo` 的同步/异步边界说明。
- 当前仓库的实现完成度与已落地功能说明，以根目录 `README.md` 为最新状态说明；接口、数据结构、交互和架构硬约束仍以上述规范文档为准。
- `docs/USAGE_GUIDE.md` 只补充使用方式、启动顺序和联调建议，不参与硬契约裁决。

## 冲突处理

如实现中发现文档冲突，不要在代码里发明第三套口径。先回改规范文档，再实现代码。

若冲突属于“当前代码是否已经完成/落地到什么程度”的状态描述，以 `README.md` 为准；若冲突属于接口、DTO、SSE、状态机或交互硬约束，仍以本文件列出的规范文档为准。

若冲突属于“用户该如何启动、使用、排障”的说明，以 `docs/USAGE_GUIDE.md` 为准；但该文档不得扩展或改写硬规范中的接口和数据契约。
