# Repo Tutor — Agent 快速入门

> 本文档面向后续 Agent（编码、审计、迭代）快速了解项目全貌。人类开发者请看 `README.md`。

---

## 一句话定义

Repo Tutor 是一个 **本地单用户、只读、教学型** Web 应用。用户输入仓库路径/GitHub URL → 只读静态分析 → M1-M4 工具上下文 → LLM 生成教学报告 → 多轮对话持续深入。

## 技术栈速查

| 后端 | Python 3.11+, FastAPI, Uvicorn, Pydantic v2, openai SDK |
|------|---|
| 前端 | React 18, TypeScript, Vite 5 |
| 通信 | HTTP REST + SSE |
| LLM | OpenAI 兼容接口（默认 DeepSeek），配置在 `llm_config.json` |
| 存储 | 内存单会话，无数据库 |

## 核心架构：7 个模块 + 工具层

```
M7 (React SPA) ──HTTP/SSE──→ FastAPI 路由层 ──→ M5 (唯一协调者)
                                                    │
                              ┌──────────────────────┤
                              │                      │
                         M1→M2→M3→M4        LLM Tools        M6 (LLM)
                       (确定性分析链)     (只读工具上下文)  (回答生成)
```

| 模块 | 包路径 | 一句话职责 | 调 LLM |
|------|--------|-----------|--------|
| M1 | `backend/m1_repo_access/` | 输入校验、本地路径/GitHub clone | 否 |
| M2 | `backend/m2_file_tree/` | 文件树扫描、忽略/敏感过滤、语言/规模判定 | 否 |
| M3 | `backend/m3_analysis/` | 入口/import/模块/分层/流程/阅读路径 | 否 |
| M4 | `backend/m4_skeleton/` | 教学骨架组装、主题索引 | 否 |
| Tools | `backend/llm_tools/` | M1-M4 工具目录/工具结果、安全文件摘录、文本搜索 | 否 |
| M5 | `backend/m5_session/` | 会话编排、状态机、教学状态、SSE 映射、工具上下文组装 | 否 |
| M6 | `backend/m6_response/` | Prompt 构建、LLM 流式调用、结构化解析；静态分析只作参考 | **是** |
| M7 | `frontend/src/` | 三视图 SPA、SSE 流式渲染 | 否 |

**调用规则**：路由 → M5 → 其他模块。M5 是唯一协调者，其他模块不互相直接调用。

## 关键文件速查

| 文件 | 用途 |
|------|------|
| `backend/main.py` | FastAPI 应用入口，CORS 配置，路由注册 |
| `backend/contracts/domain.py` | 所有内部数据模型（Pydantic） |
| `backend/contracts/dto.py` | 外部 Wire DTO（API 响应/SSE 事件） |
| `backend/contracts/enums.py` | 全量枚举值 |
| `backend/contracts/sse.py` | SSE 事件类型定义 |
| `backend/routes/` | HTTP 路由（repo, session, analysis, chat） |
| `backend/m5_session/session_service.py` | 核心：会话生命周期、分析编排、聊天编排 |
| `backend/m5_session/state_machine.py` | 状态转换规则 |
| `backend/m5_session/teaching_state.py` | 教学计划/学生状态/教师日志管理 |
| `backend/llm_tools/context_builder.py` | LLM 工具目录、M1-M4 工具结果、安全文件摘录和搜索 |
| `backend/m6_response/prompt_builder.py` | LLM messages 列表组装 |
| `backend/m6_response/llm_caller.py` | LLM 调用（openai SDK / urllib fallback） |
| `backend/m6_response/response_parser.py` | LLM 返回的 JSON 解析 |
| `frontend/src/App.tsx` | 前端入口，视图切换 |
| `frontend/src/store/sessionStore.ts` | 客户端全局状态 |
| `frontend/src/types/contracts.ts` | 前端类型契约（与后端 DTO 对齐） |
| `llm_config.json` | LLM 运行时配置（api_key 必填） |
| `pyproject.toml` | Python 依赖 |
| `frontend/package.json` | Node 依赖 |

## API 端点

| 端点 | 方法 | 返回 | 说明 |
|------|------|------|------|
| `/api/repo/validate` | POST | 200 | 格式校验，不碰文件系统 |
| `/api/repo` | POST | 202 | 创建会话 + 启动分析 |
| `/api/session` | GET | 200 | 会话快照（刷新恢复） |
| `/api/session` | DELETE | 200 | 清理会话 |
| `/api/analysis/stream` | GET | SSE | 分析进度 + 首轮报告 |
| `/api/chat` | POST | 202 | 提交用户消息 |
| `/api/chat/stream` | GET | SSE | 多轮回答流 |

HTTP envelope: `{ ok: bool, session_id: string|null, data|error }`

## 状态机

```
idle ──→ accessing ──→ analyzing ──→ chatting
              │              │           │
              ▼              ▼           ▼
         access_error   analysis_error  idle (切仓)
```

`chatting` 子状态: `waiting_user` → `agent_thinking` → `agent_streaming` → `waiting_user`

视图映射: `idle/error → input`, `accessing/analyzing → analysis`, `chatting → chat`

## 数据流（首次分析）

```
POST /api/repo (202)
  → M5 创建 session, status=accessing
  → M1 校验 + clone → M2 扫描 + 过滤 → M3 静态分析 → M4 骨架组装
  → M5 初始化教学状态
  → M5 组装 LLM 工具上下文
  → M6 基于工具上下文 + 教学状态生成首轮报告
  → SSE: progress → delta → message_completed
  → status=chatting, sub_status=waiting_user
```

## 数据流（多轮对话）

```
POST /api/chat (202)
  → M5 记录用户消息, sub_status=agent_thinking
  → M5 生成教学决策 (teaching_state)
  → M5 构建 PromptBuildInput (工具上下文 + 教学上下文 + 历史摘要)
  → M6 LLM 流式调用 + 结构化解析
  → SSE: delta → stream_end → message_completed
  → M5 更新教学状态 (计划/学生/日志)
  → sub_status=waiting_user
```

## 教学状态系统

M5 维护以下教学状态（仅内部 + M6 prompt，不在外部 DTO 中暴露）：

| 对象 | 说明 |
|------|------|
| `TeachingPlanState` | 按 LearningGoal 排列的教学步骤，含完成状态 |
| `StudentLearningState` | 各主题覆盖度（unseen→introduced→partially_grasped→temporarily_stable） |
| `TeacherWorkingLog` | 当前教学目标、风险备注、最近决策、待解决问题 |
| `TeachingDecisionSnapshot` | 每轮开始前生成：推荐动作 + 理由 + 目标切片 |
| `TeachingDebugEvent` | 调试事件（上限 80 条） |

## 硬约束清单

1. **M5 唯一协调**：路由只调 M5，M5 调其他模块。
2. **M1–M4 不调 LLM**：确定性分析，基于规则和 AST。
3. **静态分析是工具参考**：M6 prompt 中的 M1-M4 结果来自 `llm_tools`，LLM 不应被静态分析限制；证据不足时允许推断但必须标注。
4. **M6 不读写 SessionContext**：只消费 `PromptBuildInput`。
5. **敏感文件只记录存在**：正文不进入分析/SSE/日志/Prompt。
6. **安全只读**：不执行代码、不安装依赖、不修改文件。
7. **前端服务端驱动**：视图状态来自 DTO/SSE，不本地推断。
8. **命名源**：`backend/contracts` + `frontend/src/types/contracts.ts`。
9. **不扩展规范**：不添加规范外的路由/消息类型/枚举值/状态转换。

## 规范文档导航

入口：`docs/CURRENT_SPEC.md`

| 文档 | 内容 |
|------|------|
| `PRD_v5_agent.md` | 产品需求：教学主线、功能列表、验收标准 |
| `interaction_design_v1.md` | 交互设计：三视图、输入输出规格、状态转换 |
| `technical_architecture_v3.md` | 技术架构：模块划分、运行流程、ADR |
| `data_structure_design_v3.md` | 数据结构：实体定义、枚举、生命周期 |
| `interface_hard_spec_v3.md` | 接口规范：HTTP/SSE 契约、Wire DTO、状态机 |
| `spec_audit_report_v2.md` | 审计报告：已修复的契约缺口 |

冲突裁决：实现完成度 → `README.md`；硬约束 → `CURRENT_SPEC.md` 指向的规范。

## 开发快速启动

```bash
# 后端
uv sync --extra dev
uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# 前端
cd frontend && npm install && npm run dev

# 测试
pytest -q -p no:cacheprovider

# 前端构建
cd frontend && npm run build
```

LLM 配置：编辑根目录 `llm_config.json`，`api_key` 必填。

## 常见修改场景

| 想做什么 | 改哪里 |
|---------|--------|
| 新增/修改 API 路由 | `backend/routes/` + `backend/contracts/dto.py` |
| 修改分析逻辑 | `backend/m3_analysis/` 对应子模块 |
| 修改 LLM prompt | `backend/m6_response/prompt_builder.py` |
| 修改教学状态逻辑 | `backend/m5_session/teaching_state.py` |
| 修改前端渲染 | `frontend/src/views/` 或 `frontend/src/components/` |
| 修改 SSE 事件 | `backend/m5_session/event_mapper.py` + `backend/contracts/sse.py` |
| 新增枚举值 | `backend/contracts/enums.py` + `frontend/src/types/contracts.ts` |
| 修改数据模型 | `backend/contracts/domain.py` |
