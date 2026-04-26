# TeachingLoop：编排一次 turn 的 orient → (per step) read ReAct ≤ 3 轮 → teach 流式输出，途中通过 events.event_bus 推送 agent_status / answer_stream_* / teaching_code 事件，结束写回 scratchpad.covered_points。
