# TurnRuntime：start_turn 校验“一个 session 同时只允许一个 active turn”，调用 TeachingLoop 或 DeepResearchLoop，终态分别 emit MessageCompletedEvent / ErrorEvent / RunCancelledEvent，并把 active_turn_id 清掉。
