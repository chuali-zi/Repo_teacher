# new_kernel INTERFACES — 实现层接缝定稿

## 0. 范围与权威

本文件是 `module_interaction_spec.md` 的**实现层补充**：仅冻结 spec 没有定的方法签名、字段名、dataclass 形状。

| 文件 | 决定什么 | 优先级 |
| --- | --- | --- |
| `web_v4_interface_protocol.md` | 前端可见 HTTP/SSE 字段 | 最高 |
| `contracts.py` | 上面两类的 pydantic 固化 | 高 |
| `module_interaction_spec.md` | 模块依赖方向、所有权、调用流程、状态写入 | 高 |
| `INTERFACES.md`（本文档） | 内部方法签名、字段名 | 中 |
| 各 .py 文件首行注释 + 实现 | 实现细节 | 实现层 |

**冲突时一律以 spec / contracts 为准**。本文档发现的偏移要先回到 spec 层修订。

已实现的模块（`contracts.py`、`llm/client.py`、`tools/tool_protocol.py`、`tools/safe_paths.py`、`prompts/prompt_manager.py`、`repo/*`）只在 §4 引用源码、不重述。codex 切片任务包必须在开工前阅读本文与 spec 中对应章节。

---

## 1. 跨模块协议

### 1.1 `EventSink` (Protocol)

位于 `events/__init__.py`（与 `EventBus` 同包，作为 protocol 暴露）。

```python
from typing import Protocol
from ..contracts import (
    AgentStatusEvent, RepoParseLogEvent, RepoConnectedEvent, TeachingCodeEvent,
    AnswerStreamStartEvent, AnswerStreamDeltaEvent, AnswerStreamEndEvent,
    MessageCompletedEvent, DeepResearchProgressEvent, RunCancelledEvent, ErrorEvent,
)

# 联合类型在 contracts 里叫 RepoTutorSseEvent
from ..contracts import RepoTutorSseEvent

class EventSink(Protocol):
    async def emit(self, event: RepoTutorSseEvent) -> None: ...
```

业务模块（agents、turn、deep_research、repo orchestrator、session 之外的所有 caller）只见这个 protocol；不直接持有 `EventBus`。

### 1.2 `EventBus`（具体实现，同时实现 `EventSink`）

位于 `events/event_bus.py`。per-session 异步事件队列，多消费者 fan-out。

```python
class EventBus:
    def __init__(self) -> None: ...

    async def emit(self, event: RepoTutorSseEvent) -> None:
        """publisher API；同时满足 EventSink protocol。"""

    def subscribe(self) -> AsyncIterator[RepoTutorSseEvent]:
        """每次调用返回一个独立 async generator，从订阅时刻起接收。SSE 流唯一进入点。"""

    async def close(self) -> None:
        """关闭所有订阅者；后续 emit 直接 drop。"""
```

实现要点：
- 内部 `set[asyncio.Queue]`，每个 `subscribe()` 创建一个 queue
- `emit` 用 `put_nowait` fan-out 到所有 queue（满时 drop 并 log warning，不抛）
- 不持久化、不重放过去事件、不跨 session

### 1.3 `EventFactory`（无状态工厂函数集）

位于 `events/event_factory.py`。所有公开函数都是纯函数，**不持有任何状态**。

```python
# helpers
def make_event_id() -> str: ...        # uuid4 hex
def now_utc() -> datetime: ...         # timezone-aware UTC

# event constructors（每个对应一种 contracts.SseEventType）
def agent_status_event(*, session_id: str, status: AgentStatus) -> AgentStatusEvent: ...
def repo_parse_log_event(*, session_id: str, log: ParseLogLine) -> RepoParseLogEvent: ...
def repo_connected_event(
    *, session_id: str, repository: RepositorySummary,
    initial_message: str, current_code: TeachingCodeSnippet | None = None,
) -> RepoConnectedEvent: ...
def teaching_code_event(*, session_id: str, snippet: TeachingCodeSnippet) -> TeachingCodeEvent: ...
def answer_stream_start_event(
    *, session_id: str, turn_id: str, message_id: str, mode: ChatMode,
) -> AnswerStreamStartEvent: ...
def answer_stream_delta_event(
    *, session_id: str, turn_id: str, message_id: str, delta_text: str,
) -> AnswerStreamDeltaEvent: ...
def answer_stream_end_event(
    *, session_id: str, turn_id: str, message_id: str,
) -> AnswerStreamEndEvent: ...
def message_completed_event(
    *, session_id: str, message: ChatMessage,
    agent_status: AgentStatus | None = None,
    current_code: TeachingCodeSnippet | None = None,
) -> MessageCompletedEvent: ...
def deep_research_progress_event(
    *, session_id: str, turn_id: str, phase: str, summary: str,
    completed_units: int = 0, total_units: int = 0, current_target: str | None = None,
) -> DeepResearchProgressEvent: ...
def run_cancelled_event(
    *, session_id: str, agent_status: AgentStatus, turn_id: str | None = None,
) -> RunCancelledEvent: ...
def error_event(
    *, session_id: str, error: ApiError, agent_status: AgentStatus | None = None,
) -> ErrorEvent: ...
```

每个工厂自动填 `event_id` + `occurred_at`，调用方只传业务字段。**所有 SSE 事件构造必须经此工厂**（spec §9）。

### 1.4 `AgentStatusTracker`

位于 `events/agent_status_tracker.py`。维护单 session 当前 `AgentStatus`，状态变化时通过 `sink` 广播。

```python
class AgentStatusTracker:
    def __init__(
        self,
        *,
        session_id: str,
        sink: EventSink,                         # 注入；不持 EventBus
        initial_status: AgentStatus | None = None,
    ) -> None:
        """initial_status 为空时构造 idle 默认状态。"""

    @property
    def current(self) -> AgentStatus: ...

    async def update_phase(
        self,
        *,
        state: AgentPetState,
        phase: AgentPhase,
        label: str,
        pet_mood: Literal["idle","think","act","scan","teach","research","error"],
        pet_message: str,
        current_action: str | None = None,
        current_target: str | None = None,
        emit: bool = True,
    ) -> AgentStatus:
        """更新阶段类字段；emit=True 时通过 sink 广播 AgentStatusEvent。"""

    async def add_metrics(
        self,
        *,
        llm_call: int = 0,
        tool_call: int = 0,
        tokens: int = 0,
        elapsed_ms: int = 0,
        emit: bool = False,
    ) -> AgentStatus:
        """累加 metrics；默认 emit=False 避免每次都广播。"""
```

调用约定：
- 进入新阶段时 `update_phase(emit=True)`
- 工具调用前后 `add_metrics(emit=False)`
- turn 终态再 `update_phase(emit=True)` 表态（teaching → idle / error / cancelled）

### 1.5 `CancellationToken`

位于 `turn/cancellation.py`。协作式取消信号。

```python
class CancelledError(Exception):
    def __init__(self, reason: str) -> None: ...

@dataclass
class CancellationToken:
    session_id: str
    turn_id: str

    _cancelled: bool = field(default=False, init=False)
    _reason: str | None = field(default=None, init=False)

    def cancel(self, reason: Literal["user_escape","new_repo","manual"]) -> None: ...

    @property
    def is_cancelled(self) -> bool: ...

    @property
    def reason(self) -> str | None: ...

    def raise_if_cancelled(self) -> None:
        """检查点：若已取消，抛 CancelledError(reason)。"""
```

`TeachingLoop` / `DeepResearchLoop` 必须在 orient / 每个 step 起点 / teach 前 / 每 N 个 stream chunk 调一次 `raise_if_cancelled()`。

---

## 2. 数据结构

### 2.1 `Anchor` / `ReadingStep`

位于 `memory/scratchpad.py`。

```python
@dataclass(frozen=True)
class Anchor:
    path: str
    why: str

@dataclass(frozen=True)
class ReadingStep:
    step_id: str                    # "step_1" / "step_2" 等
    goal: str                       # 自然语言：本 step 要弄清什么
    anchors: tuple[Anchor, ...]
```

### 2.2 `ReadEntry`

```python
@dataclass(frozen=True)
class ReadEntry:
    step_id: str
    round_index: int                # 0-based ReAct 轮次
    thought: str
    action: str                     # tool name 或 "done"
    action_input: dict[str, Any]
    observation: str                # ToolResult.content（可被截断）
    self_note: str
    tool_success: bool
```

### 2.3 `Scratchpad`

```python
@dataclass
class Scratchpad:
    question: str = ""
    reading_plan: list[ReadingStep] = field(default_factory=list)
    read_entries: list[ReadEntry] = field(default_factory=list)
    covered_points: dict[str, str] = field(default_factory=dict)   # point_id -> 简要描述
    metadata: dict[str, Any] = field(default_factory=dict)

    # ----- per-turn 重置 -----
    def reset_for_turn(self, question: str) -> None:
        """清空 reading_plan + read_entries；保留 covered_points（跨轮记忆）。"""

    # ----- 写入 -----
    def set_plan(self, plan: list[ReadingStep]) -> None: ...
    def add_entry(self, entry: ReadEntry) -> None: ...
    def update_covered_points(self, point_id: str, summary: str) -> None: ...

    # ----- 读 -----
    def get_entries_for_step(self, step_id: str) -> list[ReadEntry]: ...

    # ----- 上下文压缩 -----
    def build_reading_context(
        self, *, current_step_id: str, max_tokens: int = 4000,
    ) -> str:
        """给 ReadingAgent 用：plan 摘要 + current_step + step_history（按预算）+ previous self_notes。"""

    def build_teacher_context(self, *, max_tokens: int = 8000) -> str:
        """给 TeacherAgent 用：完整 step + observation；超预算时早期 step 仅保留 self_note。"""

    # ----- 序列化（in-memory，用于 snapshot） -----
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Scratchpad": ...
```

### 2.4 `SessionState`

位于 `session/session_state.py`。**所有字段写入权限严格按 spec §8 owner 表**。

```python
@dataclass
class SessionState:
    # --- 必填，构造时由 SessionStore.create() 注入 ---
    session_id: str
    event_bus: "EventBus"                                    # session 唯一 bus
    agent_status: AgentStatus                                # 初始为 idle 状态

    # --- 可选/默认 ---
    mode: ChatMode = ChatMode.CHAT

    repository: RepositorySummary | None = None              # owner: repo orchestrator
    repo_root: Path | None = None                            # owner: repo orchestrator (clone 完后写)

    parse_log: list[ParseLogLine] = field(default_factory=list)             # owner: repo orchestrator
    messages: list[ChatMessage] = field(default_factory=list)               # owner: TurnRuntime
    scratchpad: Scratchpad = field(default_factory=Scratchpad)              # owner: TeachingLoop/DeepResearchLoop
    current_code: TeachingCodeSnippet | None = None                         # owner: repo orchestrator / TeachingLoop

    active_turn_id: str | None = None                        # owner: TurnRuntime（**仅它写**）

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

注意 `event_bus` 直接挂在 state 上是为了让 `api/routes/repositories.py` 与 `api/routes/chat.py` 在 SSE 路由里直接 `state.event_bus.subscribe()`。**只有 EventBus 本身可以被持有**，业务模块拿到的仍是 `EventSink` 形态的窄接口（spec §5 events）。

---

## 3. 业务模块接口

### 3.1 `SessionStore`

位于 `session/session_store.py`。

```python
class SessionStore:
    def __init__(
        self,
        *,
        event_bus_factory: Callable[[], "EventBus"],
        idle_status_factory: Callable[[str], AgentStatus],   # 输入 session_id 返回 idle AgentStatus
    ) -> None: ...

    def create(
        self,
        *,
        session_id: str | None = None,                       # None 时内部生成 "sess_<hex>"
        mode: ChatMode = ChatMode.CHAT,
    ) -> SessionState: ...

    def get(self, session_id: str) -> SessionState:
        """不存在抛 KeyError。route 层捕获后转 ApiError(SESSION_NOT_FOUND)。"""

    def drop(self, session_id: str) -> None: ...

    def __contains__(self, session_id: str) -> bool: ...
```

### 3.2 `build_snapshot`

位于 `session/snapshot.py`。**纯函数**，不修改 state。

```python
def build_snapshot(state: SessionState) -> SessionSnapshotData: ...
```

### 3.3 `ToolRuntime`

位于 `tools/tool_runtime.py`。

```python
class ToolRuntime:
    def __init__(
        self,
        tools: list[BaseTool],
        *,
        control_actions: tuple[str, ...] = ("done",),
    ) -> None: ...

    @property
    def valid_actions(self) -> frozenset[str]:
        """所有工具 name + 控制动作的并集。
        ReadingAgent 输出的 action 必须落在这里；不在则 TeachingLoop 强制降级为 done（fail-closed）。"""

    @property
    def tools(self) -> tuple[BaseTool, ...]: ...

    async def execute(
        self,
        action: str,
        action_input: dict[str, Any],
        *,
        ctx: ToolContext,
    ) -> ToolResult:
        """
        - action 是控制动作（如 "done"）：ValueError（控制动作由 TeachingLoop 处理，不该到这里）。
        - action 不在 valid_actions：ToolResult.fail(error_code='invalid_action')。
        - 工具 execute 抛异常：catch 并转 ToolResult.fail，不让单次失败终止 turn（spec §5 tools）。
        """

    def build_planner_description(self) -> str:
        """给 OrientPlanner 的 user_template 用。Markdown 列表式。"""

    def build_reader_description(self) -> str:
        """给 ReadingAgent 的 system prompt 用。表格式 + 用法说明。"""
```

### 3.4 `BaseAgent`

位于 `agents/base_agent.py`。

```python
class BaseAgent(ABC):
    agent_name: str

    def __init__(
        self,
        *,
        agent_name: str,
        llm_client: LLMClient,
        prompt_manager: PromptManager,
    ) -> None: ...

    async def call_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,    # OpenAI 接受 {"type": "json_object"}
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str: ...

    async def stream_llm(
        self,
        user_prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...

    def get_prompt(
        self,
        section: str,
        field: str | None = None,
        fallback: str = "",
    ) -> str:
        """转发 PromptManager.get(self.agent_name, section, field, fallback)。"""

    @abstractmethod
    async def process(self, *args: Any, **kwargs: Any) -> Any: ...
```

### 3.5 `OrientPlanner.process`

位于 `agents/orient_planner.py`。

```python
@dataclass(frozen=True)
class OrientPlan:
    steps: tuple[ReadingStep, ...]                         # 1-3 步

class OrientPlanner(BaseAgent):
    async def process(
        self,
        *,
        question: str,
        repo_overview: str,
        previous_covered: dict[str, str],
        tool_descriptions: str,                            # ToolRuntime.build_planner_description()
    ) -> OrientPlan:
        """
        一次 LLM 调用，response_format={"type": "json_object"}，容错解析；
        解析失败降级为单步 fallback plan（仅含 step_1 + 单 anchor "src/")，不抛。
        """
```

### 3.6 `ReadingAgent.process`

位于 `agents/reading_agent.py`。

```python
@dataclass(frozen=True)
class ReadingDecision:
    thought: str
    action: str                                            # tool name 或 "done"
    action_input: dict[str, Any]
    self_note: str

class ReadingAgent(BaseAgent):
    async def process(
        self,
        *,
        question: str,
        current_step: ReadingStep,
        step_history: list[ReadEntry],                     # 当前 step 已有 entries
        previous_steps_summary: str,                       # 之前 step 的 self_note 拼接
        valid_actions: frozenset[str],                     # 来自 ToolRuntime
        tool_descriptions: str,                            # ToolRuntime.build_reader_description()
    ) -> ReadingDecision:
        """
        严格 JSON 输出；action 不在 valid_actions 内时降级为 ReadingDecision(action='done')。
        ReadingAgent 不直接执行工具（spec §5 agents、§10 工具链路）。
        """
```

### 3.7 `TeacherAgent.process`

位于 `agents/teacher.py`。

```python
@dataclass(frozen=True)
class TeacherOutput:
    full_text: str
    suggestions: list[str] = field(default_factory=list)   # 结尾的"接下来"，最多 1 个
    next_anchor: Anchor | None = None

class TeacherAgent(BaseAgent):
    async def process(
        self,
        *,
        question: str,
        scratchpad: Scratchpad,                            # 内部调 build_teacher_context
        previous_covered: dict[str, str],
        next_anchor_hint: Anchor | None = None,            # orient 给的方向，可选
        on_chunk: Callable[[str], Awaitable[None]],        # 每段文本 await 一次（emit answer_stream_delta）
    ) -> TeacherOutput:
        """流式正文；不输出 JSON；硬约束见 spec §11、agents/teacher.py 首行注释。"""
```

### 3.8 `SidecarExplainer.process`

位于 `agents/sidecar_explainer.py`。

```python
class SidecarExplainer(BaseAgent):
    async def process(
        self,
        *,
        term: str,
        current_repo: str | None = None,
        current_file: str | None = None,
    ) -> SidecarExplainData:                               # 直接返回 contracts 类型
        """单次 LLM 调用；不写 messages / scratchpad / agent_status / active_turn_id（spec §6 sidecar）。"""
```

### 3.9 `TeachingLoop.run`

位于 `agents/teaching_loop.py`。

```python
class TeachingLoop:
    def __init__(
        self,
        *,
        orient: OrientPlanner,
        reader: ReadingAgent,
        teacher: TeacherAgent,
        tool_runtime: ToolRuntime,
        max_steps: int = 3,
        max_react_iterations: int = 3,
    ) -> None: ...

    async def run(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_message: str,
        scratchpad: Scratchpad,                            # 调用方持有；run 写入但不替换实例
        repo_overview: str,
        repo_root: Path,
        sink: EventSink,                                   # 仅广播；不广播 ChatMessage 完成事件（那是 TurnRuntime 的职责）
        status_tracker: AgentStatusTracker,
        cancellation_token: CancellationToken,
    ) -> ChatMessage:
        """
        执行 orient → per-step ReAct ≤ max_react_iterations → teach；
        - 每个阶段先 status_tracker.update_phase(emit=True) 再做事
        - 工具失败转 observation 写入 scratchpad，不终止 turn
        - 流式 token 经 on_chunk 转成 answer_stream_delta，由本方法构造并 sink.emit
        - 返回最终 ChatMessage（不含 message_completed 事件，由 TurnRuntime 发）
        """
```

### 3.10 `DeepResearchLoop.run`

位于 `deep_research/deep_research_loop.py`。**签名与 `TeachingLoop.run` 一致**，差异仅在内部：

- 默认 `max_steps`、`max_react_iterations` 更高
- 阶段间通过 `sink.emit(deep_research_progress_event(...))` 上报进度
- 最终可见正文仍由 `TeacherAgent` 出（spec §5 deep_research）

### 3.11 `TurnRuntime`

位于 `turn/turn_runtime.py`。**单 session 单 active turn 互斥**由它独占负责（spec §5 turn）。

```python
class TurnRuntime:
    def __init__(
        self,
        *,
        teaching_loop: TeachingLoop,
        deep_loop: DeepResearchLoop,
        idle_status_factory: Callable[[str], AgentStatus],     # 终态恢复 idle 用
    ) -> None: ...
        # 内部维护 dict[session_id -> CancellationToken]

    async def start_turn(
        self,
        *,
        state: SessionState,
        request: SendTeachingMessageRequest,
    ) -> SendTeachingMessageData:
        """
        校验 state.active_turn_id 必须为 None，否则抛 InvalidStateError -> route 转 ApiError(INVALID_STATE)。
        步骤：
          1. 生成 turn_id / 创建 CancellationToken / 注册到内部 registry
          2. 写 state.active_turn_id；追加 user ChatMessage 到 state.messages
          3. 启动 asyncio.create_task(_run_turn(...))，把 teaching_loop 或 deep_loop 跑起来
          4. 同步返回 SendTeachingMessageData(accepted=True, turn_id=..., chat_stream_url=..., agent_status=current)
        _run_turn 终态：
          - 成功：emit MessageCompletedEvent
          - 异常：emit ErrorEvent；status -> error
          - 取消：emit RunCancelledEvent；status -> idle/cancelled
          - finally：清 state.active_turn_id；从 registry 删除 token
        """

    async def cancel(
        self,
        *,
        state: SessionState,
        reason: Literal["user_escape","new_repo","manual"],
    ) -> CancelRunData:
        """
        从 registry 找当前 token：
          - 没有：返回 CancelRunData(cancelled=False, ...)（idempotent）
          - 有：token.cancel(reason)，等待 _run_turn 自然走 finally
        不抢先清 active_turn_id（避免重复），由 _run_turn finally 清。
        """
```

### 3.12 `summarize_file` 注入约定

位于 `tools/summarize_file.py`。

```python
SummarizerCallable = Callable[[str], Awaitable[str]]

class SummarizeFile(BaseTool):
    def __init__(self, summarizer: SummarizerCallable) -> None: ...

    def get_definition(self) -> ToolDefinition: ...

    async def execute(self, *, ctx: ToolContext, path: str) -> ToolResult: ...
```

约束（spec §5 tools 修订后版本）：
- `summarizer` 通过**构造参数**注入，**不能**放进 `ToolContext`（值对象不可变）
- 模块**不**`import llm.client` 或 `BaseAgent`
- 注入由组合根（`api/app.py`）完成：拿 `LLMClient` 包成 `summarizer` 后传进 `SummarizeFile`

---

## 4. 已固化模块（仅引用，不重写）

| 模块 | 公开 API | 备注 |
| --- | --- | --- |
| `contracts.py` | 全部 pydantic 类型 + `HTTP_ENDPOINTS` + `STREAM_EVENT_NAMES` + `RepoTutorSseEvent` | 所有公开 schema 的唯一来源 |
| `llm/client.py` | `LLMClient`, `make_client`, `LLMCallResult`, `LLMClientError` 系列 | 已带 OpenAI 异常映射 |
| `tools/tool_protocol.py` | `BaseTool`, `ToolContext`, `ToolDefinition`, `ToolParameter`, `ToolResult`, `ToolPromptHints`, `ToolRuntimeProtocol` | `ToolResult.from_text_with_limit` 直接用于截断 |
| `tools/safe_paths.py` | `resolve_under_root`, `is_sensitive_file`, `MAX_FILE_SIZE_BYTES` | 5 个工具 + repo 共用 |
| `prompts/prompt_manager.py` | `PromptManager` | 三段查找 + `zh→en` 语言回退 + `default.yaml` 合并 |
| `repo/__init__.py` | `GithubResolver`, `GitCloner`, `TreeScanner`, `OverviewBuilder`, `TeachingSlicePicker`, `RepoParsePipeline`, `RepoModuleError` 等 | 真实签名以代码为准；`RepoParsePipeline.run` 接 3 个独立 sink (status_sink / log_sink / connected_sink) |

实现时**不要在 codex 切片里重新发明这些类**，import 即可。

---

## 5. codex 切片任务包必读章节映射

每个切片在分发任务包时强制引用以下章节：

| 切片 | 必读 spec | 必读 INTERFACES | 必读 contracts |
| --- | --- | --- | --- |
| slice-1 tools | §5 tools, §10 工具链路 | §3.3, §3.12, §4 | `ToolContext`, `ToolResult`, `ToolDefinition` |
| slice-2 memory | §5 memory, §10 工具链路 | §2.1, §2.2, §2.3 | 无 |
| slice-3 events | §5 events, §9 事件规则 | §1.1, §1.2, §1.3, §1.4 | 全部 SseEvent 子类、`AgentStatus` |
| slice-4 turn-token | §5 turn, §6 cancel | §1.5 | 无 |
| slice-5 session | §5 session, §8 状态写入 | §2.4, §3.1, §3.2 | `SessionSnapshotData`、`AgentStatus`、`ChatMessage` 等 |
| slice-6 api-shell | §5 api, §9 事件规则 | §1.1, §1.2 | `ApiEnvelope`, `ApiError`, `SseEventType` |
| slice-7 prompts-draft | §5 prompts, §11 prompt 与 LLM | §3.5–§3.8（看每个 agent 的 user_template 入参） | 无 |
| Phase Y agents | §5 agents, §11 prompt 与 LLM | §3.4–§3.8 | 无 |
| Phase Z 组装 | §5 全部, §6 流程, §10 工具链路 | §3.9–§3.11 | `SendTeachingMessageData`, `CancelRunData`, `MessageCompletedEvent` 等 |

---

## 6. 静态解耦自检（每个切片完成后必跑）

```bash
python -m compileall new_kernel

# 反向依赖检查（spec §3 / §13 禁止）
rg -n "^from new_kernel\.api|^import new_kernel\.api" \
   new_kernel/{agents,tools,repo,session,events,memory,llm,prompts}
rg -n "^from new_kernel\.session|^import new_kernel\.session" \
   new_kernel/{agents,tools,repo,events,memory,llm,prompts}
rg -n "^from new_kernel\.agents|^import new_kernel\.agents" \
   new_kernel/{tools,repo,events,session,memory,llm,prompts}
rg -n "^from new_kernel\.events|^import new_kernel\.events" \
   new_kernel/{tools,repo,llm,prompts,memory}    # repo 已确认零导入 events
rg -n "^from new_kernel\.tools|^import new_kernel\.tools" \
   new_kernel/{events,llm,prompts,memory,contracts.py}
```

任何命中必须能用 spec §3 依赖方向图或 §13 import 白名单解释；不能解释就是耦合泄漏。

---

## 7. 偏移监控

- 改动本文档前，先确认改动**仅**为方法签名或字段名细化；语义层改动必须先回 spec
- 一旦 spec 修订，立刻同步本文档对应章节号引用
- contracts.py 增改公开字段时，§4 引用清单同步更新
