# Repo Tutor — Terminal UI (TUI) 使用说明

## 简介

TUI 是 Repo Tutor 的终端前端，提供纯文本一问一答体验。它直接在进程内调用后端 `SessionService`，不需要启动 FastAPI 服务器或 React 前端，适合以下场景：

- 快速验证后端分析和 LLM 对话功能
- 在没有 Node.js 环境时使用
- SSH 远程服务器上使用
- 调试后端问题时获取完整错误输出

## 前置条件

1. **Python 3.11+**
2. **依赖已安装**：`uv sync` 或 `pip install -e .`
3. **LLM 配置就绪**：根目录 `llm_config.json` 中 `api_key` 已填写
4. **GitHub 仓库输入**需要 `git` 在 PATH 中可用

## 启动方式

```bash
# 方式一：模块入口（推荐）
python -m repo_tutor_tui

# 方式二：通过 uv
uv run python -m repo_tutor_tui

# 方式三：兼容旧入口
python tui.py

# 方式四：Windows 脚本
scripts\dev_tui.cmd
```

启动后会看到欢迎界面，直接输入仓库路径或 GitHub URL 即可开始。

## 交互流程

### 第一步：输入仓库

```
仓库> C:\my\project
```

或

```
仓库> https://github.com/owner/repo
```

TUI 会立即校验格式，不合法时直接提示错误原因。校验通过后创建会话并进入分析。

### 第二步：等待分析

分析过程会逐步输出进度：

```
  ✓ 仓库接入  仓库访问验证完成
  ✓ 文件树扫描  文件树扫描完成
  ✓ 入口与模块分析  入口与模块分析完成
  ✓ 依赖来源分析  依赖来源分析完成
  ✓ 教学骨架组装  教学骨架组装完成
  ● 首轮报告生成  正在生成首轮教学报告...
```

首轮教学报告会流式逐字输出到终端。

如果触发降级（大仓库、非 Python 仓库），会显示：

```
  ⚠ 降级提示: 仓库较大，优先输出结构总览和阅读起点。 (类型: large_repo)
    原因: source_code_file_count > 3000
```

### 第三步：多轮对话

分析完成后进入对话模式，直接输入问题：

```
你> 入口在哪里？
你> 这个仓库怎么分层？
你> 只看依赖来源
你> 讲深一点
你> 总结一下
```

每次回答结束后会显示建议问题：

```
  💡 你可以继续问：
     1. 入口候选之间有什么区别？
     2. 主流程大致是怎么串起来的？
     3. 关键目录应该按什么顺序读？
```

## 内置命令

| 命令 | 作用 |
|------|------|
| `/help` | 显示帮助信息 |
| `/new` | 清除当前会话，重新输入仓库 |
| `/status` | 查看当前会话详细状态 |
| `/debug` | 查看最近 5 条教学调试事件 |
| `/quit` | 退出程序 |

### `/status` 输出示例

```
  session_id : sess_1a2b3c4d5e6f
  status     : chatting
  sub_status : waiting_user
  learning   : overview
  depth      : default
  stage      : initial_report
  repo       : my-project
  language   : Python
  size       : small
  files      : 42
  messages   : 3
  explained  : 5
```

### `/debug` 输出示例

```
  最近 5 条教学调试事件：
  [14:23:01] teaching_decision_built: 继续按计划推进入口讲解。
         decision_id: dec_a1b2c3
         selected_action: proceed_with_plan
  [14:23:05] teaching_plan_updated: 教学计划已根据本轮结果更新。
         current_step_id: step_003
  [14:23:05] student_state_updated: 学生学习状态表已根据本轮教学信号更新。
         topic_count: 8
```

## 错误输出

TUI 的核心设计原则是**所有失败原因都清楚输出**。错误信息包含三层：

```
  ✗ [error_code] 面向用户的错误消息
    | 内部详细信息（traceback 或底层原因）
    | ...
```

### 常见错误示例

**仓库路径不存在：**

```
  ✗ [local_path_not_found] 本地路径不存在：C:\nonexistent
    | Path does not exist
```

**LLM API Key 缺失：**

```
  ✗ [llm_api_failed] LLM 调用失败，请检查 llm_config.json 或稍后重试。
    | API key is missing or empty in llm_config.json
```

**LLM 调用超时：**

```
  ✗ [llm_api_timeout] LLM 调用超时，请稍后重试或缩小问题范围。
    | Request timed out after 60 seconds
```

**GitHub 仓库不可访问：**

```
  ✗ [github_repo_inaccessible] 该 GitHub 仓库不可公开访问
    | git clone --depth=1 failed with exit code 128
```

**分析过程异常：**

```
  ✗ [analysis_failed] 分析过程出错，请重试或尝试其他仓库
    | Traceback (most recent call last):
    |   File "backend/m3_analysis/entry_detector.py", line 42, in detect
    |     ...
```

## 与 Web 前端的区别

| | Web 前端 | TUI |
|---|---|---|
| 启动依赖 | FastAPI + React + Node.js | 仅 Python |
| 通信方式 | HTTP REST + SSE | 进程内直接调用 |
| 首轮报告 | 按区块结构化渲染 | 流式纯文本输出 |
| 多轮回答 | 六段式结构化卡片 | 流式纯文本输出 |
| 建议按钮 | 可点击 | 文本列表展示 |
| 错误展示 | 用户友好提示 | 完整错误码 + 内部详情 |
| 教学调试 | 不可见 | `/debug` 命令可查看 |

## 与其他前端共存

TUI 和 Web 前端各自独立。TUI 创建自己的 `SessionService` 实例，不影响通过 FastAPI 运行的 Web 前端。两者可以分别使用，但不能同时操作同一个仓库。

当前 TUI 代码已拆分为独立包 `repo_tutor_tui/`，便于后续继续优化页面表现、输入体验和渲染逻辑：

- `repo_tutor_tui/app.py`：主交互流程与状态循环
- `repo_tutor_tui/render.py`：终端输出与渲染辅助
- `repo_tutor_tui/constants.py`：文案与显示常量
- `repo_tutor_tui/__main__.py`：模块启动入口
- 根目录 `tui.py`：兼容旧启动方式的薄包装入口

## 排障

1. **`ModuleNotFoundError`**：确认在项目根目录运行，且已 `uv sync` 或 `pip install -e .`
2. **分析一直卡住**：检查 `llm_config.json` 中 `api_key` 是否有效
3. **GitHub clone 超时**：检查网络连接和 `git` 是否可用
4. **Windows 终端乱码**：确保终端使用 UTF-8 编码（`chcp 65001`）
5. **Ctrl+C 退出**：任何时候按 Ctrl+C 都可以安全退出
