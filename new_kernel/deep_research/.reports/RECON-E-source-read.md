# RECON-E · 工具与读源码倾向 侦察

## What

侦察 deep_research Investigator "不爱读源码、爱列目录" 的现象。结论:**工具层完全具备读源码能力(`read_file_range` 带行号、`search_repo` 带行片段、`find_references` 带前后文)**,但 **prompt 层没有任何一行把 LLM 推向"读源码胜过列目录"**;更糟糕的是,FIX-03 落地后 arch 的 anchors 全是目录(`api/`、`tools/` 这种),叠加 prefab 笔记开头"我们先扫了一眼仓库的顶层布局..."这段提示, **round 2 的 LLM 路径最阻力最小的动作正是再 `list_dir` 一次更深的目录**——而 arch 偏偏只剩 1 轮可用。

## 工具清单

来源:`tools/__init__.py:22-30` 的 `build_default_tools()`,运行时通过 `ToolRuntime` 注册;`valid_actions` = 5 个工具名 + 别名 + 控制动作 `done`(`tool_runtime.py:50-51`)。

| 工具 | 返回内容 | 读源码吗 | 截断 |
| --- | --- | --- | --- |
| `read_file_range(path, start_line, end_line)` | **每行 `N: <line>` 形式的源码片段**,原汁原味带行号 (`read_file_range.py:111-114`) | **是**——这是最直接读源码的工具,行号让 LLM 能明确引用 | 默认 `ctx.max_lines=200` 上限 (`tool_protocol.py:10`),metadata 标记 `truncated=True` |
| `search_repo(pattern, glob?)` | `path:line: <preview>` 每行最多 320 字符 (`search_repo.py:154-156`) | **是**——直接返回匹配行的 320 字符代码片段 | `ctx.max_search_hits=30` 上限,`MAX_SCANNED_FILES=5000` 文件数上限 |
| `list_dir(path?, recursive?)` | `[dir]  rel/`、`[file] foo.py (123 bytes)` 行 (`list_dir.py:194-197`) | **否**——只暴露名字 + 大小,不沾源码一字 | `ctx.max_search_hits=30` 上限,recursive 时深度 ≤ 4 |
| `summarize_file(path)` | LLM-generated 总结(`summarize_file.py:119-132`)或启发式提要(`File:` / `Lines:` / `Key symbols:` / `Opening context:`,`summarize_file.py:153-166`) | **间接**——读了源码但 LLM 已经压缩成自然语言;**LLM 看到的是"答案"不是"原文"** | 默认头 70% / 尾 30% 比例切片,然后 LLM 概要 |
| `find_references(symbol, glob?)` | 多行块:`path:line` + 前一行 + `> <匹配行>` + 后一行 (`find_references.py:158-165`) | **是**——带前后 1 行上下文的代码片段 | 30 hit 上限 |

**关键事实**:工具层提供了 3 件事都能读到源码的 reader(`read_file_range`、`search_repo`、`find_references`),且都包含**行号**或**路径行号坐标**;Investigator 看到的 `tools_description` 表格(`tool_runtime.py:118-139`)对每个工具都有 `when_to_use` 字段(例如 `read_file_range` 的 `Use when you need exact source code from a known path and line range.`),信息完整。**问题不在工具层。**

## 现状:anchors → 动作 链路(按 sub-topic)

### what / stack / why

- 默认 anchors:`("README.md",)` (`decomposer.py:32-36` `_DEFAULT_ANCHORS_STANDARD`)
- 这是**文件**型 anchor,Investigator 看到时最自然的动作就是 `read_file_range({"path":"README.md", "start_line":1, "end_line":80})` ——投喂"具体文件"是强信号,几乎不会去 `list_dir(README.md)`(也跑不通,因为不是目录)。
- 唯一隐患:三个支柱共享一个 anchor `README.md`,LLM 第三次轮到 why 时会觉得"这文件刚读完"(notes_history 累积),倾向 `done`。但**至少读过一次源码**。

### arch (FIX-03 落地后的关键变化)

- 原 anchors:`()` 空 tuple。
- 现在:`_arch_default_anchors(reachable)` 返回 `tuple(p for p in reachable if p.endswith("/"))[:6]`(`decomposer.py:40-52`)——**全是目录**。
- FIX-03 还在 round 1 之前**确定性**调一次 `list_dir(".")`,把结果当 `raw_observation` + 一段以"我们先扫了一眼仓库的顶层布局,看看一共分了几大块:\n[dir]  api/\n[dir]  deep_research/\n..."开头的 prefab 笔记落档(`deep_research_loop.py:328-351`)。
- arch 的 ReAct 循环 `start_round = 2 if arch_pre_seeded else 1`(`deep_research_loop.py:354`),`max_rounds_per_subtopic=2`(`deep_research_loop.py:194`)——所以 **arch 只剩 1 轮 LLM ReAct 可用**。
- (a) Round 2 时 Investigator 的 user_template 输入:
  - `subtopic_anchors`:`["api/", "deep_research/", "tools/", ...]`(全是目录)
  - `notes_history`:`轮1:\n我们先扫了一眼仓库的顶层布局,看看一共分了几大块:\n[dir]  api/\n[dir]  deep_research/\n...`
  - `repo_overview_text`:仍然包含完整 `- top_level_paths:` 章节
- (b) 给定上面输入,**最自然的下一步**:
  - 选项 X: `list_dir({"path":"api/"})`——继续展开一层目录,prompt 完美允许("能 list 一个具体目录就不要 search 全仓",`investigate.yaml:28`),anchors 里有现成路径。
  - 选项 Y: `read_file_range({"path":"api/<某个具体文件>"})`——但 anchors 里**没有具体文件**,LLM 得自己脑补一个文件名,而 prompt 里的"路径优先选 sub-topic 的 anchors 中已有的"(`investigate.yaml:27`)直接劝退这条路径。
  - 选项 Z: `read_file_range({"path":"README.md"})`——但 prefab 笔记已经显示这是导览支柱,且 README 在 what/stack/why 里读过,notes_history(空)/通用观感都不优先这一条。
- (c) Investigate prompt 里关于"anchors 是目录还是文件"的引导:**没有**。`investigate.yaml:27-28` 说"路径优先选 anchors 中已有的"+"能 list 一个具体目录就不要 search 全仓",这两条**都鼓励**选项 X(继续 `list_dir`),没有任何一行说"如果 anchors 全是目录,挑一个里面的代表文件 read 一下"。

### flow

- 默认 anchors:`()` 空 tuple (`decomposer.py:36`)。
- LLM 真正自由发挥的支柱;`investigate.yaml:27` 软建议"如果 anchors 空,可以从概览里挑最像入口的一处"。
- entry_candidates 现在被解析进 `_StringOverview`(`deep_research_loop.py:128-134`),所以 LLM 在 prompt `repo_overview_text` 里能看到 `entry_candidates: README.md (markdown): top-level readme / src/main.py (python): primary entry` 之类的具体文件。
- 实际行为:LLM 通常会选 `read_file_range({"path":"<某个 entry 候选>", "start_line":1, "end_line":80})` ——这里**会读源码**,因为 entry_candidates 是文件(不是目录)。
- 风险点:flow 没有 prefab 笔记,没有目录列表"在等着它继续展开",所以反而比 arch 更容易读到源码。

## 假设与证据:为什么不爱读源码?

### (a) Prompt 层证据(投票:列目录 ≥ 读源码)

`investigate.yaml:23-28` 的"决策方针":

```
- 路径优先选 sub-topic 的 anchors 中已有的;如果 anchors 空,可以从概览里挑最像入口的一处。
- 范围尽可能小:能读 50 行就不要读 500 行;能 list 一个具体目录就不要 search 全仓。
```

第二条**明确把 `list_dir` 列为节流首选**——"能 list 一个具体目录就不要 search 全仓"是在 list_dir vs search_repo 之间二选一的"省钱"指令,但 LLM 容易把它泛化为"list_dir 是更稳的动作"。**整个 prompt 没有任何一行说"读 50 行源码胜过 list 一层目录"**——读源码只在 system 提示里出现一次"我想看看这个入口文件到底怎么把请求接进来的"(`investigate.yaml:8`)作为意图举例,但这是**形象化**而非**指令**。

`investigate.yaml:27`("路径优先选 anchors 中已有的")是**强约束**;当 anchors 全是目录时,这条直接锁死"必须选目录里的某条路径"——而能配上目录路径的工具只有 `list_dir`(`read_file_range` 不接目录,`search_repo` 不接路径只接 pattern + glob)。

### (b) Anchor 层证据(arch 的目录 anchors 是结构性偏置)

`decomposer.py:40-52`:

```python
def _arch_default_anchors(reachable: tuple[str, ...]) -> tuple[str, ...]:
    dirs = tuple(path for path in reachable if path.endswith("/"))
    if len(dirs) >= 2:
        return dirs[:6]
    return tuple(reachable[:6])
```

只挑 `endswith("/")` 的目录(线 49),不混任何文件。**结果:arch 的 anchors 100% 是目录**(`api/`, `tools/`, `deep_research/`...)。配合(a)的 prompt 强约束"路径优先选 anchors 中已有的",**Investigator 在 arch 节实际上没有合法路径可以喂给 `read_file_range`**——它要么 `list_dir(目录)` 要么放弃 anchors 去概览里挑文件(违反优先级)。

对照 what/stack/why:它们的 anchors `("README.md",)` 是文件,LLM 顺势 `read_file_range`。**"目录-only anchors"是 arch 独有的反模式。**

### (c) FIX-03 副作用(prefab + 目录 anchors 的合谋)

FIX-03 的设计目的是**保证 arch 节稳定列出顶层目录**。它做到了——但顺带固化了 round 2 的"路径阻力最小"路线。具体证据:

- `deep_research_loop.py:336-338` 的 prefab 笔记开头:`"我们先扫了一眼仓库的顶层布局,看看一共分了几大块:\n" + raw_text`。
- 这段笔记**结尾没有任何引导句**(例如"下一步我们随便挑一个目录展开看一下" / "下面挑 X 这个目录里最像入口的文件读 40 行")。它就在`[dir] tools/`类的列表后戛然而止。
- Round 2 LLM 看到的 user_prompt 有:
  - `notes_history` = 这段不带方向的 prefab 笔记
  - `subtopic_anchors` = `["api/", "deep_research/", "tools/", ...]`
  - prompt 强约束:`"路径优先选 sub-topic 的 anchors 中已有的"`
  - prompt 软约束:`"能 list 一个具体目录就不要 search 全仓"`
- 净效果:**round 2 LLM 最容易选的是 `list_dir({"path":"api/"})` 这种"再深一层目录"**。这是结构性的,跟模型温度无关(温度 0.1,`investigator.py:74`)。
- 因为 arch **总共只有 1 轮 LLM ReAct**(start_round=2, max_rounds=2),这一轮如果用来 `list_dir` 一个子目录,后续就没有机会读源码了。Composer 拿到的 arch 笔记只有"顶层 5 个目录" + "其中 api/ 又有 4 个子文件",**完全没有任何源码引用**。

注:RECON-D-arch-nudge.md 第 123 行已经在更早的侦察里观察到类似结构性现象:"前 3 个支柱(what / stack / why)都已经多次读 README,系统 message 里提示'路径优先选 anchors 中已有的'——arch 没 anchors,LLM 倾向于'再读一遍 src/ 里某个文件'或'读 setup.py / pyproject',list_dir 不是首选"——这是修复**前**的描述。FIX-03 之后,情况翻转:arch 现在有目录 anchors,`list_dir` **变成了首选**,而读文件成了"违反 anchors 优先级"。

### (d) summarize_file 的诱惑(轻度)

`summarize_file` 在 `valid_actions` 里(`tools/__init__.py:24-29` 全部 5 个 reader 都注册),但**实测诱惑度可能不高**:

- `tool_runtime.build_reader_description()`(`tool_runtime.py:118-139`)给的 `when_to_use` = `Use when a file is relevant but too large to inspect line by line first.`,这条 hint 隐性地把它定位成"备选"而非"首选"。
- 它更需要一个**具体文件路径**作为输入(`{"path": "src/app.py"}`),所以同样受制于 anchors 是不是文件。
- 当 anchors 全是目录(arch 的现状),`summarize_file` 也跑不动——还是只能 `list_dir` 一条路。
- **但**:在 what/stack/why 这种 `("README.md",)` anchors 下,summarize_file vs read_file_range 确实存在二选一,LLM 可能选 summarize 来"省事"。这是次要风险,不是主要的"不爱读源码"成因。

## 关键发现

按严重度排:

1. **arch 的 round 2 几乎被结构性锁死成 `list_dir(子目录)`**(决定性):FIX-03 把 arch 的 anchors 改成纯目录,prefab 笔记又把"我们先扫了一眼顶层布局"作为 round 2 的起点上下文,叠加 `investigate.yaml:27-28` 的"anchors 优先 + list 优于 search"双约束,LLM 在 round 2 选 `list_dir(目录)` 的概率显著高于 `read_file_range(目录里某文件)`。**arch 总共只有 1 轮 LLM ReAct**,这一轮一旦花在再 list 一层,就没有机会读源码了。
2. **investigate.yaml 没有任何"读源码胜过列目录"的引导**:整个 system + user_template 找不到一句"碰到目录 anchors 时建议挑代表文件读 40 行"或"读源码比单纯 list 更能交付教学价值"。`read_file_range` 这个工具名在 prompt 里**从未出现**(grep 验证零命中);相反 `list_dir` 在第 28 行被作为节流首选明确点名。
3. **Decomposer 的 anchors 设计偏目录**:`_DEFAULT_ANCHORS_STANDARD` 里 what/stack/why = `("README.md",)`(单一文件,且是同一个);arch = `_arch_default_anchors`(只挑目录);flow = `()`(空)。整体不存在"安插一个代表性源文件作 anchor"的策略。
4. **Composer system prompt 不要求引用具体源代码**:`compose.yaml` 第 24-32 行只要求"按 sub-topic 顺序展开"+"架构节 1.5-2 倍篇幅"。第 13 行有"主动引导读者动手:'你现在打开 X 文件,从第 Y 行开始读,注意 Z 这个细节'"的语气示范,但这是**口吻**而非**输入要求**——如果上游 notes 里没有任何源码引用,Composer 也写不出"第 Y 行"。
5. **summarize_file 的诱惑次要但存在**:它确实是一个"读了源码但替你压缩"的近似偷懒选项;但实际触发条件需要文件型 anchors,在 arch 节因 anchors 全为目录而无效,主要风险集中在 what/stack/why 三节。
6. **flow 节反而读源码概率高于 arch**:flow 默认 anchors `()` + entry_candidates 解析后含具体文件 + `investigate.yaml:27` 软引导"挑最像入口的一处"——LLM 倾向 `read_file_range(entry_path)`。这从侧面证明问题不是模型本身懒,而是 anchors 形态决定动作形态。

## 候选改进方向(仅记录,不实现)

按"侵入度 × 提升幅度"排序,从轻到重:

- **D1 — Decomposer arch 默认 anchors 文件 + 目录混合**:`agents/decomposer.py:40-52` `_arch_default_anchors` 现在只挑 `endswith("/")` 的目录;改成"前 3 个目录 + 前 3 个非目录(优先 entry_candidates 里的源代码文件)",让 round 2 LLM 在 anchors 里既能 `list_dir(api/)` 也能 `read_file_range(api/main.py)`。**侵入度:1 个文件 ~10 行**;**提升:中-高**——把"目录-only"打破即可。无需动 prompt yaml。
- **D2 — investigate.yaml user_template 末尾追加一行条件 hint**:在 `agents/investigator.py:_render_user_prompt` 渲染时(不动 yaml,直接 Python 拼末尾),如果 `subtopic.anchors` 全是目录(`all(a.endswith("/") for a in anchors)` 且非空),追加一句:"提示:这一步 anchors 全是目录,如果你想真正讲清这个支柱,挑其中一个目录里最像入口的源文件 read 40 行通常比再 list 一层更有价值。" **侵入度:1 个文件 ~5 行**;**提升:中**——LLM 在条件命中时获得明确引导。RECON-D 的 Option D 升级版,且不动 yaml。
- **D3 — FIX-03 prefab 笔记末尾追加引导句**:`deep_research_loop.py:336-338` 的 `prefab_text` 现在以原始 `[dir]/[file]` 行结尾,改成在末尾加一句教师腔:"\n\n下一步我们挑 X 这个目录里最像入口的源文件展开看一下,这样比单纯列目录更能讲清整体怎么搭。" 其中 X 可由代码层从 entry_candidates 里挑。**侵入度:1 个文件 ~3 行**;**提升:中**——直接给 round 2 LLM 接力的方向。要求 entry_candidates 已被解析(FIX-03 已修复)。
- **D4 — 提升 arch 的 max_rounds 到 3,只针对 arch**:`deep_research_loop.py:354-355` 的 `start_round = 2 if arch_pre_seeded else 1`,如果 pre-seeded 把 round 2..3 都给 LLM,等于回补 arch 因 prefab 而损失的 1 轮 LLM 配额,让它至少有"先 list_dir 子目录,再 read_file_range 文件"两步。**侵入度:1 个文件 ~3 行**;**提升:中-高,但成本 +1 LLM call/turn**;不动 prompt。
- **D5 — Composer user_template 加一行"请引用至少 1 处源代码片段"**:`compose.yaml:50-67` user_template 末尾追加"\n\n如果 notes 或 raw materials 中有具体源代码片段,请在每个支柱至少自然引用 1 处(用 `path:line` 形式);若实在没有,改为引导读者打开某个文件的某个行段。" **侵入度:1 处 yaml 末尾**;**提升:中**——把 Composer 写"打开 X 文件第 Y 行"这一既有口吻从软变实。但用户禁修 Composer,先记不实现。
- **D6 — investigate.yaml 顶部决策方针补一行(用户禁修 yaml,所以本条仅记录)**:在 `investigate.yaml:23-28` 决策方针块插入一条:"- 当 anchors 中有具体源文件路径时,优先 `read_file_range`(读源码)而不是 `list_dir`/`summarize_file`;通读源码的 30-50 行往往比看一层目录更能交付教学价值。" **侵入度:yaml 1 行**;**提升:高**(直接对症)。但 RECON-E 任务约束"不修代码不修 yaml",此项仅作为对照基线。

## 待用户确认 / 后续动作

1. **arch 节是否值得多花 1 个 LLM call 换一轮真正的源码阅读?** D4 把 max_rounds=3-only-for-arch 是最直接的"补回 prefab 偷掉的那一轮"做法,但每个 turn 多 1 次 LLM call。如果用户愿意接受这点成本上行,D4 + D1 组合最稳。
2. **是否允许在 prefab 笔记结尾追加"接下来我们挑 X 文件展开"这种引导句?** D3 是改动最小、对当前 round 2 路径影响最大的方案,但 prefab 文本目前严格只有"我们先扫了一眼顶层布局\n<list_dir 原文>",加引导句会让 prefab 不再是纯客观素材,稍微变厚。如果用户觉得这条 OK,优先 D3 + D1。
3. **arch 的 anchors 是否可以混入文件(D1)?** 这是把 RECON-D 的"arch 必须列目录"翻译成"arch 既列目录也指几个文件",和 FIX-03 的目录预投喂不冲突,但需要确认用户认为"混合 anchors"不会让 LLM 重复读 entry_candidates 已经在 what/stack 节读过的 README。如果同意,D1 几乎是零代价收益方案。
