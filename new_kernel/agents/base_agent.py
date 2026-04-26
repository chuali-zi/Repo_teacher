# BaseAgent 抽象基类：统一封装 call_llm / stream_llm / get_prompt，构造时直接持有 llm.client，子类只实现 process()，约 80 行的最小子集（抄自 DeepTutor base_agent.py:354-777，去掉 token tracker / 多 provider / agents.yaml / log_dir 等副产物）。
