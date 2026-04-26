# 当前架构

## 文档边界

- 当前唯一有效的实现基线是 `backend/` 与 `web_v3/`。
- 当前维护文档只有 3 份：`current_architecture.md`、`data_contracts.md`、
  `protocols.md`。
- `web/`、`web_v2/`、`new_docs/`、`repo_tutor_tui/` 仅视为废弃或草稿目录，不是
  source of truth。

## 系统总览

| 子系统 | 路径 | 当前职责 |
| --- | --- | --- |
| HTTP / SSE 入口 | `backend/routes/` | 提供 REST 端点与分析/聊天流式接口 |
| 契约层 | `backend/contracts/` | 统一定义枚举、运行态模型、DTO 与 SSE 编码 |
| 仓库接入 | `backend/m1_repo_access/` | 校验本地路径或公开 GitHub URL，并建立只读边界 |
| 文件树扫描 | `backend/m2_file_tree/` | 扫描仓库、应用 ignore / sensitive 规则、生成文件树快照 |
| 会话编排 | `backend/m5_session/` | 管理状态机、SSE 事件、教学状态、分析与聊天工作流 |
| 回答生成 | `backend/m6_response/` | 构建 prompt、调用 LLM、处理工具调用、解析回答 |
| 工具层 | `backend/agent_tools/` | 暴露只读仓库工具，如列文件、搜索文本、读取片段 |
| 工具运行时 | `backend/agent_runtime/` | 负责工具选择、上下文预算与 tool loop |
| 深度研究 | `backend/deep_research/` | 选择高价值源码文件并生成长报告型初始回答 |
| 当前前端 | `web_v3/` | 静态页面、REST 客户端、SSE 客户端、聊天与 sidecar UI |

## 后端分层

### 路由层

- `repo.py`：`POST /api/repo/validate` 与 `POST /api/repo`
- `session.py`：`GET /api/session` 与 `DELETE /api/session`
- `analysis.py`：`GET /api/analysis/stream`
- `chat.py`：`POST /api/chat` 与 `GET /api/chat/stream`
- `sidecar.py`：`POST /api/sidecar/explain`
- `_errors.py` 与 `_sse.py`：统一 HTTP 错误与 SSE 错误输出

### 核心编排层

- `SessionService` 是入口协调器，负责创建会话、接收聊天消息、读取快照、触发分析流和
  聊天流。
- `AnalysisWorkflow` 负责仓库接入、文件树扫描、教学状态初始化，以及初始报告生成。
- `ChatWorkflow` 负责后续追问回合、流式增量输出、结束态收口和错误处理。
- `RuntimeEventService`、`event_streams.py`、`event_mapper.py` 共同完成运行态事件到
  SSE DTO 的映射。

### 只读工具层

- 当前 live 工具面只有：
  `m1.get_repository_context`、`m2.get_file_tree_summary`、
  `m2.list_relevant_files`、`teaching.get_state_snapshot`、`search_text`、
  `read_file_excerpt`。
- 工具返回的是机械化事实，不应该返回“架构猜测”“推荐入口真相”“层次结论真相”。

## Quick Guide 链路

### 创建初始会话

1. `POST /api/repo` 调用 `SessionService.create_repo_session`
2. 只做输入校验与 `SessionContext` 初始化，不在这个请求里完成重分析
3. 返回 `202`，附带 `analysis_stream_url`
4. 前端随后连接 `GET /api/analysis/stream?session_id=...`

### 初始分析

1. `AnalysisWorkflow.run()` 先执行 `m1_repo_access.access_repository`
2. 成功后切换状态 `accessing -> analyzing`
3. `m2_file_tree.scan_repository_tree` 生成 `FileTreeSnapshot`
4. `TeachingService.initialize_teaching_state` 初始化教学状态
5. Quick guide 模式下进入 `m6_response` 初始报告生成
6. 生成完成后切换到 `chatting / waiting_user`

### Quick Guide 进度步骤

- `repo_access`
- `file_tree_scan`
- `initial_report_generation`

`entry_and_module_analysis`、`dependency_analysis`、`skeleton_assembly` 这些 step key
仍保留在枚举和前端标签中，但当前 live quick-guide 会话不会初始化或发出这些步骤；
它们也不代表旧版静态 `m3` / `m4` 子系统回归。

## Deep Research 链路

### 激活条件

- 只有当 `analysis_mode == deep_research` 且仓库主语言是 `Python` 时，才走深度研究链路。
- 非 Python 仓库会降级到 quick guide，并在状态里留下降级信息。

### 深度研究阶段

1. `build_research_run_state`
2. `build_research_packets`
3. `build_group_notes`
4. `build_synthesis_notes`
5. `build_initial_report_answer_from_research`

### Deep Research 进度步骤

- `repo_access`
- `file_tree_scan`
- `research_planning`
- `source_sweep`
- `chapter_synthesis`
- `final_report_write`

## 聊天链路

1. `POST /api/chat` 把用户消息写入 `ConversationState.messages`
2. 状态切到 `chatting / agent_thinking`
3. 前端连接 `GET /api/chat/stream?session_id=...`
4. `ChatWorkflow.run()` 构建 `PromptBuildInput`
5. 如果开启工具调用，则通过 `agent_runtime.tool_loop` 驱动只读工具
6. LLM 增量输出通过 `ANSWER_STREAM_DELTA` 发送
7. 最终解析为 `StructuredAnswer`，落盘为 `MessageRecord`
8. 状态切回 `chatting / waiting_user`

## web_v3 前端结构

| 路径 | 作用 |
| --- | --- |
| `web_v3/index.html` | 页面入口，加载 React UMD、Babel、CSS 与 JS |
| `web_v3/js/config.js` | API 基地址、阶段标签、视图映射 |
| `web_v3/js/services/api.js` | REST 请求与 SSE `EventSource` 封装 |
| `web_v3/js/app.js` | 应用主状态、事件路由、会话恢复、提交流程 |
| `web_v3/js/components.js` | 左中右面板、聊天线程、sidecar、调试面板 |
| `web_v3/js/main.js` | `ReactDOM.createRoot(...).render(<App />)` |

### 前端状态模型

- `view`：`input` / `analyzing` / `chatting`
- `status`：来自后端 `SessionStatus`
- `subStatus`：来自后端 `ConversationSubStatus`
- `messages`：主线程消息数组
- `analysisStream`：初始报告流式可见文本镜像
- `activeActivity` / `activeError` / `deepResearch`：右侧与调试面板辅助状态

### 可见文本来源

- 聊天主线程的正文来自 `raw_text`
- 流式增量来自 `answer_stream_delta.delta_text`
- `structured_content` 与 `initial_report_content` 不负责主正文拼接，但会被右侧面板用于
  `evidence_refs`、建议与结构化补充

## 当前明确不存在的旧路径依赖

- 没有 live `m3_analysis/`
- 没有 live `m4_skeleton/`
- 没有 live `repo_kb/`
- 没有以旧版 spec 文档为准的运行时入口
