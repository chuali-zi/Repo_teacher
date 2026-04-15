# Repo Tutor

面向初学者的 **只读** 源码仓库教学 Agent。输入一个本地仓库路径或公开 GitHub URL，自动完成静态分析并生成教学式阅读报告，然后通过多轮对话持续引导深入理解。

## 核心特性

- **确定性静态分析**：M1–M4 模块链式执行，基于 Python `ast` 和规则推断，不依赖 LLM，产出入口候选、模块识别、分层视图、候选流程、阅读路径等教学骨架。
- **LLM 驱动教学对话**：M6 通过 OpenAI 兼容接口（默认 DeepSeek）流式生成首轮教学报告和多轮追问回答，支持结构化六段式输出。
- **教学状态持续追踪**：M5 维护教学计划、学生学习状态、教师工作日志，每轮对话后更新，使回答连贯且有教学主线。
- **实时流式交互**：分析进度和 LLM 回答均通过 SSE 实时推送，前端逐字渲染。
- **安全只读**：不执行仓库代码、不安装依赖、不修改文件、敏感文件仅记录存在不读取正文。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11+, FastAPI, Uvicorn, Pydantic v2 |
| 前端 | React 18, TypeScript, Vite 5 |
| 通信 | HTTP REST + SSE |
| LLM | OpenAI 兼容接口（`openai` SDK），默认 DeepSeek |
| 静态分析 | Python 标准库 `ast` |
| Git | `git` CLI（GitHub shallow clone） |
| 存储 | 内存（单会话，无数据库） |

## 项目结构

```
Irene/
├── backend/
│   ├── main.py                    # FastAPI 应用入口
│   ├── contracts/                 # 共享数据模型：domain, dto, enums, sse
│   ├── routes/                    # HTTP 路由：repo, session, analysis, chat
│   ├── m1_repo_access/            # 输入校验、本地路径访问、GitHub 克隆
│   ├── m2_file_tree/              # 文件树扫描、过滤、语言检测、规模判定
│   ├── m3_analysis/               # 入口识别、import 分析、模块/分层/流程推断
│   ├── m4_skeleton/               # 教学骨架组装、主题索引、未知项汇总
│   ├── m5_session/                # 会话管理、状态机、SSE 事件映射、教学状态
│   ├── m6_response/               # Prompt 构建、LLM 调用、回答解析、建议生成
│   ├── security/                  # 敏感文件黑名单、路径越界检查
│   └── tests/                     # pytest 测试套件
├── frontend/
│   └── src/
│       ├── views/                 # RepoInputView, AnalysisProgressView, ChatView
│       ├── components/            # AgentMessage, ChatInput, MessageList 等
│       ├── hooks/                 # useSession, useSSE
│       ├── store/                 # sessionStore
│       ├── api/                   # HTTP + SSE 客户端
│       └── types/                 # TypeScript 类型契约
├── docs/                          # 产品、架构、数据结构、接口规范
├── scripts/                       # Windows 本地启动脚本
├── llm_config.json                # LLM 运行时配置（不入版本控制为佳）
└── pyproject.toml                 # Python 依赖与工具配置
```

## 快速开始

### 1. 配置 LLM

编辑根目录 `llm_config.json`：

```json
{
  "api_key": "your_key_here",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "timeout_seconds": 60
}
```

`api_key` 必填，其余字段可选（有默认值）。缺失或 `api_key` 为空时 M6 调用会报错。

### 2. 启动后端

```bash
uv sync --extra dev
uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

或使用 Windows 脚本：`scripts\dev_backend.cmd`

GitHub 仓库输入需要 `git` 在 PATH 中可用。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

或使用 Windows 脚本：`scripts\dev_frontend.cmd`

### 4. 使用

1. 浏览器打开 `http://127.0.0.1:5173`
2. 输入本地仓库绝对路径或公开 GitHub URL
3. 等待分析完成，阅读首轮教学报告
4. 继续追问或点击建议按钮深入

## API 概览

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/repo/validate` | POST | 仓库输入格式校验（不触碰文件系统） |
| `/api/repo` | POST | 创建会话并启动分析（返回 202） |
| `/api/session` | GET | 当前会话快照（页面刷新恢复） |
| `/api/session` | DELETE | 清理会话并释放资源 |
| `/api/analysis/stream` | GET | SSE 分析进度 + 首轮报告流 |
| `/api/chat` | POST | 提交用户消息（返回 202） |
| `/api/chat/stream` | GET | SSE 多轮回答流 |

所有 HTTP 响应使用统一 envelope（`{ ok, session_id, data|error }`）。

## 模块职责

| 模块 | 职责 | LLM |
|------|------|-----|
| M1 仓库接入 | 输入校验、路径/URL 解析、GitHub 克隆 | 否 |
| M2 文件树扫描 | 递归扫描、忽略/敏感过滤、语言检测、规模判定 | 否 |
| M3 静态分析 | 入口/import/模块/分层/流程/阅读路径/证据/项目画像 | 否 |
| M4 教学骨架 | 按 PRD 顺序组装首轮骨架、主题索引、未知项汇总 | 否 |
| M5 会话管理 | 唯一协调者，状态机、教学状态、SSE 事件映射 | 否 |
| M6 回答生成 | Prompt 构建、LLM 流式调用、结构化回答解析 | 是 |
| M7 前端 | React SPA，三视图，SSE 流式渲染 | 否 |

M5 是唯一协调者。路由调 M5，M5 调其他模块。M1–M4 确定性，M6 调 LLM。

## 测试

```bash
pytest -q -p no:cacheprovider
```

Windows 临时目录权限问题可加 `--basetemp pytest_tmp`。

前端构建验证：

```bash
cd frontend && npm run build
```

## 规范文档

规范入口：`docs/CURRENT_SPEC.md`。当前有效规范集：

1. `docs/PRD_v5_agent.md` — 产品需求
2. `docs/interaction_design_v1.md` — 交互设计
3. `docs/technical_architecture_v3.md` — 技术架构
4. `docs/data_structure_design_v3.md` — 数据结构
5. `docs/interface_hard_spec_v3.md` — 接口硬规范
6. `docs/spec_audit_report_v2.md` — 规范审计

文档冲突时：实现完成度以本 README 为准，硬约束以 `CURRENT_SPEC.md` 指向的规范为准。

## 实现状态

### 后端

- M1–M4 确定性分析流水线完整实现
- M5 会话编排：状态机、进度快照、SSE 事件映射、教学状态（教学计划/学生状态/教师日志）
- M6 LLM 集成：首轮报告 + 多轮对话均通过 M5→M6 路径调用 LLM，支持流式输出和结构化解析
- LLM 调用失败时返回 `llm_api_failed` / `llm_api_timeout`，不使用确定性 fallback

### 前端

- 三视图（输入/分析进度/聊天）完整实现
- 首轮报告按 `initial_report_content` 区块渲染，多轮回答按 `structured_content` 六段渲染
- SSE 流式渲染、会话恢复、建议按钮、禁用状态映射

### 运行时约束

- 单会话内存模型，无数据库
- M5 是唯一协调者，其他模块不直接修改 `ConversationState`
- 敏感文件仅记录存在，正文不进入分析/SSE/日志/Prompt
- 所有确定性结论必须有证据，不确定时使用候选措辞

## 实现规则

- `backend/contracts` 和 `frontend/src/types/contracts.ts` 是命名源
- 不添加规范外的路由名、消息类型、SSE 事件名、枚举值或状态转换
- M1–M4 不调 LLM；M6 不直接读写完整 `SessionContext`
- 前端视图状态来自服务端 DTO/SSE，不本地推断
