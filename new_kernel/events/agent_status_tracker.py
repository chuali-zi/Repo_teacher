# AgentStatusTracker：维护当前 AgentStatus 对象（含 metrics 累加），update_phase(...) / update_metrics(...) 自动 broadcast AgentStatusEvent；新阶段事件之前必须先广播 agent_status。
