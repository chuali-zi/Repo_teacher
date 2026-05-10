# FIX-09 · 按问题意图给 TeacherAgent 软风格倾向（G1 落地）

## What

让 chat 路径的 TeacherAgent 在最后写答案时，被 **软偏好** 引导：用户问"细节实现"
时多贴源码片段、少做目录抽象；问"宏观架构"时多列目录与模块关系、少粘代码原文。
落点是 user_template 末尾追加的 `{answer_style_hint}` 软建议，由 agent 内部一个
中文关键词分类器填入。Composer / deep_research 完全不动。

## Decisions

- **方案选择**：RECON-G 推荐的 G1（user_template 软建议占位符 + agent 内部分类器）。
  最低污染同时给中等以上提升；指令文本只在 user 角色出现，不污染 system prompt；
  与 teach.yaml 现有 1-5 步组织结构是"加权"而非"覆盖"关系；5 分钟回滚。

- **关键词集合**（保留供后续语料回看 / 微调）：
  - macro：架构 / 整体 / 模块 / 分工 / 概览 / 关系 / 顶层 / 都有什么 / 哪些模块 /
    怎么分 / 组织结构 / 划分 / 边界
  - detail：怎么实现 / 具体 / 细节 / 这段代码 / 这块代码 / 函数 / 方法 / 流程 /
    字段 / 参数 / 实现 / 为什么这么写 / 里面 / 内部
  - 命中规则：substring 计数；macro_hit > detail_hit 且 ≥1 → `macro`；
    detail_hit > macro_hit 且 ≥1 → `detail`；其他（含 0/0、平局）→ `mixed`。

- **三段中文软建议**（供 prompt linguist 后续 review）：
  - macro →「学生这次问的是宏观层面的问题，你这次回答更偏向把仓库的目录结构、
    模块分工、依赖关系画清楚，少粘整段代码原文；代码引用控制在 1-2 处即可。」
  - detail →「学生这次问的是具体实现层面的问题，你这次回答更偏向把实际源码片段
    （带 path:line）和关键 symbol 摆出来，多引用代码，目录抽象只在最后一句简短交代。」
  - mixed → ""（空字符串）

- **mixed 故意空串而不是「请按教学正常基调」**：写入一行"请按正常基调"会让模型把
  那行当指令，反而对"语气中立"加权，可能拖向更平庸的回答；保持空串等于真的什么
  都不暗示，让模型继续按 system 中已有的 1-5 步组织结构发挥即可。

- **范围隔离**：`teach.yaml` 仅改 `user_template:`，`system:` 块逐字未动；
  `_DEFAULT_USER_TEMPLATE` fallback 同步加同一个占位符行，避免 yaml 缺失时
  `.format(answer_style_hint=...)` KeyError；TeachingLoop 不改（`question` 已经
  是 user_message 原文，自然可用）；deep_research/Composer 不改。

## Changes

- `new_kernel/prompts/zh/teach.yaml`：在 `user_template:` 块的"下一个教学点提示"
  和"请输出自然中文教学正文"之间，追加 2 行（标题 + `{answer_style_hint}`）。
  `system:` 块零改动。
- `new_kernel/agents/teacher.py`：
  - 新增模块级常量 `_MACRO_KEYWORDS` / `_DETAIL_KEYWORDS`；
  - 新增 `_classify_question_intent(question)`（substring 计数 + 平局/0 归 mixed）；
  - 新增 `_answer_style_hint(intent)`（macro/detail 各一段中文软建议，mixed → ""）；
  - `_build_user_prompt` 在 `_safe_format` 调用上多传一个 `answer_style_hint` kwarg；
  - `_DEFAULT_USER_TEMPLATE` 同步加 `本轮回答风格倾向（软建议）：\n{answer_style_hint}`
    一段，保护 yaml 缺失时的 fallback 路径。
- `new_kernel/tests/test_teacher_style_hint.py`：新增 16 个 pytest 用例（其中
  10 个来自 3 组 parametrize），覆盖 (a)-(h) 全部要求；额外加了一个 macro
  end-to-end 用例与 detail 配对。

## Verify

```
$ python -m pytest -q new_kernel/tests/test_teacher_style_hint.py
................                                                         [100%]
16 passed in 0.52s

$ python -m pytest -q new_kernel/tests/test_*.py \
    --ignore=new_kernel/tests/tmp_run --ignore=new_kernel/tests/pytest_tmp_run
100 passed, 8 warnings in 4.03s
```

84 baseline + 16 new = 100 全绿；老用例零回归。

## Open

- 关键词表是手工启发，覆盖会漏（例如纯英文"how is X implemented"、"architecture"
  混在中文里）；当前不扩，等真实 chat log 反馈后按命中率再加一批。
- 平局 / 全 0 都归 mixed → 完全不下偏好。如果将来想给 ReadingAgent 也用同一个
  hint（半 G4 路径），按 RECON-G 的 G5 思路把 `_classify_question_intent` 上提到
  `teaching_loop.py`，再多挂一个 kwarg 即可，G1 → G5 切换成本约 10 分钟。
- chat 与 deep 不共用：deep onboarding 的 user_message 是固定中文 seed，意图永远
  宏观；当前 v1 也不支持 deep 重跑，所以本次 Composer 不动；如果将来允许 deep
  二次 turn 带 follow-up question，再把同型机制搬过去即可。
