# Repo Teacher 新内核迁移建议

> 本文是 `new_kernel/` 的入口建议之一。它的目的不是再写一份完整设计，而是给“代码仓库型教学 agent”定一份**简单可开工**的迁移建议。
>
> 范围严格收敛到三件事：**agent 推理逻辑、tool 调用逻辑、prompt 组装逻辑**。其他全部让位。
>
> 心智模型：**一个老师带着学生学一个仓库**。
>
> 资料源：`C:\Users\chual\vibe\Irene\DeepTutor\` 内的实际代码；`new_docs/new_kernel/`、`new_docs/repo_teacher_reports_ascii/` 内的既有侦察与设计材料。

## 1. 一句话目标

```text
第一版只做一件事：
  用户问一个仓库相关的问题，
  agent 读最少必要代码，
  像老师一样讲清当前点 + 给一个下一个该看的点。
```

衡量标准：

- 一个 turn 跑通 `orient -> plan -> read -> teach`。
- 工具结果不直接进可见正文；只有 teacher 阶段输出用户文本。
- 第二轮提相邻问题时，agent 知道上一轮讲过什么。

不做：

- 不持久化（无任何数据库）。
- 不引入运行环境配置层（无 `.env` / `settings.py` / provider 工厂）。
- 不接 skill / MCP / 插件机制。
- 不接知识库 / 向量索引 / RAG / embedding。
- 不引入 shell / code execution / web search 工具。

## 2. 三大借鉴：从 DeepTutor 抽出可复用的通用 agent 逻辑

DeepTutor 里**值得借鉴**的不是它的能力数量，而是这三块**通用 agent 骨架**写得很干净：agent 推理、tool 调用、prompt 组装。

### 2.1 Agent 推理逻辑

#### 2.1.1 抽 BaseAgent 的最小子集

抄什么：

```text
统一的 LLM 调用接口：
  call_llm(user_prompt, system_prompt, ...)
  stream_llm(user_prompt, system_prompt, ...)

统一的 prompt 取值接口：
  get_prompt(section, field=None, fallback="")

抽象方法：
  process(*args, **kwargs)
```

参考位置：

- `DeepTutor/deeptutor/agents/base_agent.py:354-521`：`call_llm()`。
- `DeepTutor/deeptutor/agents/base_agent.py:523-694`：`stream_llm()`。
- `DeepTutor/deeptutor/agents/base_agent.py:700-747`：`get_prompt()`。
- `DeepTutor/deeptutor/agents/base_agent.py:770-777`：`process()` 抽象签名。

收敛掉：

```text
- token tracker
- 多 provider config
- agents.yaml 加载
- log_dir / Logger / display_manager
- multimodal attachments
- response_format 能力检测
```

repo teacher 的 `BaseAgent` 应当是约 80 行的极小类：构造函数直接持有 LLM client，`call_llm` / `stream_llm` 直接转发，`get_prompt` 从本地 yaml dict 查找。不读环境变量、不读复杂配置、不区分 provider。

#### 2.1.2 抽 Plan -> ReAct -> Write 三角色循环

DeepTutor 的 solve 模块用三个 agent 完成一次复杂解题，结构干净，直接对应仓库教学的“先想清楚要讲什么 -> 读源码 -> 讲清楚”。

对应关系：

```text
DeepTutor                 repo teacher          职责
PlannerAgent.process() -> OrientPlanner         把用户问题拆成 1-3 个读码 step
SolverAgent.process()  -> ReadingAgent          一轮 ReAct，决定调哪个工具读哪段
WriterAgent.process()  -> TeacherAgent          唯一可见正文出口，把 observation 消化成教学
```

参考位置：

- `DeepTutor/deeptutor/agents/solve/agents/planner_agent.py:60-129`
- `DeepTutor/deeptutor/agents/solve/agents/solver_agent.py:52-207`
- `DeepTutor/deeptutor/agents/solve/agents/writer_agent.py:52-105`
- `DeepTutor/deeptutor/agents/solve/main_solver.py:354-670`

收敛后形态：

```text
teaching_loop.run(user_message, scratchpad):
  1. orient_plan = OrientPlanner.process(user_message, scratchpad)
       # 一次 LLM 调用，输出小 reading_plan（最多 3 步）

  2. for step in orient_plan.steps:
       for round in range(MAX_READ_ROUNDS=3):
         decision = ReadingAgent.process(user_message, step, scratchpad)
         if decision.action == "done": break
         observation = tool_runtime.execute(decision.action, decision.action_input)
         scratchpad.add_entry(step.id, round, decision.thought, decision.action,
                              decision.action_input, observation, decision.self_note)

  3. final_text = await TeacherAgent.process(user_message, scratchpad,
                                             on_content_chunk=stream_to_caller)

  4. scratchpad.update_covered_points(final_text 中提到的 anchor)
```

和 DeepTutor 的差异：

```text
- 不实现 replan：仓库教学单轮短，第一版用不到。
- step.tools_hint 改为 step.anchors：[{path, range, why_to_read}]
- max_react_iterations = 3。
- max_steps = 3。
- safety_limit 不需要，步数本来就小。
```

### 2.2 Tool 调用逻辑

#### 2.2.1 抽 SolveToolRuntime 模式

DeepTutor 把“某个能力暴露哪些工具”抽成 `SolveToolRuntime`。第一版 repo teacher 直接照抄结构，但收窄权限。

抄什么：

```text
ToolRuntime 构造函数：
  接收 enabled_tools 列表
  对每个 tool 注册：
    - tool.name 入 valid_actions
    - tool aliases 入 valid_actions
    - 控制动作 done 入 valid_actions

ToolRuntime.execute(action, action_input, ctx):
  1. 用 action 找 tool
  2. 校验 tool 被允许
  3. 把 action_input 映射到工具参数
  4. 注入显式 ToolContext
  5. 调 tool.execute(ctx=ctx, ...)

两种 prompt 描述渲染：
  build_planner_description()
  build_reader_description()
```

参考位置：

- `DeepTutor/deeptutor/agents/solve/tool_runtime.py:44-219`
- `DeepTutor/deeptutor/core/tool_protocol.py:91-150`
- `DeepTutor/deeptutor/agents/solve/main_solver.py:676-775`

第一版只读工具：

```text
read_file_range(path, start_line, end_line)
search_repo(pattern, glob=None)
list_dir(path, recursive=False)
summarize_file(path)
find_references(symbol)
```

每个工具实现约 30-50 行：

```text
class ReadFileRange(BaseTool):
    def get_definition(self) -> ToolDefinition: ...

    async def execute(self, *, ctx: ToolContext, path, start_line, end_line) -> ToolResult:
        # 1. ctx.repo_root 拼绝对路径
        # 2. 越界检查：path 必须在 repo_root 下、不是敏感文件
        # 3. 截到 ctx.max_lines
        # 4. 返回 ToolResult(content=..., metadata={"path":..., "lines":...})
```

注意：repo teacher 的 `BaseTool.execute` **不再 `**kwargs`**，改成显式 `ctx: ToolContext` 参数 + 工具自有命名参数。kwargs 注入会让运行时上下文随处传播，难以追踪。

控制动作只保留：

```text
done - ReadingAgent 认为本 step 证据已经够。
```

不保留 `replan`，第一版无 planner 重入。

`ToolContext` 字段：

```text
repo_root        必填，所有路径越界检查的根
max_lines        默认 200，单次读上限
max_search_hits  默认 30，搜索结果上限
language         "zh" 默认
```

#### 2.2.2 工具结果回写规则

```text
- ToolResult.content 永远只进 scratchpad.entry.observation，不进可见正文。
- 可见正文唯一出口是 TeacherAgent。
- 工具失败写成 observation="Tool error (...): ..."，不让一次失败弄死整个 turn。
- 大输出截断后在 metadata 里标 {"truncated": true, "original_lines": N}。
```

### 2.3 Prompt 组装逻辑

#### 2.3.1 抽 PromptManager 极简模式

DeepTutor 把 prompts 按 `module/agent/lang/` 分层放 yaml，运行时通过 `get_prompt(section, field, fallback)` 三段查找。这套机制简单、可改 prompt。

抄什么：

```text
- prompts 目录布局：repo_teacher/prompts/zh/{orient,read,teach}.yaml
- 每个 yaml 内部至少有 system / user_template 两个 key
- get_prompt() 三段查找：
    get_prompt("system")
    get_prompt("section", "field")
    get_prompt("system", fallback="...")
- 模板缺失时降级为 inline 默认 prompt
```

`PromptManager` 第一版约 50 行：

```text
__init__(prompts_dir, language="zh")
get(agent_name, section, field=None, fallback="") -> str | None
```

不要远程 prompt store、watcher、多版本 prompt、A/B 路由。直接读本地文件夹。

#### 2.3.2 system + user_template 拼装范式

每个 agent 负责两段拼装：

```text
_build_system_prompt(self) -> str
_build_user_prompt(self, **ctx) -> str
```

OrientPlanner：

```text
system:
  你是仓库教学规划者。根据用户问题决定本轮要读哪些代码。
  输出严格 JSON：{plan: [{step_id, anchors: [{path, why}], goal}]}

user_template 注入：
  question
  repo_overview
  previous_covered
  tool_descriptions
```

ReadingAgent：

```text
system:
  你正在为某个 step 读最少代码。
  每轮输出严格 JSON：{thought, action, action_input, self_note}
  可用 action: {tools_description}
  读够即返回 done。

user_template 注入：
  question
  current_step
  step_history
  previous_steps
```

TeacherAgent：

```text
system:
  你是仓库老师。基于已读代码 observation 写自然教学回答。
  一次只讲一个核心点。
  源码引用最多 3 个 anchor。
  不要复述工具调用过程。
  结尾只给一个自然的下一教学点。
  证据不足就缩小说法，不要停止教学。

user_template 注入：
  question
  scratchpad_evidence
  previous_covered
  next_anchor_hint
```

#### 2.3.3 Scratchpad-driven context compression

DeepTutor 的 `Scratchpad` 不只是工作记忆，还是上下文压缩器。

repo teacher 的 `Scratchpad`：

```text
字段：
  question
  reading_plan
  read_entries
  covered_points
  metadata

方法：
  add_entry(...)
  get_entries_for_step(step_id)
  build_reading_context(step_id, max_tokens=4000)
  build_teacher_context(max_tokens=8000)
  to_dict() / from_dict()
```

跨轮记忆通过 `covered_points` dict 在 session 内传递。进程退出记忆消失，第一版不持久化。

#### 2.3.4 强制 JSON 输出的小技巧

OrientPlanner / ReadingAgent 使用 JSON 输出，再做容错解析。TeacherAgent 不要 JSON，它直接出自然语言可见正文。

## 3. 教学场景的最小映射

一个 turn 的形状：

```text
输入：user_message, scratchpad

orient + plan：
  输出 reading_plan，1-3 个 step，每个 step 带 anchors

read：
  每个 step 内 ReadingAgent 最多 3 轮
  每轮一个 tool 调用
  结果写 scratchpad.entries

teach：
  TeacherAgent 流式输出自然教学回答
  先答问题、解释设计意图、最多 3 个 anchor、结尾一个 next anchor

output：
  visible_text
  next_anchor
```

输出规则：

```text
1. ToolResult.content 永远不进 visible_text。
2. visible_text 来自且只来自 TeacherAgent。
3. 一轮回答最多 3 个 source anchor。
4. 结尾恰好一个 next anchor，不是菜单。
5. 没有源码 evidence 时缩小 claim，而不是停止教学。
```

## 4. 推荐文件骨架

第一版手写实现可放在用户决定的目录下，建议未来落到 `backend/repo_teacher/` 或类似位置。骨架：

```text
repo_teacher/
  base_agent.py        ~80 行
  orient_planner.py    ~100 行
  reading_agent.py     ~120 行
  teacher.py           ~100 行
  scratchpad.py        ~150 行
  prompt_manager.py    ~50 行
  tool_runtime.py      ~80 行
  repo_tools.py        ~250 行
  teaching_loop.py     ~100 行
  prompts/zh/
    orient.yaml
    read.yaml
    teach.yaml
```

总计约 1100 行手写代码即可跑通第一版。

绝对不要出现在骨架里的文件：

```text
event_store.py / sqlite_*.py / db_*.py
settings.py / config_loader.py / .env / provider_factory.py
skill_registry.py / mcp_*.py / plugin_*.py
vector_store.py / embedding_*.py / kb_*.py
shell_tool.py / code_executor.py / web_search.py
```

## 5. 不在范围

不抄：

```text
DeepTutor/deeptutor/runtime/orchestrator.py
DeepTutor/deeptutor/core/stream*.py
DeepTutor/deeptutor/core/capability_protocol.py
DeepTutor/deeptutor/core/stream_bus.py
DeepTutor/deeptutor/services/*
DeepTutor/deeptutor/services/llm/*
DeepTutor/deeptutor/services/rag/*
DeepTutor/deeptutor/knowledge/*
DeepTutor/deeptutor/tools/code_executor.py
DeepTutor/deeptutor/tutorbot/agent/tools/shell.py
DeepTutor/deeptutor/api/*
DeepTutor/deeptutor_cli/*
DeepTutor/deeptutor/agents/math_animator
DeepTutor/deeptutor/agents/research
DeepTutor/deeptutor/agents/visualize
DeepTutor/deeptutor/agents/notebook
DeepTutor/deeptutor/agents/co_writer
DeepTutor/deeptutor/agents/question
DeepTutor BaseAgent 内的 token tracker / log manager / display manager
```

第一版没有持久化，没有运行环境配置层，没有 skill 注册机制。

## 6. 怎么开工

### Step 1：抄一个 80 行 BaseAgent

```text
- 构造函数直接持有 LLM client
- call_llm / stream_llm 直接转发
- get_prompt 照 DeepTutor base_agent.py:700-747 抄
- process 抽象方法
```

### Step 2：抄一个 80 行 ToolRuntime + 5 个 repo 工具

```text
- enabled_tools / valid_actions / execute / build_planner_description
- 实现 5 个只读工具 + ToolContext
- 加路径越界检查与敏感文件拦截
```

### Step 3：抄一个 100 行 teaching_loop

```text
- OrientPlanner / ReadingAgent / TeacherAgent 三个子类
- Scratchpad 极简版
- teaching_loop.run(user_message, scratchpad)
- prompts/zh/{orient,read,teach}.yaml 各放一份初版
```

跑通验证：

```python
loop = TeachingLoop(repo_root=".../Irene")
scratchpad = Scratchpad(question="")
async for chunk in loop.run("讲讲 backend/main.py 是怎么 bootstrap 的", scratchpad):
    print(chunk, end="")
```

## 7. 验收

第一版 MVP 合格标准：

```text
1. 能跑通一个 turn：输出有 source anchor 的教学正文。
2. tool result 永不进可见正文。
3. prompts/zh/*.yaml 改一行 system 描述后，不重启不改代码即生效。
4. 第二轮提相邻问题时，agent 知道上一轮讲了什么。
```

不验收：

```text
- replay / 断点续传
- 多 session 隔离
- 多用户并发
- prompt 版本管理
- 教学质量自动打分
- 任何 web/CLI/UI 层
```

第一版只证明：**一个老师能带着学一个仓库代码**。

## 附：对应阅读顺序

```text
1. DeepTutor/deeptutor/agents/base_agent.py
2. DeepTutor/deeptutor/core/tool_protocol.py
3. DeepTutor/deeptutor/agents/solve/tool_runtime.py
4. DeepTutor/deeptutor/agents/solve/memory/scratchpad.py
5. DeepTutor/deeptutor/agents/solve/agents/planner_agent.py
6. DeepTutor/deeptutor/agents/solve/agents/solver_agent.py
7. DeepTutor/deeptutor/agents/solve/agents/writer_agent.py
8. DeepTutor/deeptutor/agents/solve/main_solver.py
```

