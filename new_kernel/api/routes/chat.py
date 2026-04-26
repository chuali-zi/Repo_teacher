# POST /api/v4/chat/messages：mode=chat 走 TeachingLoop / mode=deep 走 DeepResearchLoop，TurnRuntime.start_turn 创建 turn_id（202 Accepted）；GET /api/v4/chat/stream：按 turn_id 过滤 SSE 流。
