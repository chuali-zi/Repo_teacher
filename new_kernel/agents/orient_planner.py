# OrientPlanner：把 user_message 一次 LLM 调用拆成 1-3 个读码 step（合并 orient + plan），输出严格 JSON 的 reading_plan，每个 step 带 anchors=[{path, why}]。
