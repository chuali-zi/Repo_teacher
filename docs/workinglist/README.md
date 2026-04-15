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
- M5 维护教学计划、学生学习状态、教师工作日志、消息历史、学习目标、深浅级别
- `backend/llm_tools` 已把 M1-M4 拆成 LLM 可参考的只读工具目录和工具结果
- M6 现在基于工具上下文、教学状态和历史摘要生成首轮教学正文和多轮回答
- prompt 已携带 `teacher_memory`、`teaching_plan`、`student_learning_state`、`teacher_working_log` 和 `tool_context`

当前代码库仍然缺少：

- 前端对“工具参考来源/不确定性来源”的可视化入口
- 更完整的 LLM 动态工具调用循环；当前后端先以预组装工具上下文方式提供工具结果
- 更细粒度的文件级工具调用 UI 和调试视图

---

## 阅读建议

如果后续 Agent 要继续推进“老师感”和“agent 感”，先读：

1. `teacher_working_log_and_teaching_state_v1.md`
2. `docs/technical_architecture_v3.md`
3. `docs/data_structure_design_v3.md`
4. `docs/interface_hard_spec_v3.md`
5. 根目录 `README.md`
