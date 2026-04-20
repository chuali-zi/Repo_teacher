# DeepResearch Long Report Architecture v1

> 状态：冻结的实施基线  
> 日期：2026-04-20  
> 用途：给后续接手的 agent 作为唯一有效架构蓝本  
> 约束级别：高。后续 agent 不允许偏离本文件的核心边界、模块划分、质量门槛与外部契约。

## 0. 适用范围

本架构只针对：

- `analysis_mode = deep_research`
- 首轮长报告生成

本架构不适用于：

- `quick_guide`
- follow-up chat
- `sidecar` 的小解释功能

## 1. 冻结的外部行为

以下行为必须保持不变：

1. 用户仍然通过 `web/` 中现有模式切换进入 deepresearch。
2. 仓库提交仍然走 `POST /api/repo`，见 `backend/routes/repo.py`
3. 首轮分析流仍然走 `GET /api/analysis/stream`，见 `backend/routes/analysis.py`
4. 首轮报告最终仍然落在 `MessageDto.raw_text` 中，由前端 Markdown 渲染，见 `web/js/views.js:917-935`
5. `web/` 现有视图切换、聊天进入方式、SSE 基本事件类型不做破坏性修改，见 `web/js/api.js:80-103` 与 `web/js/views.js:667-742`
6. `quick_guide` 的 prompt、tool loop、教学保守原则不因本功能被重写

允许变化的只有：

- `backend/deep_research/` 内部实现
- `backend/m5_session/analysis_workflow.py` 中 deepresearch 分支的内部调用
- deepresearch 专属测试

## 2. 冻结的产品目标

新的 deepresearch 成品必须满足：

1. 简体中文为主。
2. 正文不少于 3000 个中文汉字。
3. 是教学报告，不是文件摘要拼接。
4. 必须覆盖下列主题：
   - 项目定位
   - 整体架构
   - 为什么这么架构
   - 入口与运行链路
   - 模块划分与协作
   - 数据结构与状态模型
   - 解耦点与依赖关系
   - 关键实现细节
   - 设计收益与代价
   - 推荐阅读路径
   - 未验证点与验证建议
5. 允许形成成型架构结论，但每个结论都必须有证据锚点与置信度意识。
6. 禁止机械引用、禁止英文模板、禁止只按目录罗列文件。

## 3. 冻结的原则

### 3.1 双模式原则

- `quick_guide` 继续遵守保守导航原则
- `deep_research` 是独立的教学长报告模式

这条原则必须写进未来实现注释和测试，不允许模糊处理。

### 3.2 证据优先原则

最终报告允许总结与推断，但必须满足：

- 先有证据对象
- 再有结构解释
- 最后才有自然语言写作

不允许直接从文件树或路径列表跳到最终成型报告。

### 3.3 教学问题优先原则

章节不是按“仓库扫描流程”组织，而是按“学生最需要被回答的问题”组织。

### 3.4 质量门禁原则

只要报告不满足中文、长度、覆盖率、非机械引用要求，就不能作为最终 deepresearch 正文发送给前端。

## 4. 强制模块划分

后续 agent 必须按下面的模块边界搭脚手架。文件名可以有极小调整，但职责不能合并、也不能缺席。

建议目录结构：

```text
backend/deep_research/
  __init__.py
  models.py
  repository_profile.py
  evidence_index.py
  module_graph.py
  runtime_flow.py
  architecture_insights.py
  teaching_outline.py
  chapter_briefs.py
  writer_prompts.py
  chapter_writer.py
  report_assembler.py
  quality_gate.py
  pipeline_v2.py
```

## 4.1 `models.py`

职责：

- 定义 deepresearch v2 的内部数据结构

必须包含的核心模型：

- `RepositoryProfile`
- `EvidenceSnippet`
- `ModuleNode`
- `ModuleEdge`
- `RuntimeFlowHypothesis`
- `ArchitectureInsight`
- `TeachingQuestion`
- `ChapterBrief`
- `ChapterDraft`
- `RenderedLongReport`
- `QualityGateResult`

禁止：

- 在这里定义 FastAPI DTO
- 直接复用 quick guide 的 `InitialReportContent` 作为内部写作模型

原因：

- 外部契约要兼容，内部模型要为长报告服务，两者不能绑死

## 4.2 `repository_profile.py`

职责：

- 从仓库级信息建立整体画像

输入：

- `RepositoryContext`
- `FileTreeSnapshot`

输出：

- `RepositoryProfile`

必须提取：

- 主要语言
- 关键根目录
- 关键配置文件
- 关键文档
- 仓库入口候选
- 明显的 runtime surface

禁止：

- 输出最终教学文案

## 4.3 `evidence_index.py`

职责：

- 构建可复用证据索引

必须做的事：

- 读取关键源码
- 同时支持 Python 源码与 `web/` 下的 JS/HTML/CSS 关键文件
- 保留文件级和符号级证据
- 按路径、模块、角色、主题建立索引
- 为后续章节选证据时提供稳定查询能力

必须输出：

- `EvidenceSnippet` 列表
- `path -> snippets` 映射
- `symbol -> snippets` 映射
- `topic -> snippets` 映射

禁止：

- 只保存前 80 行然后停止
- 只保存函数名和 import 名
- 只对 `.py` 文件建语义索引、把 `web/` 退化成普通静态文件列表

原因：

- 长报告需要可解释的证据，不是轮廓符号表

## 4.4 `module_graph.py`

职责：

- 建立模块图，而不是顶层目录组

必须做的事：

- 识别逻辑模块边界
- 生成 `ModuleNode`
- 生成 `ModuleEdge`
- 标出：
  - 依赖边
  - 调用边
  - 配置注入边
  - 状态传递边
  - 前后端契约边

强制要求：

- 不允许仅按顶层目录分组
- 不允许只构建后端模块图，不构建前端模块图
- 至少支持识别本项目中的这类模块边界：
  - `contracts`
  - `routes`
  - `m1_repo_access`
  - `m2_file_tree`
  - `m5_session`
  - `m6_response`
  - `agent_tools`
  - `agent_runtime`
  - `web/js/api.js`
  - `web/js/state.js`
  - `web/js/views.js`

## 4.5 `runtime_flow.py`

职责：

- 重建“启动入口到最终输出”的关键链路

必须覆盖：

- 提交仓库链路
- 初始分析链路
- deepresearch 分支链路
- SSE 推送链路
- 前端渲染链路
- `web/js/api.js -> /api/* -> backend/routes/* -> session/service/workflow -> SSE -> web/js/views.js` 的连接关系

输出：

- `RuntimeFlowHypothesis` 列表

注意：

- flow 可以包含推断，但必须标出是 `verified` 还是 `source-grounded hypothesis`

## 4.6 `architecture_insights.py`

职责：

- 生成“为什么这么设计”的候选洞察

必须回答：

- 为什么 `SessionService` 是 orchestration 中心
- 为什么 `AnalysisWorkflow` 与 `ChatWorkflow` 分开
- 为什么 `contracts` 与 `routes` 解耦
- 为什么 `m5_session` 和 `m6_response` 分层
- 为什么 `agent_tools` 和 `agent_runtime` 分开
- 为什么前端把 `api.js`、`state.js`、`views.js` 拆开

输出：

- `ArchitectureInsight` 列表

禁止：

- 没有证据就直接写“为了高扩展性”
- 用空泛架构词替代具体解释

## 4.7 `teaching_outline.py`

职责：

- 把代码证据和架构洞察转成“教学问题清单”

必须产出的问题类型：

- 项目是什么
- 主要模块有哪些
- 模块如何协作
- 为什么这样切分
- 数据结构为什么这样设计
- 哪些地方体现了解耦
- 新人第一遍应该怎么看

输出：

- `TeachingQuestion` 列表
- 报告总纲

这是新 deepresearch 的核心中间层，不能省略。

## 4.8 `chapter_briefs.py`

职责：

- 为每个强制章节生成严格 brief

每个 `ChapterBrief` 必须包含：

- `chapter_key`
- `title`
- `goal`
- `must_answer`
- `must_cover_modules`
- `must_cover_data_structures`
- `required_evidence_paths`
- `allowed_inferences`
- `forbidden_patterns`
- `min_chars`
- `max_chars`

强制章节如下：

1. 项目定位与整体目标
2. 架构总览与设计动机
3. 启动入口与主执行链路
4. 模块地图与模块协作
5. 数据结构与状态模型
6. 解耦设计与依赖关系
7. 关键实现细节
8. 设计收益、代价与风险
9. 推荐阅读路径
10. 未验证问题与后续验证建议

禁止：

- 让 writer 自己决定写哪些章
- 允许缺失“为什么这样设计”或“数据结构为什么这样用”

## 4.9 `writer_prompts.py`

职责：

- 维护 deepresearch 专属写作 prompt 模板

必须明确写入的规则：

- 全文简体中文
- 默认教学口吻
- 先解释，再给证据锚点
- 不要逐句贴文件路径
- 不要只复述函数名和目录名
- 必须回答章节 brief 中的问题
- 对未验证结论用“从源码迹象看”“更像是”“目前更合理的推断是”这类措辞

禁止：

- 复用 quick guide 的 `_SYSTEM_RULES` 直接写长报告
- 把 deepresearch prompt 混进 `backend/m6_response/prompt_builder.py` 主流程

原因：

- quick guide 的 prompt 是面向短轮次教学答复，不是面向长报告写作

## 4.10 `chapter_writer.py`

职责：

- 逐章调用 LLM 生成 `ChapterDraft`

必须遵守：

- 一次只写一章
- 每章输入只包含该章所需 brief 和证据
- 返回时要包含：
  - `chapter_key`
  - `markdown_text`
  - `used_evidence_paths`
  - `confidence_notes`

为什么按章写：

- 更稳定
- 更可控
- 更容易重试
- 更容易做回归测试

## 4.11 `report_assembler.py`

职责：

- 把所有 `ChapterDraft` 装配为最终 Markdown 正文

必须输出的标题骨架：

```markdown
# 仓库深度代码导读报告：{repo_name}

## 1. 项目定位与整体目标
## 2. 架构总览与设计动机
## 3. 启动入口与主执行链路
## 4. 模块地图与模块协作
## 5. 数据结构与状态模型
## 6. 解耦设计与依赖关系
## 7. 关键实现细节
## 8. 设计收益、代价与风险
## 9. 推荐阅读路径
## 10. 未验证问题与后续验证建议
```

每章末尾必须允许一个短的“证据锚点”小段，但禁止整章都变成证据路径列表。

## 4.12 `quality_gate.py`

职责：

- 对最终报告做硬性验收

必须检查：

- 中文字符数 `>= 3000`
- 必备章节是否齐全
- “为什么/原因/收益/代价/解耦/数据结构”等核心主题是否出现
- 证据路径数量是否过密
- 英文句子比例是否超标
- 是否出现模板空话或占位语
- 是否存在章节缺失或严重失衡

建议输出：

- `QualityGateResult(passed: bool, failures: list[str], metrics: dict)`

强制策略：

- `passed = false` 时不得直接对用户返回最终正文

## 4.13 `pipeline_v2.py`

职责：

- 串起整个 deepresearch v2 流程

强制流程：

1. `repository_profile`
2. `evidence_index`
3. `module_graph`
4. `runtime_flow`
5. `architecture_insights`
6. `teaching_outline`
7. `chapter_briefs`
8. `chapter_writer`
9. `report_assembler`
10. `quality_gate`
11. `build_initial_report_answer_from_report`

禁止：

- 重新回到一个单文件大函数
- 让 `analysis_workflow.py` 自己承担上述所有职责

## 5. 强制数据结构设计

后续 agent 必须采用“显式中间结构”，不能跳过。

推荐的数据结构策略如下。

## 5.1 `ModuleNode` + `ModuleEdge`

用途：

- 表达模块图

原因：

- 图结构适合表达依赖、调用、契约、状态传播
- 比单纯目录树更贴近“模块如何连起来”

## 5.2 `EvidenceSnippet`

用途：

- 保存可引用的代码证据片段

原因：

- 后续章节写作和质量门禁都需要复用证据

## 5.3 `TeachingQuestion`

用途：

- 把工程事实转成教学问题

原因：

- 没有这一层，报告会回到“列事实”而不是“讲清楚”

## 5.4 `ChapterBrief`

用途：

- 把章节写作从自由发挥变成强约束任务

原因：

- 这是防止后续 agent 偏离的关键数据结构

## 6. 与现有项目的连接点

后续 agent 只能在下面这些点和现有项目耦合：

1. `backend/m5_session/analysis_workflow.py`
   - deepresearch 分支调用 `pipeline_v2`
2. `backend/contracts/domain.py`
   - 继续复用 `DeepResearchRunState`
   - 最终仍然返回 `InitialReportAnswer`
3. `backend/tests/test_deep_research.py`
   - 替换为新的长报告测试基线
4. `web/js/views.js`
   - 原则上不改正文渲染逻辑

禁止耦合：

- 不允许把 deepresearch v2 写进 quick guide 的 `prompt_builder.py`
- 不允许为了 deepresearch 改写 `web/` 的消息渲染契约
- 不允许重引旧版 `teaching_skeleton` 或 `topic_slice`

## 7. SSE 与进度阶段的冻结规则

为避免前端交互变化，现有 deepresearch 的外部阶段名保持不变：

- `research_planning`
- `source_sweep`
- `chapter_synthesis`
- `final_report_write`

内部子阶段可以更细，但必须映射回这四个外部阶段。

推荐映射：

- `research_planning`
  - repository profile
  - evidence indexing
  - teaching question draft
- `source_sweep`
  - module graph
  - runtime flow
  - architecture insights
- `chapter_synthesis`
  - outline
  - chapter briefs
- `final_report_write`
  - chapter writing
  - assembly
  - quality gate

## 8. 质量红线

以下任何一条触发，都算 deepresearch 失败：

1. 最终正文少于 3000 中文汉字。
2. 最终正文缺少强制章节。
3. 最终正文大面积英文模板。
4. 最终正文主要由文件路径和 bullet 构成。
5. 没有解释“为什么这样设计”。
6. 没有解释“用了哪些数据结构，为什么”。
7. 没有解释“怎么解耦，为什么解耦”。
8. 只讲 `backend` 不讲 `web`。
9. 把推断说成已验证事实。
10. 直接复用旧的 `render_final_report()` 输出。

## 9. 明确禁止的偷懒做法

后续 agent 不允许采用下面这些捷径：

1. 继续使用 `backend/deep_research/pipeline.py` 当前的英文章节模板，只把文案翻译成中文。
2. 继续按顶层目录分组，然后宣称那就是模块架构。
3. 只抽取函数名、类名、import 名，就去写“为什么这样设计”。
4. 让模型一次性自由写完整报告，不经过章节 brief。
5. 用“Evidence files”之类的路径清单代替自然讲解。
6. 修改前端去消费复杂结构化对象，从而规避正文质量问题。
7. 为了做长报告，把 quick guide 的保守流程一并打碎重写。

## 10. 测试要求

后续 agent 必须补以下测试。

### 10.1 单元测试

- `repository_profile.py`
- `module_graph.py`
- `runtime_flow.py`
- `architecture_insights.py`
- `quality_gate.py`

### 10.2 集成测试

- Python 仓库 deepresearch 可以生成中文长报告
- 非 Python 仓库仍按既有规则降级
- 现有 quick guide 不回归
- SSE 事件顺序不回归

### 10.3 质量测试

必须新增断言：

- 中文字符数达标
- 强制章节齐全
- 报告包含“为什么这样设计”
- 报告包含“数据结构”
- 报告包含“解耦”
- 报告包含 `backend` 与 `web`
- 报告证据路径密度不过载

## 11. 给脚手架 agent 的执行顺序

后续 agent 必须按下面顺序实现：

1. 先建 `models.py`
2. 再建 `repository_profile.py` 和 `evidence_index.py`
3. 再建 `module_graph.py` 与 `runtime_flow.py`
4. 再建 `architecture_insights.py`
5. 再建 `teaching_outline.py` 与 `chapter_briefs.py`
6. 再建 `writer_prompts.py` 与 `chapter_writer.py`
7. 再建 `report_assembler.py`
8. 最后建 `quality_gate.py` 和 `pipeline_v2.py`
9. 然后接入 `analysis_workflow.py`
10. 最后补测试

禁止乱序原因：

- 没有中间结构就写 writer，后面一定回到自由发挥
- 没有质量门禁就接前端，最后一定出现不稳定产物

## 12. 最终架构决策

本文件的最终决策如下：

1. `deep_research` 升级为独立的中文教学长报告流水线。
2. 外部交互与前端消息契约保持不变。
3. 内部采用“证据层 -> 语义层 -> 教学规划层 -> 章节写作层 -> 质量门禁层”的分层结构。
4. 章节必须强约束，不能自由发挥。
5. 质量门禁必须是上线前置条件，不是建议项。

后续 agent 若与本决策冲突，必须以本文件为准，而不是以旧版 `PRD_v5_agent` 或当前 `pipeline.py` 的实现习惯为准。
