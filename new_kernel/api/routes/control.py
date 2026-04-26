# POST /api/v4/control/cancel：触发当前 active turn 的 CancellationToken，TurnRuntime 收到后 emit RunCancelledEvent + AgentStatus(state=idle, phase=cancelled)，返回 CancelRunData。
