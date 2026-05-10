# RECON-D · 架构节稳定列目录 优化方案 侦察

## What

针对用户反馈"首次 deepresearch 在 arch 这块要稳定地详细一点：列出顶层目录 + 每个目录在干嘛。现在有时列有时不列，比较看运气。" 侦察今天的目录数据流，定位"看运气"的根因，并给出 2-4 个不修系统 prompt、不强制基调的轻量优化方案，按"侵入度 × 提升幅度"排序。

## 当前数据流证据链

### (a) `RepoOverview.text` 的形状

**已经包含顶层路径**，且是结构化的 YAML 风格列表。`repo/overview_builder.py:46-76` 的 `_build_lines`：

```python
lines = ["repo_overview:", f"- primary_language: {scan.primary_language or 'unknown'}",
         f"- file_count: {scan.file_count}", ...]
if top_level_paths:
    lines.append("- top_level_paths:")
    lines.extend(f"  - {path}" for path in top_level_paths[:20])
if candidates:
    lines.append("- entry_candidates:")
    lines.extend(f"  - {candidate.path} ({candidate.language or 'text'}): {candidate.reason}" ...)
```

`top_level_paths` 由 `_top_level_paths` (line 130-133) 从扫到的 `directories.depth==1` + `files.depth==1` 各取 12 项排序拼接而成，目录追加 `/`。

也就是说，**`overview.text` 里已经写好了一段以 `- top_level_paths:` 开头、每行 `  - module/`、`  - api/` 这样的小章节**，最多 20 行（再加 12 行 entry_candidates）。

### (b) `_StringOverview` 解析

**只解析两个字段，把 top_level_paths 全丢了。** `deep_research/deep_research_loop.py:84-90`：

```python
def __init__(self, *, text: str, primary_language: str | None, file_count: int) -> None:
    self.text = text or ""
    self.primary_language = primary_language
    self.file_count = file_count
    self.language_counts: dict[str, int] = {}
    self.top_level_paths: list[str] = []   # ← 始终空
    self.entry_candidates: list[Any] = []  # ← 始终空
```

`_make_overview_proxy` (line 93-118) 只 split 出 `primary_language:` 和 `file_count:` 两行。其它三个字段（`language_counts` / `top_level_paths` / `entry_candidates`）**永远是空集合**。这是 RECON-B Severity-3 已经记录在案的小问题，但当时没修。

注意：`self.text` 里仍然包含原始的 top_level_paths 行（因为整段 `repo_overview` 字符串原样塞进 `.text`）；只是 `top_level_paths` 这个**结构化字段**为空。

### (c) Decomposer prompt 是否携带顶层路径

**两条通道都拿到了路径，但都是间接的。** `deep_research/agents/decomposer.py:55-67`：

```python
top_level_paths = list(getattr(repo_overview, "top_level_paths", ()) or ())[:60]   # → []
...
user_prompt = self.get_prompt("user_template").format(
    ...
    top_level_paths=json.dumps(top_level_paths, ensure_ascii=False),   # → "[]"
    ...
    repo_overview_text=repo_overview_text,    # 这里 IS 包含完整带 top_level_paths 章节的文本
)
```

而 `prompts/zh/decompose.yaml:60-67` 渲染了两个占位符：

```yaml
顶层路径列表：
{top_level_paths}              ← 这里渲染出 "[]"

仓库概览正文（已经裁剪过）：
{repo_overview_text}            ← 这里 IS 看得见 "- top_level_paths:" 那一段
```

LLM 在 `decompose` 阶段确实**看得见**目录列表（藏在 `repo_overview_text` 里），但只是用作 anchor reachability 校验。`_anchor_reachable` (decomposer.py:136-139) 走双向 substring 比对 `top_level_paths`（**也是空的**）和 entry_candidates（**也是空的**）—— 也就是说：**LLM 输出 anchor 合格率 ≈ 0**，全被 strip 掉。`arch` sub-topic 因此走 `_DEFAULT_ANCHORS_STANDARD["arch"] = ()`（line 36，**空 tuple**）。

### (d) Investigator 是否看到 arch 锚点

**没看到任何 arch 专属锚点。** `deep_research/agents/investigator.py:100-113`：

```python
template.format(
    subtopic_id=subtopic.id,
    subtopic_title=subtopic.title,
    subtopic_anchors=anchors_json,          # ← arch 这里是 "[]"
    ...
    repo_overview_text=repo_overview_text,  # ← 仍然 IS 带 top_level_paths 章节
)
```

`investigate.yaml:42-58` 提示 "路径优先选 sub-topic 的 anchors 中已有的；如果 anchors 空，可以从概览里挑最像入口的一处" + "范围尽可能小：能 list 一个具体目录就不要 search 全仓"。**但这是软建议**，LLM 在 anchors=[] 时常常去读 README.md 又读一遍（因为它是 stack/why 已经读过的），或者挑一个 entry_candidate 的具体文件。**`list_dir({"path":"."})` 是 valid_actions 之一，但没有任何东西在 prompt 层硬性引导它先做这一步**。

### (e) NoteTaker 处理 list_dir 结果

**list_dir 一旦被 Investigator 选中，结果会被忠实保留。** `tools/list_dir.py:122` 把每行格式化为 `[dir]  module/` / `[file] foo.py (1234 bytes)`，整个内容作为 `tool_result.content` 传给 NoteTaker。

NoteTaker 没有针对 list_dir 的特殊压缩；`note.yaml:1-26` 教师腔基调要求把 200-400 字"教学要点"写出来，并且 `note_taker.py:81-83` 的 `_infer_anchor` 会对 `list_dir` 保留 `path` 锚点。`note.yaml` 第 21 行有一句"如果观察里有这类内容（路径脚手架噪声），挑两三处最有信息量的提一下即可"——这意味着 **NoteTaker 会主动把目录列表压成"挑两三处"的笔记**，原始 12-20 个目录名会被它的教师视角主动挑选 / 改写。

但是！重要保险：`deep_research_loop.py:302-307` 把第 1 轮的**原始 observation** 也存进 scratchpad（`raw_observation=observation_text if round_idx == 1 else None`），传到 Composer 上下文的 `raw_first_round_by_id`。所以即使 NoteTaker 只挑了三个目录，Composer 仍然能看到 list_dir 的完整 raw 输出（每 sub-topic 上限 2KB）。

### (f) Composer 上下文里目录数据存活情况

**只有 Investigator 在 `arch` 这一支柱选了 `list_dir` 时，Composer 才稳定看到目录列表。**

`research_scratchpad.py:106-138` 的 `build_compose_context` 输出三个 dict：

- `subtopics_payload`：只有 id/title/anchors/skip_reason，**不携带任何目录信息**。
- `notes_by_id["arch"]`：NoteTaker 挑过的 200-400 字笔记。包含与否取决于 Investigator 是否选了 list_dir。
- `raw_first_round_by_id["arch"]`：Investigator 第 1 轮 list_dir 的完整原始结果（≤2KB），**仅当 Investigator 选了 list_dir** 才有内容。

而 `compose.yaml:50-67` 的 user_template 把这三块组装成正文上下文，**外加** `{repo_overview_text}` 整段（包括原 `- top_level_paths:` 章节）。

也就是说：
- 总有一份 `repo_overview_text` 带顶层路径列表喂给 Composer (`composer.py:97-103` + `_clip_overview` 4KB 限长)。这是"基础信息源"。
- 但 Composer 的 system prompt（`compose.yaml:1-48`）从未要求"必须把顶层目录复述给学生"，只要求"按 sub-topic 顺序展开 / 架构节 1.5-2 倍篇幅"。Composer 对 `repo_overview_text` 的态度是 "轻上下文，仅供你判断方向"。

## 为什么"有时列有时不列"

诊断结论：**目录数据全程存在，但只有在两件事同时发生时 LLM 才会"自然地把它写出来"**——

1. Investigator 在 `arch` 支柱第 1 轮主动选了 `list_dir({"path":"."})`，让 NoteTaker 写出"我们刚扫了一眼顶层有 X / Y / Z 这几块"，并把原始目录列表存进 `raw_first_round_by_id["arch"]`；
2. Composer 看到 arch 这一节 `notes_dump` + `raw_first_round_dump` 都明确出现了目录词条后，自然在正文里复述。

而决定 (1) 是否发生的有两层概率：

- **arch 的 anchors 永远是空**（证据：上文 (c) (d)，`_DEFAULT_ANCHORS_STANDARD["arch"] = ()`，且 LLM 输出的 arch anchors 全被 reachability 校验 strip）。LLM 在 anchors=[] 时发挥空间大：可能选 list_dir / 可能 read 一个具体源文件 / 可能选 search_in_repo。`investigate.yaml` 没有针对 anchors=空 的硬规则。
- **Investigator 是 LLM**，温度 0.1，仍会随机性挑动作；且第 1 轮 sub-topic 已经轮到 arch 时，前 3 个支柱（what / stack / why）都已经多次读 README，系统 message 里提示"路径优先选 anchors 中已有的"——arch 没 anchors，LLM 倾向于"再读一遍 src/ 里某个文件"或"读 setup.py / pyproject"，list_dir 不是首选。

加上 Composer 即使看到 raw_first_round 里的目录列表，没有 system prompt 硬性指引（也不允许加）。所以最终阶段也存在小幅波动。

净结果：用户观察到的"看运气"，**主要赌点 1 在 Investigator 是否选 list_dir**，副赌点在 Composer 对 raw 数据的复述偏好。

## 候选方案

### Option A — Decomposer 默认 anchors 注入顶层目录前 N 项

**Essence**：`_DEFAULT_ANCHORS_STANDARD["arch"]` 不再是空 tuple；当兜底（或验证后空）时，从 `repo_overview.top_level_paths` 取前 4-6 个目录作为 anchors。这样 Investigator 看到 arch sub-topic 的 anchors_json 会变成 `["api/", "deep_research/", "memory/", "tools/"]` 之类的具体路径，prompt 中"路径优先选 anchors 中已有的"立刻起作用。

但有依赖：**先要让 `top_level_paths` 不为空**（即修复 `_make_overview_proxy` 不解析它的 bug，RECON-B Severity-3）。否则 anchors 还是没有可用源。

- **Insertion**:
  - `deep_research/deep_research_loop.py:93-118` 的 `_make_overview_proxy`：补上对 `- top_level_paths:` / `- entry_candidates:` YAML 子块的解析（≈12 行）。
  - `deep_research/agents/decomposer.py:31-37` 的 `_DEFAULT_ANCHORS_STANDARD["arch"]`：改成函数化默认或在 `_validate_subtopics` / `_fallback_subtopics` 里按 `reachable[:N]` 注入。需要把 `reachable` 透传进去（≈4 行）。
- **Pollution**: 数据 / 代码层（**无任何 prompt yaml 改动**）
- **Reliability uplift**: 中-高。Investigator 看到具体路径列表是强信号；它会大概率 `list_dir(top_dir)` 或对应路径的 read。但仍然不保证一定选 `list_dir({"path":"."})`。
- **Side effects**: stack/why 等节也会受益（它们 anchors 默认是 `("README.md",)`，不变）；`flow` 默认空 tuple，会同样注入；short 分支不受影响。
- **Reversibility**: 1-2 个文件、≈15 行总量。回退把改动逐字 revert 即可。
- **AGENTS.md compat**: §3.2（"anchors 必须落在 `top_level_paths` ∪ `entry_candidates.path`"——本质上就是把已经合法的路径塞回去）；§7.2 不变；§12.3 不变。
- **Diff sketch**:

```python
# deep_research_loop.py:_make_overview_proxy 内追加（在 file_count 解析循环后）
in_paths_block = False
for raw_line in text.splitlines():
    line = raw_line.rstrip()
    if line.strip().startswith("- top_level_paths:"):
        in_paths_block = True
        continue
    if in_paths_block:
        if line.startswith("  - "):
            proxy.top_level_paths.append(line[4:].strip())
        elif line.startswith("- "):
            in_paths_block = False
# 同理解析 - entry_candidates: 子块
```

```python
# decomposer.py:_fallback_subtopics（以及 _validate_subtopics 兜底分支）
def _arch_default_anchors(reachable: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(p for p in reachable if p.endswith("/"))[:6] or ()
```

### Option B — 在 arch sub-topic 第 1 轮"预投喂"一次 list_dir（确定性）

**Essence**：`DeepResearchLoop._run_investigate_phase` 在每次 `subtopic.id == "arch"` 进入 round 1 之前，**先确定性**调一次 `list_dir({"path":"."})`，把 result 当作"零号轮"原始素材塞进 `scratchpad.add_note(... raw_observation=...)`，再合成一段固定模板的 NoteTaker 笔记（不调 LLM，纯文本拼接如"顶层一共有 N 块：A、B、C ...，下面我们一个个看"），随后正常进入 LLM 驱动的 round 1+ ReAct。

- **Insertion**: `deep_research/deep_research_loop.py:253-323` 在 `for index, subtopic ... cancellation_token.raise_if_cancelled()` 之后、`policy.reset_failure()` 之前插入：

```python
if subtopic.id == "arch":
    pre_result = await self._tool_runtime.execute(
        "list_dir", {"path": "."}, ctx=ctx
    )
    if pre_result.success:
        text = "我们先扫了一眼仓库顶层布局：\n" + (pre_result.content or "")[:1800]
        prefab_note = SubtopicNote(text=text[:600], success=True,
                                   anchor_path=".", anchor_lines=None)
        scratchpad.add_note(subtopic.id, 1, prefab_note,
                            raw_observation=pre_result.content)
        # 注意：现有 round_idx 计数从 1 开始；这里我们已经"用掉"了 round 1
        # 后续 ReAct 从 round_idx=2 起跑，且 raw_observation 已落档
```

需配合微调 `for round_idx in range(1, ...)` 起点（如果 arch 已预占 round 1，则从 2 开始）。或者更干净地：把这一步当作 round 0，不计入 max_rounds 配额。

- **Pollution**: 仅 Python 代码层（**无任何 prompt yaml 改动**）。
- **Reliability uplift**: 高。100% 保证 Composer 拿到 arch 的 raw_first_round + 一段已经写明顶层布局的笔记，"列目录"几乎无可避免。
- **Side effects**: arch 的 ReAct 配额从 2 减到 1 (因占用了 round 1)；可以选择 `max_rounds=3` 仅在 arch 时；或者把这一步存成 round 0 不计配额。tool_call 计数 +1，LLM call 节省 1（NoteTaker 笔记走 prefab，不调 LLM）。Phase 2 成本反而下降。
- **Reversibility**: 单文件 ≈15 行，干净 if 块包裹，回退一刀切。
- **AGENTS.md compat**: §3.3 描述的 ReAct 是软要求；§3.4 Composer 上下文需要 `notes_by_id` + `raw_first_round_by_id`，本方案标准供给。注意：§7.2 教师腔基调不变（prefab 笔记本身就用教师口吻）；§12.1 cancellation 检查点不变（在 sub-topic 起点就已 check）。
- **Diff sketch**: 见上"Insertion"段。

### Option C — Composer user_template 加 `{top_level_directories}` 数据块

**Essence**：纯数据 nudge。`scratchpad.build_compose_context()` 多塞一个 `top_level_directories: list[str]` 字段，从 `repo_overview` 派生。Composer user_template 在末尾加一个标签段："\n\n本仓库顶层目录素材（参考用，不强制复述）：\n- a/\n- b/\n- c/\n"。**system prompt 不动**——只是数据放在它面前，让它自然取用。

为了保留现有 build_compose_context 签名稳定，可以从 `_run_compose_phase` 把 `top_level_directories` 通过 `composer.stream` 的额外 kwarg 传入；或者扩展 `build_compose_context(*, top_level_paths=())`。

- **Insertion**:
  - `deep_research/deep_research_loop.py:325-336` `_run_compose_phase`：从 `_StringOverview.top_level_paths` 取派生（依赖 Option A 的 proxy 修复）。
  - `deep_research/agents/composer.py:88-103` `stream` 增加 `top_level_directories: tuple[str,...] = ()` 参数；在 `user_prompt` format 中追加 placeholder。
  - `deep_research/prompts/zh/compose.yaml:50-67` 的 user_template 末尾追加：

```yaml
本仓库顶层目录素材（仅作参考；如果你判断对学生有帮助，自然提到即可）：
{top_level_directories_block}
```

- **Pollution**: user_template **数据块**（不是指令）。比 Option D 更弱的污染——只是把数据放在 LLM 鼻子下，没有任何"必须列出"字眼。
- **Reliability uplift**: 中。Composer 看到一段醒目的"顶层目录素材"很可能在 arch 节自然引用，但仍是 LLM 自由裁量。
- **Side effects**: Composer prompt 体积增加 ~300 字（≤20 个目录×平均 15 字）；§12.3 总预算 30KB 充足。可能带来副作用：Composer 在其它支柱里也提目录，但这通常是教学加分项。
- **Reversibility**: 跨 3 个文件，但每处改动 ≤5 行。
- **AGENTS.md compat**: §3.4 描述的 Composer 输入"`RepoOverview.text` 轻上下文" 已经默许了这种弱注入；§7.1 反模式禁的是"必须严格根据证据"——本方案没有任何此类基调；§12.3 总预算稳。

- **Diff sketch**:

```yaml
# compose.yaml 末尾追加
本仓库顶层目录素材（仅作参考；自然提及即可，不强制复述）：
{top_level_directories_block}
```

```python
# composer.py:stream
async def stream(self, *, report_shape, repo_overview_text, scratchpad_context,
                 top_level_directories: tuple[str, ...] = ()) -> AsyncIterator[str]:
    block = "\n".join(f"- {p}" for p in top_level_directories) or "(暂无)"
    user_prompt = self.get_prompt("user_template").format(
        ..., top_level_directories_block=block,
    )
```

```python
# deep_research_loop.py:_run_compose_phase
async for delta in self._composer.stream(
    report_shape=decision.report_shape,
    repo_overview_text=repo_overview_text,
    scratchpad_context=scratchpad.build_compose_context(),
    top_level_directories=tuple(getattr(overview_obj, "top_level_paths", ()) or ()),
):
```

### Option D — Investigator user_template 在 anchors=[] 时加一行"建议先看顶层结构"

**Essence**：在 `investigator.py:_render_user_prompt` 渲染时，如果 `subtopic.anchors` 为空且 `subtopic.id in {"arch", "flow"}`，在 user_template 末尾追加一句"如果你还没扫过仓库顶层结构，先选 list_dir 看一眼通常会很高效"。**system prompt 不动**。

- **Insertion**: `deep_research/agents/investigator.py:90-113`（`_render_user_prompt`）+ `prompts/zh/investigate.yaml`（新增可选 placeholder `{hint_block}` 或者直接在 Python 里拼末尾）。
- **Pollution**: user_template **指令**（比 Option C 强）。仍不污染 system prompt。
- **Reliability uplift**: 中。条件指令直接命中场景，但仍是 LLM 自由意志，不能做硬决定。
- **Side effects**: 无明显副作用——arch / flow 已经是天然适合先 list_dir 的两节。
- **Reversibility**: 1 个文件 ≈8 行，配合 yaml 1 处。
- **AGENTS.md compat**: §7.1 反模式 ✅（只是建议，不是"必须"）；§7.2 不变；§3.3 决策方针明面上也写了 "anchors 空时，可以从概览里挑最像入口的一处"——本方案是把这条建议从软变硬。

- **Diff sketch**:

```python
# investigator.py:_render_user_prompt
hint = ""
if not subtopic.anchors and subtopic.id in {"arch", "flow"}:
    hint = "\n\n小提示：这一支柱目前还没有任何笔记 / anchors，先用 list_dir " \
           "扫一下仓库顶层的目录布局通常很高效。"
return template.format(...) + hint
```

## 推荐

**主推：Option B（arch 预投喂 list_dir）**

理由：
1. **可靠性几乎是 100%**——直接消除"看运气"，每次都把 raw_first_round + 一段教师腔笔记摆在 Composer 面前。
2. **零 prompt 污染**——纯代码层 if 块，system prompt 完全不动，user_template 也不动；符合"不大改 / 不强制 / 不污染系统 prompt"硬约束。
3. **成本反而下降**——把一次 LLM 驱动的 NoteTaker 调用换成一段 prefab 文本，节省 1 次 LLM call；arch 节质量同时上升。
4. **回退简单**——单文件 if 块，5 分钟可恢复。
5. **不破坏其它节**——条件 `subtopic.id == "arch"`，stack/why/flow 不受影响；测试只需新增 1 个 case 验证 prefab 存在。

**兜底：Option A（默认 anchors 注入顶层目录）**

理由：
- 即使 Option B 上线后效果在 30%+ 样本上不达标（如 LLM 仍写不充分），叠加 Option A 让 Investigator 后续 round 2 拿到的 anchors 仍是合法路径，能补充更深一层的"每个目录在干嘛"信息。
- Option A 单独上线在没修 `_make_overview_proxy` 之前没有任何意义——它和 RECON-B Severity-3 是双胞胎；修了 proxy 也是顺便修了多语言判定（让 polyglot 支柱终于能触发）。

如果用户偏好"完全在 LLM 自主决定下做柔性引导"，可以改主推 Option C；但 C 的天花板低于 B（仍是软建议）。如果想要最最最低改动量，单独上 Option D 也行，但提升幅度仅"中"。

## 回归保护建议

- 现有 73/73 集成测在 stub LLM 下走完整流程；新增 1 个集成测 case：在 standard 分支跑到 arch 时，断言 `scratchpad.first_round_raw("arch")` 不为 None 且包含 `[dir]` 关键字（适用于 Option B）；或断言 Composer 输入 `top_level_directories_block` 非空（Option C）。
- 真实 LLM 抽检：连续跑 10 次同一仓库 onboarding，人工统计 arch 节是否包含至少 3 个顶层目录名 + 一句"每个目录在干什么"。目标 ≥ 7/10。低于该阈值则叠加兜底方案。
- 不要写 `assert "顶层" in markdown` 一类的硬字数测试——voice prompt 只是建议项不是合同（§13 / AGENTS.md 末行）。

## 关键文件 / 行号一览（chief engineer 直接动手用）

| 用途 | 路径 | 行 |
| --- | --- | --- |
| Overview 文本生成器（已含 top_level_paths） | `repo/overview_builder.py` | 46-76 / 130-133 |
| 字符串 → 对象 proxy（漏解析路径） | `deep_research/deep_research_loop.py` | 84-118 |
| Decomposer arch 默认 anchors=空 | `deep_research/agents/decomposer.py` | 31-37 |
| Decomposer prompt 占位符 | `deep_research/prompts/zh/decompose.yaml` | 60-67 |
| Investigator user_template | `deep_research/agents/investigator.py` | 100-113 |
| Investigator prompt | `deep_research/prompts/zh/investigate.yaml` | 35-60 |
| NoteTaker list_dir 锚点 | `deep_research/agents/note_taker.py` | 81-83 |
| Loop ReAct 主循环 | `deep_research/deep_research_loop.py` | 253-323 |
| Compose 入口 | `deep_research/deep_research_loop.py` | 325-411 |
| Composer stream 渲染 | `deep_research/agents/composer.py` | 88-172 |
| Compose user_template | `deep_research/prompts/zh/compose.yaml` | 50-67 |
| list_dir 工具实现 | `tools/list_dir.py` | 32-141 |
| Scratchpad build_compose_context | `deep_research/research_scratchpad.py` | 98-138 |
