# Repo Tutor — Agent README

这份文档给后续 Agent、维护者和审阅者快速建立“当前代码现实”的心智模型。人类开发者如果只想知道项目是什么、怎么跑，先看 `README.md`。

## 先记住这几件事

1. 当前主运行链路是 `backend/` + `web/`，不是 `frontend/`。
2. `web/` 是静态阅读间前端，无构建步骤；`frontend/` 是旧版 React/Vite 原型。
3. 产品目标来自 `docs/PRD_v5_agent.md`：只读、教学型、单 Agent、围绕入口/模块/分层/依赖/主流程/阅读路径组织教学。
4. M1-M4 是确定性分析；M5 是唯一协调者；M6 负责 LLM 回答。
5. 多轮聊天阶段支持工具调用；首轮报告仍由预构建工具上下文驱动。

## 当前系统怎么跑

### 首次分析链路

```text
POST /api/repo
  -> routes/repo.py
  -> m5_session.session_service.create_repo_session()
  -> SSE /api/analysis/stream
  -> AnalysisWorkflow
  -> M1 -> M2 -> M3 -> M4
  -> TeachingService.build_initial_report_prompt_input()
  -> M6 生成首轮报告
  -> status = chatting / waiting_user
```

### 多轮对话链路

```text
POST /api/chat
  -> routes/chat.py
  -> m5_session.session_service.accept_chat_message()
  -> SSE /api/chat/stream
  -> ChatWorkflow
  -> TeachingService.build_prompt_input()
  -> 如 enable_tool_calls=True，则走 agent_runtime.tool_loop
  -> 调用 agent_tools / repo_kb / repository_tools
  -> M6 组织回答
  -> 更新 teaching_state / history_summary / suggestions
```

## 当前目录现实

### 你最该看的目录

| 路径 | 角色 |
|------|------|
| `backend/contracts/` | 当前后端契约源：domain、dto、enum、SSE 事件 |
| `backend/routes/` | API 入口层 |
| `backend/m1_repo_access/` | 仓库输入校验、GitHub clone、本地路径接入 |
| `backend/m2_file_tree/` | 文件树、语言统计、敏感文件策略、规模判断 |
| `backend/m3_analysis/` | 项目画像、入口、依赖、模块、分层、流程、阅读路径、repo KB |
| `backend/m4_skeleton/` | 首轮教学骨架与 topic index |
| `backend/m5_session/` | 会话生命周期、状态机、SSE、教学状态、工作流 |
| `backend/m6_response/` | Prompt、LLM 调用、解析、建议生成 |
| `backend/agent_tools/` | 工具定义、工具注册表、文件读取/搜索、分析查询工具 |
| `backend/agent_runtime/` | 工具循环、超时、降级、上下文预算 |
| `backend/repo_kb/` | 仓库知识库查询接口 |
| `web/` | 当前主前端：静态页面、状态、SSE、视图、插件 |

### 当前不应默认当成主链路的目录

| 路径 | 说明 |
|------|------|
| `frontend/` | 旧版 React/Vite 原型。除非用户明确让你维护它，否则不要把它当当前前端。 |
| `repo_tutor_tui/` | 可选 TUI。不是当前默认用户界面。 |

## 关键文件速查

| 文件 | 说明 |
|------|------|
| `backend/main.py` | FastAPI 入口，CORS 允许 `5173` 和 `5180` |
| `backend/routes/repo.py` | 仓库接入 API |
| `backend/routes/analysis.py` | 分析 SSE |
| `backend/routes/chat.py` | 聊天 API + SSE |
| `backend/routes/session.py` | 会话快照 / 清理 |
| `backend/m5_session/session_service.py` | 全局会话服务和入口编排 |
| `backend/m5_session/analysis_workflow.py` | 首次分析工作流 |
| `backend/m5_session/chat_workflow.py` | 多轮对话工作流 |
| `backend/m5_session/teaching_service.py` | 学习目标、深浅控制、PromptBuildInput 生成 |
| `backend/m5_session/teaching_state.py` | 教学计划、学生状态、教师日志演进 |
| `backend/llm_tools/context_builder.py` | LLM 种子工具上下文构建 |
| `backend/agent_runtime/tool_loop.py` | 多轮工具调用循环与超时/降级控制 |
| `backend/agent_tools/repository_tools.py` | `read_file_excerpt` / `search_text` |
| `backend/repo_kb/query_service.py` | repo surfaces / entries / modules / evidence / reading path |
| `backend/m6_response/llm_caller.py` | OpenAI 兼容接口调用与 `llm_config.json` 读取 |
| `web/index.html` | 当前阅读间壳子与模板 |
| `web/js/api.js` | HTTP + SSE 客户端 |
| `web/js/state.js` | 前端状态仓库 |
| `web/js/views.js` | 输入页、分析页、聊天页渲染 |
| `web/js/plugins.js` | 插件系统与事件总线 |

## 当前契约和状态机

### 后端状态

- `idle`
- `accessing`
- `analyzing`
- `chatting`
- `access_error`
- `analysis_error`

### 聊天子状态

- `waiting_user`
- `agent_thinking`
- `agent_streaming`

### 视图映射

- `idle / access_error / analysis_error -> input`
- `accessing / analyzing -> analysis`
- `chatting -> chat`

### 当前前端依赖的 SSE 事件名

- `status_changed`
- `analysis_progress`
- `degradation_notice`
- `agent_activity`
- `answer_stream_start`
- `answer_stream_delta`
- `answer_stream_end`
- `message_completed`
- `error`

这些名字一旦改动，至少要同时检查：

- `backend/contracts/dto.py`
- `backend/contracts/sse.py`
- `backend/m5_session/event_mapper.py`
- `web/js/api.js`
- `web/js/views.js`

## 当前工具调用现实

### 种子上下文

首轮报告和多轮对话都会先注入 `llm_tools` 生成的种子上下文，其中包含：

- 仓库上下文
- 文件树摘要
- 入口候选、模块摘要、分层、流程、阅读路径、证据、未知项
- 教学骨架 topic slice
- 当前教学状态快照

### 多轮对话中的可调用工具

聊天阶段的工具调用由 `backend/agent_runtime/tool_loop.py` 驱动，当前主要分两类：

- 仓库安全读取工具：`read_file_excerpt`、`search_text`
- 分析查询工具：入口候选、repo surfaces、模块图、阅读路径、证据等

关键事实：

- 工具调用只在 follow-up / goal switch / depth adjustment 场景开启。
- 工具调用有软超时、硬超时和降级继续回答逻辑。
- 工具执行结果会缓存。
- 敏感文件和不可读文件会被拒绝，返回结构化不可用结果而不是直接抛出原文。

## 当前前端现实

`web/` 不是占位目录，它就是现在跑起来的前端。

它的特点：

- 无框架、无打包、无 Node 运行时依赖。
- `python -m http.server 5180` 就能启动。
- 会话恢复依赖 `GET /api/session`。
- 分析期和聊天期分别连接不同 SSE 流。
- 有调试日志面板。
- 有插件系统和三个 plugin slot：`sidebar`、`header`、`thinking`。

如果你要改前端，不要先去 `frontend/src/`，先看：

- `web/index.html`
- `web/js/views.js`
- `web/js/state.js`
- `web/js/api.js`
- `web/css/main.css`

## 修改指引

### 如果你要改 API 或 DTO

优先检查：

- `backend/contracts/dto.py`
- `backend/contracts/enums.py`
- `backend/contracts/sse.py`
- `backend/routes/`
- `web/js/api.js`
- `web/js/views.js`
- 相关测试：`backend/tests/test_routes.py`、`backend/tests/test_m5_session.py`

### 如果你要改静态分析结果

优先检查：

- `backend/m3_analysis/`
- `backend/m4_skeleton/`
- `backend/repo_kb/query_service.py`
- `backend/tests/test_m3_analysis.py`
- `backend/tests/test_m4_skeleton.py`

### 如果你要改教学策略或对话行为

优先检查：

- `backend/m5_session/teaching_service.py`
- `backend/m5_session/teaching_state.py`
- `backend/m5_session/chat_workflow.py`
- `backend/m6_response/prompt_builder.py`
- `backend/tests/test_m5_session.py`
- `backend/tests/test_m6_response.py`

### 如果你要改工具调用

优先检查：

- `backend/agent_tools/`
- `backend/agent_runtime/tool_loop.py`
- `backend/m6_response/tool_executor.py`
- `backend/tests/test_tool_calling.py`
- `backend/tests/test_llm_tools.py`

### 如果你要改当前前端体验

优先检查：

- `web/index.html`
- `web/js/views.js`
- `web/js/plugins.js`
- `web/css/main.css`
- `web/plugins/README.md`

## 运行与测试

### 后端

```bash
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

或：

```bash
scripts\dev_backend.cmd
```

### 当前前端

```bash
cd web
python -m http.server 5180 --bind 127.0.0.1
```

或：

```bash
scripts\dev_web.cmd
scripts\dev_all.cmd
```

### 测试

```bash
pytest -q -p no:cacheprovider
```

和当前实现最相关的测试文件：

- `backend/tests/test_routes.py`
- `backend/tests/test_m5_session.py`
- `backend/tests/test_m6_response.py`
- `backend/tests/test_tool_calling.py`
- `backend/tests/test_llm_tools.py`

## 当前硬约束

1. M1-M4 不能调用 LLM。
2. M5 是唯一协调者，路由层不应直接编排 M1-M6 细节。
3. M6 不应直接读写完整 `SessionContext`，只消费 `PromptBuildInput`。
4. 敏感文件默认不读正文，不得把正文泄露到 SSE、日志或 Prompt。
5. 如果文档和代码冲突，硬约束先看 `docs/CURRENT_SPEC.md`，当前运行现实先看本文件和 `README.md`。
6. 除非用户明确要求，否则不要把 `frontend/` 当成当前前端来改。

## 最后一个判断准则

如果你只改了 `frontend/`，大概率没有改到用户现在真正看到的界面。
