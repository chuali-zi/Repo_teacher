# TeacherAgent：唯一可见正文出口，stream_llm 输出自然教学回答，硬约束：一次只讲一个核心点 / 最多 3 个 anchor / 结尾恰好一个 next_anchor / 证据不足缩小 claim 而不是停止教学。
