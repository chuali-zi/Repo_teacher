# 错误处理：内部异常 → contracts.ApiError 映射（ErrorCode + ErrorStage + retryable + input_preserved），FastAPI exception_handler 把任何未捕获异常包成失败 envelope。
