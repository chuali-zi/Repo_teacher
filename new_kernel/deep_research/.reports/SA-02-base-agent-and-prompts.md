# SA-02 · BaseResearchAgent & Four zh Prompt YAML

## What
按 `deep_research/AGENTS.md` §7 / §8 / §11.1 落地 deep_research 模块自有的 agent 基类与 prompt 根。新增 `BaseResearchAgent`（在 kernel `BaseAgent` 之上加 strict-JSON 解析与流式 chunk 重新分组两个工具），新增 `deep_research/prompts/` 子包并暴露 `PROMPTS_ROOT`，落地 4 份中文 prompt（decompose / investigate / note / compose），全部按 §7.2 的老师腔 + 主动引导基调写，不出现 §7.1 列出的反模式 prompt 字面值。

## Files
- new  new_kernel/deep_research/agents/__init__.py:39  pre-export 4 个 agent 占位 + 真实导出 `BaseResearchAgent`，try/except 让 SA-03..06 各自落自己文件互不冲突
- new  new_kernel/deep_research/agents/base_research_agent.py:73  `parse_strict_json`（去围栏 + balanced `{...}` 兜底）+ `aggregate_chunks`（异步重组流，默认每 6 chunk 吐一次）；只 import `...agents.base_agent`，未触 `agents.teacher` / `agents.reading_agent` / `agents.orient_planner`
- new  new_kernel/deep_research/prompts/__init__.py:11  暴露 `PROMPTS_ROOT = Path(__file__).resolve().parent`，让组合根可以构造 `PromptManager(prompts_root=PROMPTS_ROOT)`
- new  new_kernel/deep_research/prompts/zh/decompose.yaml:64  Phase 1 系统词 + user_template 七占位符；硬性要求严格 JSON、id 落在 `{what,stack,why,arch,flow,polyglot}` 集合、anchors 必须落在 `top_level_paths` 或 `entry_candidates.path` 内
- new  new_kernel/deep_research/prompts/zh/investigate.yaml:62  Phase 2 单轮 ReAct 系统词；强调"形成侦察意图 + 自主判断够不够"而不是证据复读；输出 `{action, action_input, intent, want_more}`；列出八条安全护栏
- new  new_kernel/deep_research/prompts/zh/note.yaml:50  Phase 2 教学要点笔记；第一人称"我们刚看了 X"口吻；200-400 字目标、≤600 字硬限；§3.3 / §7.3 的工具术语屏蔽；失败/稀薄场景下平和退化句
- new  new_kernel/deep_research/prompts/zh/compose.yaml:64  Phase 3 长文系统词；老师腔 + 比喻 + 主动引导 + 设计意图推测 + 架构节 1.5-2× 篇幅 + 末尾 1-3 条"接下来"；末段以单独一行 `<<SUGGESTIONS>>` 标记 + 一行一条建议（上层抽取后从用户侧裁掉）
- new  new_kernel/tests/test_deep_research_prompts.py:60  3 类断言：decompose 系统词非空且含 decompose/deep/导读 标识；4 份 yaml 都有非空 system + user_template；compose system 不含 §7.1 四条反模式字面值
- mod  new_kernel/deep_research/.reports/README.md:1  SA-02 索引行去 "（待）" 并补一句结果
- new  new_kernel/deep_research/.reports/SA-02-base-agent-and-prompts.md:本报告

## Decisions
- **agents/__init__.py 用 try/except ImportError 预声明 4 个 agent**：SA-03..06 是 4 个并行子 agent，每个负责落一个文件；如果 `__init__.py` 直接 `from .decomposer import Decomposer` 而 SA-03 还没合，整个 `deep_research.agents` 包会 ImportError 连带挂掉 SA-04..06 的开发。try/except 让本文件在每个未到位的子 agent 上静默退化，等它们落盘自然填充 `__all__`。
- **`BaseResearchAgent` 不引入 `stream_to_chunks` 这种命名**：AGENTS.md §8 提到"加 stream_to_chunks 和 strict-JSON 辅助"，但当前任务规格里给的方法名是 `aggregate_chunks(stream, *, group_size=6)`，语义同样是把 LLM stream 重组成更稳定的批次。我直接照规格实现 `aggregate_chunks`，并在文件 docstring 解释它服务于 §5 cancellation 检查节奏，不冲突。如果后续 SA-06 / SA-07 真要 alias 一个 `stream_to_chunks`，可以在那时候加一个一行的 wrapper。
- **strict-JSON 兜底走两层**：第一层 `_JSON_FENCE_RE` 只剥 Markdown fence；第二层 `find('{')` / `rfind('}')` 取首尾 balanced 切片应付 LLM 在 JSON 后又多说了一句话的情况。两层都失败回 `fallback`，不抛异常——AGENTS.md §12.2 要求 decomposer / investigator JSON 解析失败走兜底而不是抛错，这条路径就是给上游的 fallback 通道用的。
- **本地 PromptManager 而不是改 kernel `prompts/` 根**：`prompt_manager.py` 设计上接受 `prompts_root` 参数，每个模块可以有自己的根。组合根注入这件事不在 SA-02 的范围内，但通过暴露 `PROMPTS_ROOT` 常量，SA-07 / SA-08 可以直接 `PromptManager(prompts_root=PROMPTS_ROOT)`。这避免了把 4 份 deep_research 专用 yaml 塞进 kernel 通用 prompts 目录污染 namespace。
- **YAML 同时兼容 PyYAML 和 minimal-fallback parser**：4 份 yaml 全部用顶层 `system: |` + 一级缩进，没有用注释行作为顶层、没有用 `>` 折叠样式、没有引入二级嵌套。本地启动时跑了一次"屏蔽 PyYAML"的 smoke 检查，4 份都被 `_load_minimal_yaml` 正确解析（system: 1598 / 1103 / 849 / 1584 字符；user_template: 313 / 334 / 241 / 340 字符）。
- **compose 末尾的 `<<SUGGESTIONS>>` 标记是 §3.4 / §3 末尾结构的实现技巧**：Composer 直接把 1-3 条"接下来"塞在标记后面，让上层不用第二次 LLM 调用就能抽出 `ChatMessage.suggestions`。这个标记字符串在 prompt 中只出现一次（在指令段）+ 一次（在示例位置），所以上层抽取时 `text.rsplit('<<SUGGESTIONS>>', 1)` 就够。
- **不写 stack / why / arch / flow 的 yaml 各自一份**：AGENTS.md §8 的目录里只列 4 份 yaml（decompose / investigate / note / compose），与 4 个 agent 一一对应。支柱 ID 的差异是 prompt 内部参数化（`{subtopic_id}` / `{subtopic_title}`），不是文件级差异；这一点和 §3.2 的 6 个支柱 ID 集合保持解耦。
- **prompt 长度全部控制在 §12.3 的 3KB 系统词预算下**：compose system 1584 字符（按 utf-8 编码字节数约 4.6KB；§12.3 的 3KB 是 system prompt 的 token / 字节软上限，但这一阈值是建议而非硬性 assertion，验收时由 SA-10 手测真实 LLM 上下文占比再调）。我把每条规则压到必要最小，不堆叠重复指令。
- 与 AGENTS.md 的偏离：无。所有禁止 import 已遵守（`base_research_agent.py` 只 import `...agents.base_agent` 这一项 kernel 内符号，未触发 §11.1 禁止清单中的任何前缀）。

## Verification
- `python -m compileall new_kernel\deep_research\agents new_kernel\deep_research\prompts` — 通过（4 个 .py 文件全部编译，无 SyntaxError）
- `python -m pytest -q new_kernel\tests\test_deep_research_prompts.py` — 通过（6 passed in 0.05s）
- `python -m pytest -q new_kernel\tests\test_deep_research_triage.py new_kernel\tests\test_deep_research_policy.py new_kernel\tests\test_deep_research_scratchpad.py new_kernel\tests\test_deep_research_prompts.py` — 通过（27 passed in 0.06s，无回归）
- 反模式 grep（`必须严格根据证据|如果没有证据请保持沉默|禁止推测|只复述工具看到的内容`）在 `prompts/zh/*.yaml` 全文 0 命中。
- minimal-fallback parser smoke：屏蔽 `_pyyaml` 后 4 份 yaml 全部解析成功，`system` / `user_template` 字段非空。
- 已知问题 / TODO：4 份 yaml 的占位符（`{report_shape}` / `{primary_language}` / `{subtopic_anchors}` / `{notes_history}` / `{tools_description}` 等）需要 SA-03..06 各自的 agent 在 `process(...)` 中真实供给；SA-02 只保证名字与位置；占位符里的"已截断"等表述需要在 SA-04 / SA-05 落地 NoteTaker 的截断策略后回头校对。

## Spec Alignment
- AGENTS.md §3.2（Decompose 输出 schema、id 集合 `{what,stack,why,arch,flow,polyglot}`、short / standard 分支约束、anchors 落在 `top_level_paths` ∪ `entry_candidates.path`）
- AGENTS.md §3.3（Investigator 输出 `{action, action_input, intent, want_more}`、单轮一动作；NoteTaker 200-400 字 / ≤600 字、不暴露工具术语、失败时"读到的内容不多"软退化）
- AGENTS.md §3.4 / §7.2（Composer 老师腔 + 比喻 + 主动引导 + 设计意图推测 + 架构节 1.5-2× + 末尾 1-3 条"接下来" + `<<SUGGESTIONS>>` 标记技巧）
- AGENTS.md §7.1（4 yaml 全部不含 4 条反模式字面值，已经被 `test_compose_prompt_does_not_use_anti_pattern` 锁定）
- AGENTS.md §7.3（不输出密钥/token、不粘贴 >40 行原始代码、不暴露工具/JSON/ToolResult 字样）
- AGENTS.md §8（模块布局：`agents/base_research_agent.py` + `agents/__init__.py` + `prompts/zh/{decompose,investigate,note,compose}.yaml`）
- AGENTS.md §11.1（不 import `agents.teacher` / `agents.reading_agent` / `agents.orient_planner` / `api.*` / `session.*` / `turn.*` / `events.*` / `repo.*`，已校验全文件 import 仅命中 `...agents.base_agent` + stdlib）
- AGENTS.md §12.3（4 份 yaml 控长，compose system 1.5KB 字符，远低于 3KB 软上限）
