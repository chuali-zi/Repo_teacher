# ReadingAgent：ReAct 单轮决策 agent，每轮输出严格 JSON {thought, action, action_input, self_note}，action 必须落在 tool_runtime.valid_actions 内否则降级为 done；单 step 最多 3 轮。
