# Working List Index

> 用途：面向后续 Agent 的非规范性工作索引。
> 这里记录待推进的教学能力设计，不直接裁决 DTO、SSE、状态机或接口契约。

---

## 索引

1. `teacher_working_log_and_teaching_state_v1.md`
   - 主题：教师工作日志、教学计划、学生学习状态表、状态更新器
   - 当前状态：draft
   - 目的：把 Repo Tutor 从“单轮结构化回答器”推进到“有持续教学状态的老师”

---

## 当前状态摘要

当前代码库已经具备：

- M4 提供可控教学骨架
- M5 维护基础会话状态、消息历史、学习目标、深浅级别
- M6 现在已经能基于骨架生成首轮教学正文和多轮回答
- prompt 已开始携带 `teacher_memory` 与 `teaching_plan` 风格的上下文

当前代码库仍然缺少：

- 显式、可持续更新的“教师 working log”
- 独立的“教学计划生成 + 教学计划更新”模块
- 独立的“学生学习状态预测 + 更新”模块
- 把以上状态稳定写回会话并参与后续回答的标准更新流程

---

## 阅读建议

如果后续 Agent 要继续推进“老师感”和“agent 感”，先读：

1. `teacher_working_log_and_teaching_state_v1.md`
2. `docs/technical_architecture_v3.md`
3. `docs/data_structure_design_v3.md`
4. `docs/interface_hard_spec_v3.md`
5. 根目录 `README.md`
