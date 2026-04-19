# Repo Tutor

Repo Tutor 是一个面向初学者的只读源码仓库教学 Agent。用户输入本地仓库绝对路径或 GitHub 公开仓库 URL，系统先做确定性仓库接入、文件树扫描与静态分析，再由 LLM 结合教学骨架、教学状态和安全只读工具上下文，生成首轮讲解与多轮追问回答。

当前主链路是 `backend/` + `web/`：

- `backend/` 是 FastAPI 后端、分析流水线、会话编排和 LLM 调用中心。
- `web/` 是正在使用的“阅读间”前端，纯静态 HTML + ES Modules，无需 Node 构建。
- `frontend/` 仍保留旧版 React/Vite 原型，但不是当前默认前端。
- `repo_tutor_tui/` 是可选的终端界面实验。

## 这个项目在解决什么问题

Repo Tutor 的目标不是把仓库当成问答素材库，而是把“读懂陌生工程”这件事拆成一条教学主线：

- 先帮用户建立观察框架：入口、模块、分层、依赖、主流程分别是什么。
- 再把这些框架映射到当前仓库里：哪些目录重要、哪些文件值得先看。
- 然后给出 3 到 6 步可执行阅读路径。
- 在多轮对话里持续围绕当前学习目标深入，而不是每轮都从零开始。

这套目标来自 `docs/PRD_v5_agent.md`，也是当前实现最值得被理解的产品核心。

## 当前实现的核心能力

- 只读仓库接入：支持本地仓库路径和 GitHub 公开仓库 URL。
- 安全边界：不执行目标仓库代码，不安装目标仓库依赖，不修改目标仓库文件；敏感文件默认只记录存在，不读取正文。
- 确定性分析链：M1-M4 基于规则和 Python 语义分析，输出项目画像、入口候选、模块摘要、分层、候选流程、阅读路径、未知项和告警。
- 教学状态编排：M5 维护学习目标、教学计划、学生覆盖度、教师工作日志和会话状态。
- LLM 回答生成：M6 负责首轮教学报告、多轮跟进回答、目标切换确认、阶段性总结等输出。
- 聊天阶段工具调用：后续问答支持安全工具调用，LLM 可以按需读取文件摘录、搜索文本、查询入口/模块/证据/阅读路径等结构化结果。
- 流式体验：分析进度和回答通过 SSE 推送，`web/` 前端逐步渲染。
- 前端插件机制：`web/plugins/` 支持在阅读间生命周期中挂接轻量插件。

## 当前架构总览

### 后端主线

1. `POST /api/repo` 创建会话，进入 `accessing`。
2. M1 处理路径校验或 GitHub clone。
3. M2 扫描文件树、忽略规则、语言统计、敏感文件策略。
4. M3 生成项目画像、入口候选、依赖分类、模块摘要、分层、候选流程、阅读路径和仓库知识库。
5. M4 组装首轮教学骨架和 topic slice。
6. M5 初始化教学状态，组织 SSE 事件和 Prompt 输入。
7. M6 生成首轮教学报告，状态切到 `chatting / waiting_user`。
8. 用户继续追问时，M5 再构建多轮 Prompt；M6 在需要时通过工具循环读取更多证据后回答。

### 当前运行中的前端

`web/` 是当前主前端，不走构建流程：

- `web/index.html`：阅读间壳子、三种视图模板、插件挂载点。
- `web/js/api.js`：HTTP + SSE 客户端。
- `web/js/state.js`：轻量状态仓库。
- `web/js/views.js`：输入页、分析页、聊天页渲染与交互。
- `web/js/plugins.js`：插件系统和事件总线。
- `web/plugins/`：前端插件示例与说明。

## 项目目录

```text
Irene/
├── backend/
│   ├── main.py                  # FastAPI 入口
│   ├── contracts/               # domain / dto / enums / sse 契约
│   ├── routes/                  # repo / session / analysis / chat 路由
│   ├── m1_repo_access/          # 仓库输入校验与接入
│   ├── m2_file_tree/            # 文件树扫描与安全过滤
│   ├── m3_analysis/             # 项目画像、入口、模块、分层、流程、阅读路径
│   ├── m4_skeleton/             # 教学骨架组装
│   ├── m5_session/              # 会话编排、状态机、教学状态、SSE 事件
│   ├── m6_response/             # Prompt、LLM 调用、回答解析、建议生成
│   ├── llm_tools/               # LLM 种子工具上下文构建
│   ├── agent_tools/             # 可调用工具注册表与工具实现
│   ├── agent_runtime/           # 工具循环、上下文预算、超时与降级
│   ├── repo_kb/                 # 仓库知识库查询接口
│   ├── security/                # 路径安全与敏感文件策略
│   └── tests/                   # pytest 测试
├── web/                         # 当前主前端，静态阅读间
├── frontend/                    # 旧版 React/Vite 原型，默认不参与当前联调
├── repo_tutor_tui/              # 可选终端界面
├── docs/                        # PRD、架构、接口与使用文档
├── scripts/                     # Windows 启动脚本
├── llm_config.example.json      # LLM 配置示例
├── llm_config.json              # 本地运行时配置
└── pyproject.toml               # Python 项目配置
```

## 快速开始

### 1. 准备环境

- Python 3.11+
- `git` 在 PATH 中可用（如果要分析 GitHub 公开仓库）
- 一个 OpenAI 兼容接口的模型服务

### 2. 配置 LLM

复制并编辑根目录 `llm_config.json`：

```json
{
  "api_key": "your_api_key",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "timeout_seconds": 60
}
```

也可以用环境变量覆盖：

- `REPO_TUTOR_LLM_API_KEY`
- `REPO_TUTOR_LLM_BASE_URL`
- `REPO_TUTOR_LLM_MODEL`
- `REPO_TUTOR_LLM_TIMEOUT_SECONDS`
- `REPO_TUTOR_LLM_MAX_TOKENS`

### 3. 安装后端依赖

推荐使用 `uv`：

```bash
uv sync --extra dev
```

如果你不用 `uv`，也可以：

```bash
python -m pip install -e ".[dev]"
```

### 4. 启动后端

```bash
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

或直接运行：

```bash
scripts\dev_backend.cmd
```

### 5. 启动当前前端

当前前端是 `web/`，不需要 `npm install`：

```bash
cd web
python -m http.server 5180 --bind 127.0.0.1
```

或直接运行：

```bash
scripts\dev_web.cmd
```

一键启动前后端：

```bash
scripts\dev_all.cmd
```

### 6. 使用

1. 打开 `http://127.0.0.1:5180`
2. 输入本地仓库绝对路径，或 `https://github.com/owner/repo`
3. 等待分析进度完成并阅读首轮报告
4. 继续提问，例如“入口在哪里”“启动流程怎么走”“只看数据库相关部分”

## API 概览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/repo/validate` | `POST` | 只做输入校验，不创建会话 |
| `/api/repo` | `POST` | 创建会话并启动分析，返回 `202` |
| `/api/session` | `GET` | 读取当前会话快照，用于刷新恢复 |
| `/api/session` | `DELETE` | 清理当前会话 |
| `/api/analysis/stream` | `GET` | 分析进度与首轮报告 SSE |
| `/api/chat` | `POST` | 提交用户消息，返回 `202` |
| `/api/chat/stream` | `GET` | 多轮回答 SSE |

所有 HTTP 响应都使用统一 envelope：

```json
{
  "ok": true,
  "session_id": "sess_xxx",
  "data": {}
}
```

## 当前实现里值得注意的几点

- 当前主前端不是 `frontend/`，而是 `web/`。
- 当前前端默认监听 `5180`，后端 CORS 同时兼容 `5173` 和 `5180`。
- 多轮聊天已经不是“只吃初始上下文”的一锤子回答，而是带工具循环的 Agent 式回答路径。
- `backend/m3_analysis` 不仅输出阅读报告所需材料，还会构建 `repo_kb`，供后续问答按主题检索。
- `backend/tests/test_tool_calling.py` 说明聊天阶段工具调用已经是当前实现的一部分，而不是计划能力。

## 测试

运行后端测试：

```bash
pytest -q -p no:cacheprovider
```

Windows 临时目录有权限问题时，可追加：

```bash
pytest -q --basetemp pytest_tmp -p no:cacheprovider
```

如果你有意维护旧版 React 原型，再额外检查：

```bash
cd frontend
npm install
npm run build
```

## 规范与说明文档

- 当前规范入口：`docs/CURRENT_SPEC.md`
- 当前产品 PRD：`docs/PRD_v5_agent.md`
- 使用说明：`docs/USAGE_GUIDE.md`
- TUI 说明：`docs/TUI_README.md`
- 前端插件说明：`web/plugins/README.md`

文档冲突时：

- 产品目标、接口与状态机硬约束，以 `docs/CURRENT_SPEC.md` 指向的规范为准。
- 当前代码实际落地范围、运行方式和目录现实，以本 `README.md` 为准。

## 补充说明

- `frontend/` 不是当前主前端，除非你明确要维护旧版 React 实现，否则优先看 `web/`。
- `repo_tutor_tui/` 可以单独运行，但不是本仓库当前默认交互入口。
- 如果你是后续维护这个仓库的 Agent，请继续看 `AGENT_README.md`。
