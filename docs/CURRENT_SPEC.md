# Repo Tutor — 当前规范入口

后续脚手架 Agent 必须以本文件列出的文档作为当前有效规范。

## 当前有效文档

1. `PRD_v5_agent.md`
2. `interaction_design_v1.md`
3. `technical_architecture_v3.md`
4. `data_structure_design_v3.md`
5. `interface_hard_spec_v3.md`
6. `spec_audit_report_v2.md`

## 版本裁决

- `PRD_v1.txt` 到 `PRD_v4_agent.md` 仅作历史参考，产品口径以 `PRD_v5_agent.md` 为准。
- 架构口径以 `technical_architecture_v3.md` 为准，不再使用 `technical_architecture_v1.md` 或 `technical_architecture_v2.md` 作为实现依据。
- 数据结构口径以 `data_structure_design_v3.md` 为准，不得从 v1/v2 生成 enum 或 schema。
- 接口口径以 `interface_hard_spec_v3.md` 为准，不得从 v1/v2 生成路由、DTO 或 SSE 事件。
- 二次审计结论以 `spec_audit_report_v2.md` 为准；已补齐会话进度快照、`sub_status` 空值规则和 `POST /api/repo` 的同步/异步边界说明。

## 冲突处理

如实现中发现文档冲突，不要在代码里发明第三套口径。先回改规范文档，再实现代码。
