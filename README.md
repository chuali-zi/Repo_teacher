# Repo Tutor

Repo Tutor 是一个证据优先、只读的代码仓库教学助手。当前唯一有效的运行时组合是
`backend/` + `web_v3/`。

## 当前真相源

- 当前架构：`docs/current_architecture.md`
- 数据契约：`docs/data_contracts.md`
- 协议说明：`docs/protocols.md`

以上 3 份文档与当前代码一起构成维护基线。`new_docs/`、`web/`、`web_v2/` 仅视为历史
或草稿，不再作为当前实现依据。

## 当前运行时

- 后端：`backend/`，FastAPI + SSE
- 前端：`web_v3/`，静态 HTML + 浏览器端 React UMD/Babel
- 默认前端端口：`5181`
- 后端端口：`8000`
- 可见消息正文来自 `MessageDto.raw_text` 与 SSE `delta_text`
- `structured_content` 与 `initial_report_content` 仍然保留，用于结构化补充、证据引用和兼容

## 目录概览

- `backend/`：当前后端，包含路由、契约、会话编排、工具执行、安全规则和测试
- `web_v3/`：当前前端
- `docs/`：当前维护文档，仅保留架构、数据契约、协议三件套
- `scripts/`：Windows 启动脚本；`dev_web.cmd` / `dev_all.cmd` 默认启动 `web_v3`
- `new_docs/`：历史调研或草稿，不是 source of truth
- `web/`、`web_v2/`：废弃前端，默认不要参考

## 快速开始

### 1. 安装依赖

```bash
uv sync --extra dev
```

或：

```bash
python -m pip install -e ".[dev]"
```

### 2. 配置模型

在仓库根目录创建 `llm_config.json`：

```json
{
  "api_key": "your_api_key",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "timeout_seconds": 60
}
```

可选环境变量覆盖：

- `REPO_TUTOR_LLM_API_KEY`
- `REPO_TUTOR_LLM_BASE_URL`
- `REPO_TUTOR_LLM_MODEL`
- `REPO_TUTOR_LLM_TIMEOUT_SECONDS`
- `REPO_TUTOR_LLM_MAX_TOKENS`
- `REPO_TUTOR_MAX_TOOL_ROUNDS`
- `REPO_TUTOR_CHAT_TURN_TIMEOUT_SECONDS`

### 3. 启动后端

```bash
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

或：

```bash
scripts\dev_backend.cmd
```

### 4. 启动默认前端 `web_v3`

```bash
cd web_v3
python -m http.server 5181 --bind 127.0.0.1
```

或：

```bash
scripts\dev_web.cmd
scripts\dev_all.cmd
```

显式别名脚本仍可用：

```bash
scripts\dev_v3.cmd
```

### 5. 使用方式

1. 打开 `http://127.0.0.1:5181`
2. 提交本地仓库绝对路径或 `https://github.com/owner/repo`
3. 等待初始分析完成
4. 继续围绕源码证据提问

## 最小 API 概览

| Endpoint | Method | 用途 |
| --- | --- | --- |
| `/api/repo/validate` | `POST` | 仅校验输入 |
| `/api/repo` | `POST` | 创建会话并开始分析 |
| `/api/session` | `GET` | 返回当前会话快照 |
| `/api/session` | `DELETE` | 清除当前会话 |
| `/api/analysis/stream` | `GET` | 初始分析 SSE |
| `/api/chat` | `POST` | 提交追问 |
| `/api/chat/stream` | `GET` | 追问回答 SSE |
| `/api/sidecar/explain` | `POST` | 术语 sidecar 解释 |

## 测试

```bash
python -m pytest -q -p no:cacheprovider
```

如果 Windows 临时目录权限有噪音：

```bash
python -m pytest -q --basetemp pytest_tmp_run -p no:cacheprovider
```

## 维护约束

- 以后新增文档时，优先更新 `docs/` 三件套，而不是继续堆叠平行 spec。
- 如果代码与文档冲突，以当前 `backend/` 与 `web_v3/` 实现为准，再回写文档。
- 不要把 `web/`、`web_v2/`、`new_docs/` 当作当前产品事实来源。
