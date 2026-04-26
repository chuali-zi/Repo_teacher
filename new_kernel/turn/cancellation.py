# CancellationToken：协作式取消信号，TeachingLoop / DeepResearchLoop 在 orient / per-step / teach 三个检查点轮询 token.is_cancelled，命中即停止并由 TurnRuntime emit run_cancelled。
