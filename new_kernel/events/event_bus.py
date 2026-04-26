# EventBus：per-session 异步队列 + 多消费者 fan-out（asyncio.Queue 列表），publish(event) 同步分发给所有订阅者，subscribe() 返回独立 queue 给 SSE 流。
