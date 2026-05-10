# RECON-G · 「按问题意图软偏好代码 vs 目录展示」侦察

## What

让 TeacherAgent（chat）和 Composer（deep）在最后组织回答时被**软偏好**：用户问"细节实现"时多贴源码片段、少做目录抽象；问"宏观架构"时多列目录与模块关系、少粘代码原文。这是回答组织阶段的**软偏好**，不是硬路由；不修改任何代码 / yaml，只产出方案。

## 当前现状

### TeacherAgent（chat 路径）

- 系统词来自 `prompts/zh/teach.yaml:1-23`，已经写明"引用 1-3 个关键源码位置（path 或 path:line）；只贴 5-15 行最有信息量的部分"`teach.yaml:11`，但这是"细节型"基调；没有"问宏观时多列目录"的反向倾向。
- user_template 在 `prompts/zh/teach.yaml:25-38`，占位符当前只有 `{question}` / `{scratchpad_evidence}` / `{previous_covered}` / `{next_anchor_hint}`。
- 系统词 fallback + user_template fallback 各自在 `agents/teacher.py:137-151`；agent 通过 `_safe_format(template, **values)`（`agents/teacher.py:130-134`）填充模板；任何新占位符如果 yaml 缺则会回退到 `_DEFAULT_USER_TEMPLATE`，所以新增占位符必须同步改两侧。
- 入口 `TeacherAgent.process(question=..., scratchpad=..., ...)`（`agents/teacher.py:31-46`）：上层有 `question` 字段可见。

### Composer（deep 路径）

- 系统词 `deep_research/prompts/zh/compose.yaml:1-48`，已锁死"按 sub-topic 顺序展开 + 架构节 1.5–2 倍篇幅"`compose.yaml:26-27`；正文护栏中"不要粘超过 40 行原始代码；短引用 5-15 行"`compose.yaml:38`。这是"标准 onboarding 报告"基调，没有"按用户当前关注度"分支。
- user_template `deep_research/prompts/zh/compose.yaml:50-67` 占位符 `{report_shape}` / `{repo_overview_text}` / `{subtopics_meta}` / `{notes_dump}` / `{raw_first_round_dump}`，通过 `deep_research/agents/composer.py:97-103` 填充。
- 见 §"关于 deep onboarding"——deep 模式的 user_message 不是用户问题，是固定中文 seed，所以不需要意图分类。

### 用户问题信号在哪

- HTTP 入口契约 `contracts.py:153-158`：`SendTeachingMessageRequest.message`。
- TurnRuntime 把它原样传给 loop：`turn/turn_runtime.py:355-365` `loop.run(..., user_message=request.message, ...)`。
- TeachingLoop 把 user_message 当成 `question` 既给 OrientPlanner（`agents/teaching_loop.py:137`）也给 TeacherAgent（`agents/teaching_loop.py:210`）。
- 也就是说在 chat 路径上，`user_message` 在 orient / read / teach 三处都已经可见，分类点可以放在它们任一进入之前。

## 意图启发式（关键词集合）

一个**软启发**——硬命中即标，未命中归为 `mixed`，不强制覆盖。

| 类别 | 中文关键词（任一命中即记一票） |
| --- | --- |
| macro | 架构 / 整体 / 总体 / 模块 / 分工 / 大体 / 概览 / 关系 / 边界 / 顶层 / 都有什么 / 几大部分 / 目录 / 布局 / overview / structure |
| detail | 怎么实现 / 如何实现 / 具体 / 细节 / 这段代码 / 这一段 / 这一块 / 内部 / 字段 / 参数 / 函数 / 方法 / 流程 / 入口 / 行 / 这里 / 实现 / 解析 / 算法 / 工作原理 |

简单选择规则：

- `macro_hit > detail_hit` → `macro`
- `detail_hit > macro_hit` → `detail`
- 两边都 0 或两边都 ≥1 且相等 → `mixed`（不下任何偏好建议）

参考人工标注表：

| 用户问题（paraphrase） | 期望意图 | 期望偏好 |
| --- | --- | --- |
| "这个仓库的整体架构是什么" | macro | dirs + 模块关系；少粘代码 |
| "deep_research 模块在干什么" | mid（命中 "模块"）→ macro | 目录级摘要 + 1-2 个轻引用 |
| "DeepResearchLoop.run 怎么工作的" | detail（命中 "怎么"+"工作"） | 代码引用 + 行号 |
| "Phase 2 里的 ReAct 循环逻辑怎么实现的" | detail（命中 "怎么实现"） | 代码引用 + 流程 |
| "总共有多少模块、各自分工" | macro | 目录树 + 一行一模块 |
| "教学 loop 与 deep loop 的关系" | macro | 关系图 + 轻引用 |

承认局限：关键词命中是粗启发，会漏会误判；这正是放在**软偏好**而不是**硬路由**的原因。

## 候选方案

### G1 — user_template 软建议占位符

在 `prompts/zh/teach.yaml:25-38` user_template 末尾追加一段，由 agent 侧根据关键词分类填入：

```yaml
user_template: |
  ...（原内容不变）...

  本轮回答风格倾向（仅作为软建议，最终以教学价值为准）：
  {answer_style_hint}
```

agent 侧（`agents/teacher.py:_build_user_prompt` / `process`）在 `_safe_format` 之前根据 question 关键词分类：

```python
def _classify_intent(question: str) -> str:
    q = question
    macro_kw = ("架构", "整体", "模块", "分工", ...)
    detail_kw = ("怎么实现", "具体", "函数", ...)
    macro_hit = sum(1 for k in macro_kw if k in q)
    detail_hit = sum(1 for k in detail_kw if k in q)
    if macro_hit > detail_hit: return "macro"
    if detail_hit > macro_hit: return "detail"
    return "mixed"

_HINT = {
    "macro": "你这次回答更适合多列出目录与模块结构，少粘大段代码原文；引用 1 处即可。",
    "detail": "你这次回答更适合多引用源码片段与具体行号；可以保留 2-3 处代码块。",
    "mixed": "（无特定偏好，按教学正常基调即可）",
}
```

- **改动点**：`prompts/zh/teach.yaml:25-38` 加 1 占位符；`agents/teacher.py:82-97`（`_build_user_prompt`）加 1 个分类调用 + 字典映射；`agents/teacher.py:145-151`（`_DEFAULT_USER_TEMPLATE`）保持同步。
- **污染**：user_template 软指令型——比纯数据强，比 system 弱。指令文本只在 user 角色出现，不污染 system prompt。
- **提升**：中等。LLM 通常对 user_template 末尾的"风格倾向"提示比较敏感，特别是当 system 已有明确组织结构时（teach.yaml 的 1-5 步骤），这条软建议是"加权"而不是"覆盖"。
- **AGENTS.md 兼容**：与 §7.2 "教师腔基调"、§7.1 反模式都不冲突；不引入工具术语；不写"必须"。
- **可逆性**：5 分钟回滚（删占位符 + 删分类函数）。

### G2 — 纯数据占位符（无指令）

把 G1 的指令性文字换成**纯信号数据**，让模型自己解读：

```yaml
user_template: |
  ...（原内容不变）...

  本轮提问关键词标签：{question_keywords}
  本轮意图分类：{focus_hint}      # macro | detail | mixed
```

agent 侧只填数据：`question_keywords="架构, 模块"` / `focus_hint="macro"`，不写任何"应该多/少"的指令。

- **改动点**：teach.yaml + teacher.py 各加 2 个占位符；分类函数同 G1。
- **污染**：极低（纯数据，无 imperative 语言；不出现"请多"、"少"等动词）。
- **提升**：低到中。优势：完全没有 prompt 污染；劣势：依赖模型自己悟出"既然你给我标了 macro，那我应该……"——较弱模型可能直接忽略。
- **AGENTS.md 兼容**：完全兼容；这只是"问题元数据"，性质同 `previous_covered`。
- **可逆性**：5 分钟回滚。

### G3 — 条件 system suffix（不推荐）

在 TeacherAgent 调用前 dynamically 拼接系统词：

```python
suffix = {"macro": "本轮请多展示目录与模块关系。",
          "detail": "本轮请多展示实际代码引用。"}.get(intent, "")
system_prompt = base_system + ("\n\n" + suffix if suffix else "")
```

- **改动点**：`agents/teacher.py:79-80`（`_build_system_prompt`）改成接受 question 参数并按 intent 加 suffix；teach.yaml 不动。
- **污染**：**system 级**——历史上用户已明确在 RECON-D（`deep_research/.reports/RECON-D-arch-nudge.md`）拒绝过为"架构节稳定列目录"加 system 级 nudge；同类信号；**很可能踩雷**。
- **提升**：高（system 提示在 LLM 优先级最高）。
- **AGENTS.md 兼容**：不与硬条款冲突，但与"系统词不轻易加分支指令"的隐式偏好冲突。
- **可逆性**：5 分钟回滚。

> 标记此项**仅为完整性记录**，不推荐落地。

### G4 — 锚点侧（前置 orient/read 偏置）

修改 TeachingLoop / OrientPlanner / ReadingAgent，让 macro 意图驱动 reading_plan 选 `list_dir` / `summarize_file`，detail 意图驱动 `read_file_range`：

- 把 `intent` 注入 `OrientPlanner.process`（`agents/orient_planner.py:27-50`）的 user_template 作为新占位符；Planner 自然产出更符合意图的 plan。
- 同样思路给 `ReadingAgent`（`agents/reading_agent.py`）传 hint。
- 后果：到达 TeacherAgent 时 `scratchpad.build_teacher_context()`（`memory/scratchpad.py:223-234`）已经"自然"含有更多目录信号或更多源码片段，TeacherAgent **不知情**也会沿用。

- **改动点**：3 个 prompt + 3 个 agent 入口。一处分类，三处消费。
- **污染**：分散到 orient.yaml + 阅读 yaml；`teach.yaml` 完全不动。
- **提升**：高（直接改变证据结构，TeacherAgent 没法不改风格）；但风险也高——意图判错时连证据都偏了，比 G1/G2 的"只是建议"更危险。
- **AGENTS.md 兼容**：影响 reading 阶段；不冲突。
- **可逆性**：30 分钟以上（要回滚 3 个文件 + 联调 3 个 agent）。

### G5 — TeacherAgent 前置 classifier（独立分类器）

在 TeachingLoop 调用 `self._teacher.process(...)` 前（`agents/teaching_loop.py:209-215`）插入一个轻量分类——可以是规则、也可以是一次小 LLM call——产出 `style_hint`，作为 kwarg 传给 `TeacherAgent.process`，再由 teacher 在 user_template 注入。

- **改动点**：teaching_loop.py 加一行规则分类（与 G1 共用 `_classify_intent`）+ 一个 kwarg；teacher.py 加 kwarg 形参 + 占位符；teach.yaml 加占位符。
- **污染**：等同 G1（同样落到 user_template），只是分类逻辑放在 loop 而不是 agent 内部，便于单元测。
- **提升**：中（与 G1 等同）。
- **AGENTS.md 兼容**：完全兼容；与 G1 性质相同。
- **可逆性**：10 分钟回滚（多一个 kwarg 解绑步骤）。

> 与 G1 的差别：G1 在 agent 内部分类，调用方无感；G5 把分类提到 loop，便于将来从规则升级到小模型/复用到别的 agent。如果以后想给 ReadingAgent 也用同一个 hint（即"半 G4"），G5 是更好的起点。

## 推荐

**主推：G1**

- 最低污染同时给中等以上提升：user_template 软建议落在 user 角色，与现有 teach.yaml 的"1-2 步直接回应；3 步串调用链"叙事结构对齐——它不是"覆盖"system 的步骤，而是"在第 2 步的代码引用密度上做加权"。
- 实现极轻：1 个占位符 + 1 个分类函数 + 1 张关键词表，全部塞进 `agents/teacher.py` 单文件。
- chat 单路径足够：deep onboarding 不需要（见下节）。
- 5 分钟回滚。

**兜底：G5**

- 当将来想把同一 hint 复用到 ReadingAgent / OrientPlanner（半 G4 路径）时，把分类提到 loop 是更干净的迭代起点。
- G1 → G5 升级成本低（把 `_classify_intent` 从 teacher.py 搬到 teaching_loop.py，多加 1 个 kwarg）。

**不推荐：G3 / G4**

- G3 踩"系统词分支指令"红线（与 RECON-D 同类信号）。
- G4 风险/收益比差：意图判错时连证据都歪掉。

**chat 与 deep 是否能共用？**

不能。chat 的"用户问的是什么"是 turn 级变量；deep 的 user_message 是 frontend 固定 seed（见下节），不是真用户问题。所以这个 soft preference 只在 chat 路径生效；deep 不需要新机制。

## 验证思路（不实现）

### (a) 手动眼测

- 准备 5 个 detail 样问 + 5 个 macro 样问。例：
  - detail：「`TeachingLoop._run_read_step` 的 ReAct 一轮做了什么？」
  - macro：「这个仓库一共分了几大模块？它们之间怎么协作？」
- 各跑一次 chat 模式，看回答里：
  - detail 期望：≥2 处 ``` `path:line` `` 引用；≥1 个 ``` 围栏 ```代码块；目录段落 ≤1 段。
  - macro 期望：≥2 处 `path/`（带斜杠的目录路径）；≤1 个 ``` 围栏；模块关系叙述 ≥3 段。
- 对照 baseline（关掉 G1 的 hint 跑同 10 题）。

### (b) 廉价自动 metric

不引入 LLM-as-judge，只对最终 assistant 文本做 regex 计数：

```python
re_code_block = re.compile(r"```", re.M)            # 围栏次数（成对算半）
re_pyfile     = re.compile(r"\b\w+\.py\b")          # 文件提及
re_pyline     = re.compile(r"\b\w+\.py:\d+")        # 文件:行 提及
re_dirpath    = re.compile(r"`?(\w+)/(\w+)?/?`?")   # 目录形 path/
```

阈值（建议默认；后续按真实数据微调）：

- detail：`code_block_pairs >= 2` 且 `pyline_count >= 2`。
- macro：`dirpath_count >= 3` 且 `code_block_pairs <= 1`。

把这两条阈值跑在最近 N 条 assistant 文本上，按 intent 分组算命中率；命中率 baseline → 启用 G1 后是否有 ≥10pp 提升。注意：这是**指标趋势**，不是 pass/fail assertion——`AGENTS.md §13` 明确"不写字数下限 assertion"。

## 关于 deep onboarding

不需要新机制。

- deep 模式的 user_message 是前端固定中文 seed（"为我做这个仓库的入门导读"那一类），不是真用户问题；意图永远是"宏观 onboarding"。
- 这一点已经被 `compose.yaml:24-27` 的"按 sub-topic 顺序展开 + 架构节 1.5-2 倍篇幅"+ AGENTS.md §7.2 "5 支柱（what/stack/why/arch/flow）"硬编码到 prompt。
- AGENTS.md 当前 v1 不支持 deep 重跑（同一 session 第二次 deep turn 是非典型路径），所以"在 deep 第二次让 user 表达不同关注度"目前不是产品形态。
- 假如将来支持 deep 重跑且第二次允许带 follow-up question，再考虑给 Composer 走 G1 同型机制即可——届时把 `user_message` 当 question 走 `_classify_intent`，往 `compose.yaml:50-67` user_template 加同一类占位符。**当前不动**。
