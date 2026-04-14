# M5/M6 改造方案：让智能体老师真正能教学

> **目标**：当前 LLM 被当作"结构化填表机器"使用，改造后让它成为"主动带路的教学老师"。
> **涉及文件**：5 个，按顺序执行。
> **约束**：不改动 m1-m4 模块，不改动 contracts/domain.py 中的 PromptBuildInput 模型定义，不改动前端。

---

## 目录

- [STEP-1](#step-1) — `llm_caller.py`：支持多轮消息 + 可调温度
- [STEP-2](#step-2) — `prompt_builder.py`：拆分多轮消息 + 放松规则 + 保留路径（核心改动）
- [STEP-3](#step-3) — `answer_generator.py`：适配新接口
- [STEP-4](#step-4) — `session_service.py`：放宽限制参数
- [STEP-5](#step-5) — 测试文件：适配新接口
- [CHECKLIST](#checklist) — 改完后验证清单

---

## <a id="step-1"></a>STEP-1：改 `backend/m6_response/llm_caller.py`

**目的**：让 LLM 调用支持 system/user/assistant 多条消息，而不是把所有内容塞进一条 user 消息。同时把 temperature 从硬编码 0.2 提高到默认 0.6。

### 1-A：改函数 `stream_llm_response` 签名（第 26 行）

**旧代码**：
```python
async def stream_llm_response(prompt: str) -> AsyncIterator[str]:
```

**新代码**：
```python
async def stream_llm_response(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.6,
) -> AsyncIterator[str]:
```

### 1-B：改 OpenAI 流式调用处（第 42-47 行）

**旧代码**：
```python
stream = await client.chat.completions.create(
    model=config.model,
    messages=[{"role": "user", "content": prompt}],
    temperature=0.2,
    stream=True,
    timeout=config.timeout_seconds,
)
```

**新代码**：
```python
stream = await client.chat.completions.create(
    model=config.model,
    messages=messages,
    temperature=temperature,
    stream=True,
    timeout=config.timeout_seconds,
)
```

### 1-C：改 fallback 调用处（第 31 行）

**旧代码**：
```python
yield await asyncio.to_thread(_complete_with_stdlib_http, config, prompt)
```

**新代码**：
```python
yield await asyncio.to_thread(_complete_with_stdlib_http, config, messages, temperature)
```

### 1-D：改函数 `_complete_with_stdlib_http` 签名和 body（第 69-78 行）

**旧代码**：
```python
def _complete_with_stdlib_http(config: LlmConfig, prompt: str) -> str:
    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "stream": False,
        }
    ).encode("utf-8")
```

**新代码**：
```python
def _complete_with_stdlib_http(
    config: LlmConfig,
    messages: list[dict[str, str]],
    temperature: float,
) -> str:
    endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
    body = json.dumps(
        {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
    ).encode("utf-8")
```

---

## <a id="step-2"></a>STEP-2：改 `backend/m6_response/prompt_builder.py`（核心改动）

**目的**：这是最重要的一步。把 LLM 从"填表机器"变成"教学老师"。

### 2-A：替换 `_SYSTEM_RULES` 常量（第 16-26 行）

**旧代码**：
```python
_SYSTEM_RULES = """
你是 Repo Tutor 的教学回答 Agent。

必须严格遵守：
1. 只能基于提供的教学骨架、主题切片、会话状态回答，不得发明新结论。
2. 对入口、流程、分层、依赖等不确定结论，使用"候选 / 可能 / 目前证据更支持"之类措辞。
3. 不得输出敏感文件正文、绝对真实路径、内部错误堆栈、疑似密钥。
4. 每轮只讲 2-4 个核心点；浅层时更少，深层时可补更多证据，但仍要标注不确定项。
5. 如果证据不足，要明确说明"不确定"或"暂时无法确认"，不要强行补全。
6. 最终必须输出给用户看的 Markdown 正文，然后单独输出一个 <json_output>...</json_output> 结构化 JSON。
""".strip()
```

**新代码**：
```python
_SYSTEM_RULES = """
你是 Repo Tutor，一位面向编程初学者的源码仓库教学老师。

你的教学风格：
- 像一位耐心的导师一样，用自然的语言带着学生理解代码仓库。
- 主动引导学生：每轮结束时告诉学生下一步该看什么、为什么。
- 先讲骨架再讲细节：先帮学生建立整体认知，再逐步深入。
- 每轮围绕 2-5 个核心认知点展开，不要一次灌输太多。

你的知识来源：
- 优先基于提供的教学骨架和主题切片来回答。
- 当骨架中没有直接对应的内容时，可以基于编程常识和仓库上下文合理补充，但请标注"根据推断"或"可能"。
- 对入口、流程、分层等不确定结论，使用"候选""可能""目前证据更支持"等措辞。
- 证据不足时，明确说"目前不确定"，不要硬编。

安全规则：
- 不得输出疑似密钥、token、凭据等敏感信息。
- 不得输出内部错误堆栈。

输出格式：
- 先输出给用户看的 Markdown 正文（自然教学语言，不要像在填表）。
- 正文结束后，另起一行输出 <json_output>...</json_output> 包裹的结构化 JSON，用于系统解析。
""".strip()
```

### 2-B：删除 `build_prompt` 函数，新建 `build_messages` 函数（第 29-44 行）

**旧代码（整个 `build_prompt` 函数）**：
```python
def build_prompt(input_data: PromptBuildInput) -> str:
    payload = _build_payload(input_data)
    json_schema = _json_schema_for_scenario(input_data.scenario)
    sections = [
        _SYSTEM_RULES,
        f"场景: {input_data.scenario}",
        f"讲解深度: {input_data.depth_level}",
        _scenario_guidance(input_data.scenario),
        "输出要求:",
        _output_requirements(input_data),
        "JSON 结构要求:",
        json_schema,
        "可用上下文(JSON):",
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
    ]
    return "\n\n".join(section for section in sections if section)
```

**新代码（替换为 `build_messages` + 辅助函数 `_strip_json_output`）**：
```python
def build_messages(input_data: PromptBuildInput) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    # 1) system message: 角色 + 规则 + 场景 + 参考素材
    system_parts = [
        _SYSTEM_RULES,
        f"当前场景: {input_data.scenario}",
        f"讲解深度: {input_data.depth_level}",
        _scenario_guidance(input_data.scenario),
        _output_requirements(input_data),
        "JSON 结构要求:\n" + _json_schema_for_scenario(input_data.scenario),
        "以下是当前仓库的教学参考素材（教学骨架和主题切片），请基于这些素材回答：",
        json.dumps(_build_payload(input_data), ensure_ascii=False, indent=2, sort_keys=True),
    ]
    messages.append({
        "role": "system",
        "content": "\n\n".join(part for part in system_parts if part),
    })

    # 2) 历史对话: 真正的 user/assistant 多轮消息
    for msg in input_data.conversation_state.messages[-8:]:
        if msg.role == "user":
            messages.append({"role": "user", "content": msg.raw_text})
        elif msg.role == "agent":
            visible = _strip_json_output(msg.raw_text)
            if len(visible) > 1500:
                visible = visible[:1500] + "\n...(已截断)"
            messages.append({"role": "assistant", "content": visible})

    # 3) 如果历史消息的最后一条已经是当前用户消息，就不用重复添加
    current_user_text = input_data.user_message or ""
    if current_user_text and (
        not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != current_user_text
    ):
        messages.append({"role": "user", "content": current_user_text})

    return messages


def _strip_json_output(text: str) -> str:
    """去掉 <json_output>...</json_output> 块，只保留用户可见的 Markdown 部分。"""
    return re.sub(r"<json_output>.*?</json_output>", "", text, flags=re.DOTALL).strip()
```

> **注意**：`_strip_json_output` 用到了 `re`，文件顶部已经有 `import re`，无需新增 import。

### 2-C：简化 `_sanitize_value` 函数（第 76-90 行）— 保留路径，只过滤密钥

**旧代码**：
```python
def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"root_path", "real_path", "internal_detail"}:
                continue
            sanitized[key] = _sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        redacted = _WINDOWS_PATH_RE.sub("<path_omitted>", value)
        redacted = _UNIX_PATH_RE.sub("<path_omitted>", redacted)
        return _SECRET_RE.sub("[redacted_secret]", redacted)
    return value
```

**新代码**：
```python
def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"internal_detail"}:
                continue
            sanitized[key] = _sanitize_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _SECRET_RE.sub("[redacted_secret]", value)
    return value
```

> **变更说明**：
> - 删除 `root_path`、`real_path` 的过滤 — 路径是教学核心素材
> - 删除 `_WINDOWS_PATH_RE`、`_UNIX_PATH_RE` 的替换 — 文件路径不是敏感信息
> - 保留 `_SECRET_RE` — 密钥必须脱敏
> - 保留 `internal_detail` 过滤 — 内部调试信息不需要暴露
> - `_WINDOWS_PATH_RE` 和 `_UNIX_PATH_RE` 两个常量定义（第 10-11 行）可以删除，也可以保留不管

### 2-D：简化 `_output_requirements` 函数（第 127-137 行）

**旧代码**：
```python
def _output_requirements(input_data: PromptBuildInput) -> str:
    required_sections = ", ".join(input_data.output_contract.required_sections)
    return (
        f"- 先输出用户可读 Markdown，再输出 <json_output>JSON</json_output>。\n"
        f"- required_sections 顺序: {required_sections}\n"
        f"- max_core_points: {input_data.output_contract.max_core_points}\n"
        f"- must_include_next_steps: {str(input_data.output_contract.must_include_next_steps).lower()}\n"
        f"- must_mark_uncertainty: {str(input_data.output_contract.must_mark_uncertainty).lower()}\n"
        f"- must_use_candidate_wording: {str(input_data.output_contract.must_use_candidate_wording).lower()}\n"
        f"- next_steps / suggested_next_questions 必须 1-3 条，短句、可点击、自然。"
    )
```

**新代码**：
```python
def _output_requirements(input_data: PromptBuildInput) -> str:
    required_sections = ", ".join(input_data.output_contract.required_sections)
    return (
        f"回答建议包含以下部分（自然衔接，不需要严格分段标题）: {required_sections}\n"
        f"核心认知点控制在 {input_data.output_contract.max_core_points} 个以内。\n"
        f"每轮结尾给出 1-3 条下一步建议，用自然的引导语气。\n"
        f"不确定的结论请标注。"
    )
```

### 2-E：简化 `_sanitize_conversation` 函数（第 60-73 行）

**旧代码**：
```python
def _sanitize_conversation(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state.model_dump(mode="json")
    conversation["messages"] = [
        {
            "message_id": item.message_id,
            "role": item.role,
            "message_type": item.message_type,
            "raw_text": _sanitize_value(item.raw_text),
            "related_goal": item.related_goal,
            "streaming_complete": item.streaming_complete,
        }
        for item in input_data.conversation_state.messages[-6:]
    ]
    return _sanitize_value(conversation)
```

**新代码**：
```python
def _sanitize_conversation(input_data: PromptBuildInput) -> dict[str, Any]:
    conversation = input_data.conversation_state.model_dump(mode="json")
    # 消息内容已通过多轮 messages 传递，这里只保留会话元信息
    conversation.pop("messages", None)
    return _sanitize_value(conversation)
```

---

## <a id="step-3"></a>STEP-3：改 `backend/m6_response/answer_generator.py`

**目的**：衔接层，适配 STEP-1 和 STEP-2 的接口变化。

### 3-A：整个文件替换为

**旧代码（完整文件）**：
```python
from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from backend.contracts.domain import InitialReportAnswer, PromptBuildInput, StructuredAnswer
from backend.m6_response.llm_caller import stream_llm_response
from backend.m6_response.prompt_builder import build_prompt

LlmStreamer = Callable[[str], AsyncIterator[str]]


async def stream_answer_text(
    input_data: PromptBuildInput,
    *,
    llm_streamer: LlmStreamer = stream_llm_response,
) -> AsyncIterator[str]:
    prompt = build_prompt(input_data)
    async for chunk in llm_streamer(prompt):
        yield chunk


def parse_answer(
    input_data: PromptBuildInput,
    raw_text: str,
) -> StructuredAnswer | InitialReportAnswer:
    return parse_final_answer(input_data.scenario, raw_text)
```

**新代码（完整文件）**：
```python
from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from backend.contracts.domain import InitialReportAnswer, PromptBuildInput, StructuredAnswer
from backend.m6_response.llm_caller import stream_llm_response
from backend.m6_response.prompt_builder import build_messages
from backend.m6_response.response_parser import parse_final_answer

LlmStreamer = Callable[[list[dict[str, str]]], AsyncIterator[str]]


async def stream_answer_text(
    input_data: PromptBuildInput,
    *,
    llm_streamer: LlmStreamer = stream_llm_response,
) -> AsyncIterator[str]:
    messages = build_messages(input_data)
    async for chunk in llm_streamer(messages):
        yield chunk


def parse_answer(
    input_data: PromptBuildInput,
    raw_text: str,
) -> StructuredAnswer | InitialReportAnswer:
    return parse_final_answer(input_data.scenario, raw_text)
```

> **变化点**：`build_prompt` → `build_messages`，`Callable[[str], ...]` → `Callable[[list[dict[str, str]]], ...]`。
> 同时补上原文件缺失的 `from backend.m6_response.response_parser import parse_final_answer` import。

---

## <a id="step-4"></a>STEP-4：改 `backend/m5_session/session_service.py`

**目的**：给老师更多素材和空间。

### 4-A：`_topic_slice_for_goal` 方法（第 623 行）

**旧代码**：
```python
return self._dedupe_topic_refs(refs)[:10]
```

**新代码**：
```python
return self._dedupe_topic_refs(refs)[:20]
```

### 4-B：`_output_contract` 方法（第 610 行）

**旧代码**：
```python
max_core_points=2 if depth == DepthLevel.SHALLOW else 4,
```

**新代码**：
```python
max_core_points=3 if depth == DepthLevel.SHALLOW else 5,
```

### 4-C：`_summarize_recent_messages` 方法（第 665 行和第 677 行）

**旧代码（第 665 行）**：
```python
for message in messages[-6:]:
```

**新代码**：
```python
for message in messages[-10:]:
```

**旧代码（第 677 行）**：
```python
return summary[-1200:] if summary else None
```

**新代码**：
```python
return summary[-2000:] if summary else None
```

---

## <a id="step-5"></a>STEP-5：改测试文件

### 5-A：改 `backend/tests/test_m5_session.py` 的 `fake_llm_streamer` fixture（第 25-65 行）

**旧代码**：
```python
@pytest.fixture(autouse=True)
def fake_llm_streamer():
    prompts: list[str] = []
    previous_streamer = session_service.llm_streamer

    async def stream(prompt: str):
        prompts.append(prompt)
        label = _prompt_label(prompt)
        # ... payload 和 yield 不变 ...

    session_service.llm_streamer = stream
    yield prompts
    session_service.llm_streamer = previous_streamer
    session_service.clear_active_session()
```

**新代码**：
```python
@pytest.fixture(autouse=True)
def fake_llm_streamer():
    captured: list[list[dict[str, str]]] = []
    previous_streamer = session_service.llm_streamer

    async def stream(messages: list[dict[str, str]]):
        captured.append(messages)
        all_text = " ".join(m.get("content", "") for m in messages)
        label = _prompt_label(all_text)
        payload = {
            "focus": f"LLM focus: {label}",
            "direct_explanation": f"LLM direct answer for {label}.",
            "relation_to_overall": "This answer is generated from the M6 prompt context.",
            "evidence_lines": [
                {
                    "text": "M6 received the controlled teaching skeleton and topic slice.",
                    "evidence_refs": [],
                    "confidence": "medium",
                }
            ],
            "uncertainties": ["当前没有额外不确定项。"],
            "next_steps": [
                {
                    "suggestion_id": "s_next",
                    "text": "继续看入口候选。",
                    "target_goal": "entry",
                    "related_topic_refs": [],
                }
            ],
            "related_topic_refs": [],
            "used_evidence_refs": [],
        }
        text = (
            f"## 本轮重点\nLLM answer for {label}."
            f"\n<json_output>{json.dumps(payload)}</json_output>"
        )
        midpoint = len(text) // 2
        yield text[:midpoint]
        yield text[midpoint:]

    session_service.llm_streamer = stream
    yield captured
    session_service.llm_streamer = previous_streamer
    session_service.clear_active_session()
```

> **变量名从 `prompts` 改成 `captured`**。测试文件中所有引用 `fake_llm_streamer` 返回值的地方：
> - 如果原来是 `assert "xxx" in prompts[0]`，改成 `assert any("xxx" in m.get("content", "") for m in captured[0])`
> - 如果原来是 `len(prompts)`，改成 `len(captured)`
> - 搜索整个测试文件中所有使用 fixture 返回值的位置，逐一适配

### 5-B：改 `backend/tests/test_m6_response.py` 的 import 和测试函数

**旧代码（第 44 行）**：
```python
from backend.m6_response.prompt_builder import build_prompt
```

**新代码**：
```python
from backend.m6_response.prompt_builder import build_messages
```

**旧代码（第 49-72 行，整个测试函数）**：
```python
def test_build_prompt_for_follow_up_includes_sanitized_context() -> None:
    prompt = build_prompt(
        PromptBuildInput(
            scenario=PromptScenario.FOLLOW_UP,
            user_message="启动流程怎么走？",
            teaching_skeleton=_teaching_skeleton(),
            topic_slice=[_topic_ref("ref_flow", LearningGoal.FLOW, "主流程")],
            conversation_state=ConversationState(
                current_repo_id="repo_1",
                current_learning_goal=LearningGoal.FLOW,
                current_stage=TeachingStage.INITIAL_REPORT,
                sub_status=ConversationSubStatus.AGENT_THINKING,
            ),
            history_summary="用户刚看完首轮报告，想继续看启动流程。",
            depth_level=DepthLevel.DEFAULT,
            output_contract=_output_contract(),
        )
    )

    assert "场景: follow_up" in prompt
    assert "启动流程怎么走？" in prompt
    assert "<json_output>" in prompt
    assert "[redacted_path]" not in prompt
    assert '"topic_slice"' in prompt
```

**新代码**：
```python
def test_build_messages_for_follow_up_includes_context() -> None:
    messages = build_messages(
        PromptBuildInput(
            scenario=PromptScenario.FOLLOW_UP,
            user_message="启动流程怎么走？",
            teaching_skeleton=_teaching_skeleton(),
            topic_slice=[_topic_ref("ref_flow", LearningGoal.FLOW, "主流程")],
            conversation_state=ConversationState(
                current_repo_id="repo_1",
                current_learning_goal=LearningGoal.FLOW,
                current_stage=TeachingStage.INITIAL_REPORT,
                sub_status=ConversationSubStatus.AGENT_THINKING,
            ),
            history_summary="用户刚看完首轮报告，想继续看启动流程。",
            depth_level=DepthLevel.DEFAULT,
            output_contract=_output_contract(),
        )
    )

    assert isinstance(messages, list)
    assert len(messages) >= 2
    assert messages[0]["role"] == "system"
    assert "Repo Tutor" in messages[0]["content"]
    assert messages[-1]["role"] == "user"
    assert "启动流程怎么走？" in messages[-1]["content"]
    assert "topic_slice" in messages[0]["content"]
```

---

## <a id="checklist"></a>改完后验证清单

按以下顺序验证：

1. **跑测试**：`pytest backend/tests/ -v`，全部通过
2. **启动服务**：确认服务能正常启动，不报 import 错误
3. **提交一个仓库**：走一遍完整流程，确认首轮报告能正常生成
4. **多轮追问**：连续问 3-5 个问题，观察：
   - 老师是否用自然语言在教学，而不是在填表
   - 老师是否能引用具体的文件路径（如 `backend/main.py`）
   - 老师是否能记住前几轮讲了什么，不重复从零开始
   - 老师是否在每轮结尾主动给出下一步建议
   - `<json_output>` 块是否仍然能正常生成和解析
5. **检查 response_parser 兼容性**：确认 `parse_final_answer` 仍能从新格式的 LLM 输出中正确提取 JSON
