# DeepResearch Long Report Diagnosis

> 日期：2026-04-20  
> 目标：解释为什么当前 deepresearch 导读会产出“机械引用、英文、教学价值弱”的结果  
> 结论先行：这不是单纯的 prompt 没调好，而是当前 deepresearch 分支在架构上根本不是“中文教学长报告生成器”，而是“后端确定性英文摘要器”。

## 1. 核心结论

当前 `deep_research` 模式的问题，不是模型偶尔发挥失常，而是整条链路的主设计目标和你的目标不一致。

你的目标是：

- 产出中文
- 至少 3000 字
- 面向教学
- 讲清楚项目架构、设计动机、模块协作、数据结构、解耦方式、实现细节、优缺点与阅读路径
- 允许全面分析代码并形成成型报告

当前实现的真实目标是：

- 在不重新引入旧版静态骨架的前提下
- 用保守、确定性的方式
- 快速拼出一份“基于文件树和 AST 轮廓的 repo map”
- 让用户知道下一步看什么

这两者不是同一个产品。

## 2. 现有 deepresearch 的真实执行链路

当前 deepresearch 入口在 `backend/m5_session/analysis_workflow.py`。

- 只有当 `analysis_mode == deep_research` 且仓库主语言是 Python 时，才会走 deepresearch 分支，见 `backend/m5_session/analysis_workflow.py:117-118`
- deepresearch 主流程在 `_build_deep_research_initial_report()`，见 `backend/m5_session/analysis_workflow.py:199`
- 该流程的四个阶段是：
  - `Planning the deep research pass.`，见 `backend/m5_session/analysis_workflow.py:209`
  - `Sweeping selected source files.`，见 `backend/m5_session/analysis_workflow.py:230`
  - `Synthesizing chapter notes.`，见 `backend/m5_session/analysis_workflow.py:264`
  - `Writing the deep research report.`，见 `backend/m5_session/analysis_workflow.py:290`

但这里的 “Writing the deep research report” 并不是调用大模型写一篇中文长报告，而是调用 `backend/deep_research/pipeline.py` 中的确定性字符串拼接逻辑。

关键证据：

- `build_research_packets()` 只是收集包，见 `backend/deep_research/pipeline.py:55`
- `build_group_notes()` 生成 group note，见 `backend/deep_research/pipeline.py:67`
- `build_synthesis_notes()` 生成固定章节 note，见 `backend/deep_research/pipeline.py:114`
- `render_final_report()` 直接把字符串拼成最终 Markdown，见 `backend/deep_research/pipeline.py:237`
- `build_initial_report_answer_from_research()` 只是把上述结果包成 `InitialReportAnswer`，见 `backend/deep_research/pipeline.py:297`

也就是说，当前 deepresearch 根本不是 “LLM based long report generation pipeline”，而是 “deterministic research-note renderer”。

## 3. 为什么输出会是英文

答案非常直接：因为当前 deepresearch 可见文本就是英文硬编码。

关键证据：

- 报告标题是 `# Deep Research Report: {repository.display_name}`，见 `backend/deep_research/pipeline.py:245`
- 报告前言是英文硬编码，见 `backend/deep_research/pipeline.py:247`
- 章节标题全部是英文硬编码：
  - `Repository Verdict`，见 `backend/deep_research/pipeline.py:138`
  - `Reading Framework`，见 `backend/deep_research/pipeline.py:151`
  - `Directory and Module Map`，见 `backend/deep_research/pipeline.py:160`
  - `Entry and Startup Path`，见 `backend/deep_research/pipeline.py:171`
  - `Core Flows`，见 `backend/deep_research/pipeline.py:183`
  - `Key Abstractions and State`，见 `backend/deep_research/pipeline.py:192`
  - `Dependencies and Config`，见 `backend/deep_research/pipeline.py:201`
  - `File Coverage Appendix`，见 `backend/deep_research/pipeline.py:212`
  - `Open Questions`，见 `backend/deep_research/pipeline.py:225`
- `Group Notes`、`Research Coverage` 也是英文，见 `backend/deep_research/pipeline.py:268`、`285`
- 建议问题也是英文硬编码，见 `backend/deep_research/pipeline.py:307-317`

因此，当前 deepresearch 输出英文不是模型语言偏好导致的，而是后端直接写死了英文字符串。

补充一点：

- 当前本地模型配置虽然走的是 OpenAI-compatible Chat Completions 接口，默认模型与基座代码位于 `backend/m6_response/llm_caller.py:14-15`
- 但 deepresearch 分支根本不走 `stream_llm_response()` 或 `stream_llm_response_with_tools()` 这条写作链路
- 所以“模型是英文模型”不是这条问题链路的主因

## 4. 为什么内容会显得“机械引用、营养不良”

### 4.1 当前抽取的是“轮廓信息”，不是“教学语义”

`_extract_python_outline()` 只做了非常浅的一层 Python AST 抽取，见 `backend/deep_research/pipeline.py:452`。

它只关心：

- 顶层函数名
- 顶层类名
- import 名

它不关心：

- 谁调用谁
- 状态在哪里流动
- 配置如何注入
- 模块边界为什么这样切
- 哪些数据结构承担了核心职责
- 哪些类/函数是关键协作点
- 设计动机和取舍

这意味着当前 deepresearch 的原材料只足够支撑“目录地图”和“名字列表”，不够支撑“教学型架构分析”。

### 4.2 分组粒度过粗，天然看不到真实模块协作

`source_selection.py` 现在用顶层目录名做 `group_key`，见 `backend/deep_research/source_selection.py:79`。

这会带来三个直接问题：

- `backend/` 这种大目录会被视为一个组，无法分辨 `contracts/`、`routes/`、`m5_session/`、`m6_response/`、`agent_runtime/` 等子系统
- `web/` 也会被视为一个组，无法分辨 `api.js`、`views.js`、`state.js`、CSS 与插件层
- 任何“模块如何连起来”的解释都会退化成“顶层目录有哪些文件”

这和你要的“明确模块、明确功能、明确连接方式”完全不匹配。

### 4.3 报告章节是固定模板，不是按教学问题生成

`build_synthesis_notes()` 当前不是先问“这份教学报告必须回答哪些关键问题”，而是直接生成一组固定章节，见 `backend/deep_research/pipeline.py:114`。

这组固定章节更像“repo scan checklist”，而不是“教学长报告大纲”。

它关注的是：

- 仓库结论
- 阅读框架
- 模块地图
- 启动路径
- 核心 flow
- 配置与依赖
- 文件覆盖率
- 开放问题

它没有把下面这些教学核心问题作为一等公民：

- 为什么项目这样分层
- 为什么用这组数据结构
- 哪些解耦是真正有价值的
- 模块之间靠什么协议协作
- 每个核心模块的职责边界是什么
- 为什么不能把某两个模块合并
- 当前实现的收益和代价是什么
- 新人应该如何建立心智模型

所以现在的内容会像“遍历报告”，不会像“老师讲课”。

### 4.4 可见文本大量来自固定句子，不来自代码语义理解

例如：

- `_repository_verdict()` 直接生成固定句型，见 `backend/deep_research/pipeline.py:521`
- 它甚至包含固定英文句子：`The report is optimized to establish a source-backed mental model before any line-by-line walkthrough.`，见 `backend/deep_research/pipeline.py:526`
- `render_final_report()` 只是把 note 的标题、summary、bullet、evidence files 顺序拼接起来，见 `backend/deep_research/pipeline.py:237-285`

这会导致三个体验问题：

- 每份报告的句式高度同质化
- 代码引用以“路径枚举”形式出现，显得机械
- 即使读了很多文件，也没有真正长出“解释”

### 4.5 抽取出来的 excerpt 没有进入教学合成主链路

`_build_packet()` 会把源码前 80 行存到 `excerpt` 字段，见 `backend/deep_research/pipeline.py:427-439` 与 `473`

但当前最终报告主链路并没有真正消费这些 excerpt 去做章节写作。结果就是：

- 读了文件
- 但没有把文件里的实现细节转成教学说明
- 于是最终仍然只能围绕文件名、符号名、导入名打转

这是“明明扫过源代码，却仍然没有代码导读感”的直接原因。

## 5. 为什么看起来像“机械引用”

因为当前证据表达方式主要是：

- bullet point
- `Evidence files:`
- `Covered files:`
- 固定 `evidence_refs`

相关代码见：

- `render_final_report()` 输出 `Evidence files:`，见 `backend/deep_research/pipeline.py:262`
- group note 输出 `Covered files:`，见 `backend/deep_research/pipeline.py:268-282`

问题不在于“有证据”，而在于“证据没有和解释自然融合”。

现在的证据表达逻辑是：

- 先写一句短 summary
- 再列 bullet
- 再列文件路径

而不是：

- 先提出一个教学问题
- 用 2-3 段自然中文解释
- 在段尾或小节尾收束到关键证据锚点

所以用户看到的就不是“带证据的讲解”，而是“讲解 + 文件清单”。

## 6. 为什么没有达到“至少 3000 字的全面教学报告”

### 6.1 当前 deepresearch 根本没有长度目标

当前 `render_final_report()` 的结构天生短小，见 `backend/deep_research/pipeline.py:237-285`。

它由这些部分组成：

- 固定标题
- 每章 1 段 summary
- 几条 bullet
- 若干 evidence file 路径

这不是一个会自然长到 3000 字的结构。

### 6.2 现有 LLM 预算也不是为长报告设计的

尽管 deepresearch 当前绕过了 LLM 写作，但如果后续直接借用现有 quick guide 写作链路，也依然不够。

关键证据：

- `PromptScenario.INITIAL_REPORT` 的输出 token 预算是 `2400`，见 `backend/m6_response/budgets.py:6`
- 初始 tool context 字符预算是 `24_000`，见 `backend/m6_response/budgets.py:14`
- quick guide 的 seeded context 主要是：
  - `m1.get_repository_context`
  - `m2.get_file_tree_summary`
  - `m2.list_relevant_files`
  - `teaching.get_state_snapshot`
  见 `backend/agent_runtime/context_budget.py:93-96`
- 若需要源码证据，只额外塞一个 starter excerpt，且 `max_files=1`、`max_lines=40`，见 `backend/agent_runtime/context_budget.py:61-66`
- 暴露给模型的工具上限只有 `MAX_SELECTED_TOOLS = 5`，见 `backend/agent_runtime/tool_selection.py:10`

这套预算适合“首轮引导报告”，不适合“全面长报告”。

## 7. 为什么前端也放大了这个问题

前端不是根因，但它强化了“可见文本必须一次写对”的约束。

关键证据：

- 前端渲染 agent 消息时，直接渲染 `raw_text`，见 `web/js/views.js:917-935`
- 首轮报告只是从 `raw_text` 提取 Markdown 标题做一个 toc，见 `web/js/views.js:921-939`
- 建议按钮只读 `msg.suggestions`，见 `web/js/views.js:950-951`
- 测试明确要求前端不要依赖 `initial_report_content` 或 `structured_content` 渲染正文，见 `backend/tests/test_web_contracts.py:21-22`、`35-36`、`52-53`

这意味着：

- 你不能寄希望于“后端只给结构化数据，前端再智能拼成长报告”
- 长报告的质量，必须在 `raw_text` 生成阶段一次性完成

所以，如果 deepresearch 想升级，升级点必须在后端的报告生成流水线，而不是前端渲染层。

## 8. 为什么这不是单独的 prompt 问题

当前 quick guide 的 prompt 体系是存在的，相关位置包括：

- `backend/m5_session/teaching_service.py:42-62`
- `backend/m6_response/prompt_builder.py:15-45`
- `backend/m6_response/prompt_builder.py:184`
- `backend/m6_response/prompt_builder.py:338`

但是 deepresearch 目前没有把这套“教学指令 + 工具调用 + 结构化输出”真正用于长报告正文写作。  
所以你现在看到的问题，不是“提示词措辞差一点”，而是：

- deepresearch 没有专属长报告 contract
- 没有专属章节 planner
- 没有专属中文教学 writer
- 没有质量门禁

在这种情况下，单纯换 prompt 只会把“固定英文摘要器”变成“固定中文摘要器”，依旧达不到你的要求。

## 9. 旧的保守原则也是当前问题的一部分

README 当前明确强调：

- 产品是 read-only repository teaching agent，见 `README.md:3`
- backend 主要提供导航帮助，而不是静态 teaching conclusion，见 `README.md:200`
- backend 不应暴露推断式的 module map / reading path / skeleton facts，见 `README.md:61`

这条原则对于 `quick_guide` 是对的，因为它能防止后端把猜测当事实。

但对于你想要的 `deep_research` 长报告，它变成了一个产品边界冲突：

- 你要的是成型教学报告
- 当前架构原则只允许保守导航帮助

如果不显式把 `deep_research` 升格为“允许形成教学型长报告的独立模式”，后续 agent 很容易继续在旧原则里打转，最后产出还是会偏保守、偏短、偏空。

## 10. 当前测试也在锁定“保守短报告”心智

关键测试信号包括：

- deepresearch 测试只校验出现 `## Repository Verdict` 和 `## File Coverage Appendix`，见 `backend/tests/test_deep_research.py:110-111`
- 非 Python 仓库会直接降级到 quick guide，见 `backend/tests/test_deep_research.py:188`
- quick guide / follow-up 测试持续强调不要回到旧 skeleton 架构，见 `backend/tests/test_m5_session.py:258-292`

这说明当前测试关注的是：

- 不要退回旧版静态骨架
- 保持保守、安全、可解释

它没有关注：

- 中文比例
- 教学性
- 长度
- 设计动机覆盖率
- 模块协作说明完整度

所以即使所有测试都通过，仍然可能产出一份对用户价值很低的导读报告。

## 11. 诊断结论

当前结果之所以“机械引用、英文、没教学性”，根本原因有六个：

1. deepresearch 正文是后端确定性英文字符串拼接，不是长报告写作流程。
2. 语义抽取太浅，只拿到了符号名、导入名、顶层目录组，拿不到架构解释所需的教学语义。
3. 章节是固定 repo scan 模板，不是围绕“教学问题”动态组织。
4. 证据表达方式是文件枚举，不是自然中文讲解中的证据锚点。
5. 没有中文约束、长度约束、教学约束、质量门禁。
6. 前端只吃 `raw_text`，所以后端如果不直接生成高质量报告，前端无法补救。

因此，下一步不能只做 prompt 微调。必须把 deepresearch 升级为一个专门面向“中文教学长报告”的独立流水线。
