# 数据契约

本文只以 `backend/contracts/domain.py`、`dto.py`、`enums.py`、`sse.py` 为准，
梳理当前仓库中的契约层。为了避免文档漂移，本文把契约分成三类：

- 公开 API / SSE 契约：前后端直接交互
- 内部运行态契约：后端会话、扫描、教学、工具执行时使用
- 保留但非当前 live path 契约：类型仍在代码中，但不是当前主接口输出

## 文件级角色

| 文件 | 角色 |
| --- | --- |
| `enums.py` | 所有稳定枚举定义 |
| `domain.py` | 后端内部运行态与答案解析模型 |
| `dto.py` | HTTP DTO、会话快照 DTO、SSE 事件 DTO |
| `sse.py` | `SseEventDto -> event:` 编码器 |

## 基础约束

- 所有契约都继承 `ContractModel`
- `ContractModel` 使用 `use_enum_values=True`
- 契约默认允许枚举值序列化、字段名直接输出和嵌套模型组合

## 公开 API / SSE 契约

### 统一 Envelope

- `ApiEnvelope[T]`
  - 成功：`ok=true`，必须有 `data`，不能有 `error`
  - 失败：`ok=false`，必须有 `error`，不能有 `data`
- 这层约束同时体现在 `success_envelope()` 与 `error_envelope()` 辅助函数

### 请求 DTO

- `ValidateRepoRequest`：`input_value`
- `SubmitRepoRequest`：`input_value`、`analysis_mode`
- `SendMessageRequest`：`message`
- `ExplainSidecarRequest`：`question`

### HTTP 返回 DTO

- `ValidateRepoData`
  - `input_kind`: `local_path` / `github_url` / `unknown`
  - `is_valid`
  - `normalized_input`
  - `message`
- `SubmitRepoData`
  - `accepted`
  - `status`
  - `sub_status`
  - `view`
  - `analysis_mode`
  - `repository`
  - `analysis_stream_url`
- `SendMessageData`
  - `accepted`
  - `status`
  - `sub_status`
  - `user_message_id`
  - `chat_stream_url`
- `ExplainSidecarData`
  - `answer`
- `ClearSessionData`
  - `status`
  - `sub_status`
  - `view`
  - `cleanup_completed`

### 快照与消息 DTO

- `RepositorySummaryDto`
  - 面向前端展示仓库摘要：`display_name`、`source_type`、`input_value`、
    `primary_language`、`repo_size_level`、`source_code_file_count`
- `MessageDto`
  - 核心字段：`message_id`、`role`、`message_type`、`created_at`、`raw_text`、
    `suggestions`、`streaming_complete`
  - 可选字段：`structured_content`、`initial_report_content`、`related_goal`、
    `error_state`
  - 约束：
    - `initial_report` 必须带 `initial_report_content`
    - 非 `initial_report` 不能带 `initial_report_content`
    - 结构化 agent 消息必须带 `structured_content`
    - 用户消息不能带结构化 payload
- `SessionSnapshotDto`
  - `session_id`、`status`、`sub_status`、`view`
  - `analysis_mode`
  - `repository`
  - `progress_steps`
  - `degradation_notices`
  - `messages`
  - `active_agent_activity`
  - `active_error`
  - `deep_research_state`

### 结构化内容 DTO

- `SuggestionDto`
- `EvidenceLineDto`
- `EntryCandidateDto`
- `ReadingStepDto`
- `UnknownItemDto`
- `ProjectTypeCandidateDto`
- `InitialReportContentDto`
- `InitialOverviewDto`
- `InitialFocusPointDto`
- `InitialRepoMappingDto`
- `InitialLanguageTypeDto`
- `InitialKeyDirectoryDto`
- `InitialEntrySectionDto`
- `InitialRecommendedStepDto`
- `StructuredMessageContentDto`
- `UserFacingErrorDto`
- `MessageErrorStateDto`
- `DegradationFlagDto`
- `RelevantSourceFileDto`
- `DeepResearchStateDto`
- `AgentActivityDto`

这些 DTO 是 `domain.py` 中对应模型的前端输出层版本。

### SSE 事件 DTO

- `SseEventDto`：公共基类，字段是 `event_id`、`event_type`、`session_id`、
  `occurred_at`
- `StatusChangedEvent`
- `AnalysisProgressEvent`
- `DegradationNoticeEvent`
- `AgentActivityEvent`
- `AnswerStreamStartEvent`
- `AnswerStreamDeltaEvent`
- `AnswerStreamEndEvent`
- `MessageCompletedEvent`
- `ErrorEvent`

组合类型：

- `AnalysisSseEvent`
- `ChatSseEvent`

### SSE 编码函数

- `encode_sse_event(event)`
  - 输出 `event: {event_type}\ndata: {json}\n\n`
- `encode_sse_stream(events)`
  - 逐条校验事件对象后编码输出

## 内部运行态契约

### 仓库接入与文件树

- `ProgressStepStateItem`
- `ReadPolicySnapshot`
- `RepositoryContext`
- `TempResourceSet`
- `IgnoreRule`
- `SensitiveFileRef`
- `LanguageStat`
- `ScanScope`
- `FileNode`
- `FileTreeSnapshot`
- `RelevantSourceFile`

这组模型负责描述仓库边界、扫描结果、ignore / sensitive 命中情况和可读文件集合。

### 深度研究运行态

- `ResearchPacket`
- `ResearchNote`
- `SynthesisNote`
- `DeepResearchRunState`

这组模型只在 deep research 模式下参与长报告生成。

### 当前 live 会话 / 回答 / 提示层

- `ExplainedItemRef`
- `EvidenceLine`
- `Suggestion`
- `InitialReportContent`
- `StructuredMessageContent`
- `UserFacingError`
- `UserFacingErrorException`
- `MessageErrorState`
- `MessageRecord`
- `TeachingPlanStep`
- `TeachingPlanState`
- `StudentLearningTopicState`
- `StudentLearningState`
- `TeacherWorkingLog`
- `TeachingDecisionSnapshot`
- `TeachingDirective`
- `TeachingDebugEvent`
- `ConversationState`
- `OutputContract`
- `LlmToolDefinition`
- `LlmToolResult`
- `LlmToolContext`
- `PromptBuildInput`
- `StructuredAnswer`
- `InitialReportAnswer`
- `DegradationFlag`
- `AgentActivity`
- `RuntimeEvent`
- `SessionContext`
- `SessionStore`

其中最关键的几类：

- `MessageRecord`
  - 是后端内部持久化到会话里的消息形态
  - 与 `MessageDto` 保持相同的消息形状约束
- `ConversationState`
  - 聚合消息历史、当前学习目标、教学计划、学生状态、调试事件
- `PromptBuildInput`
  - 约束一轮 prompt 构建需要的上下文、输出契约和工具开关
- `RuntimeEvent`
  - 是 SSE 之前的内部事件总线模型
- `SessionContext`
  - 聚合仓库、文件树、对话、进度、错误、降级、运行事件

## 保留但非当前 live path 契约

以下类型仍然存在于代码中，但不是当前主交互面直接输出的 live API：

- `ProjectTypeCandidate`
- `ProjectProfileResult`
- `UnknownItem`
- `EntryCandidate`
- `ImportClassification`
- `ModuleSummary`
- `LayerAssignment`
- `LayerViewResult`
- `FlowStep`
- `FlowSummary`
- `ReadingStep`
- `EvidenceRef`
- `AnalysisWarning`
- `RepoSurfaceAssignment`
- `KnowledgeObservation`
- `KnowledgeCandidate`
- `RepositoryKnowledgeBase`
- `AnalysisBundle`
- `TopicRef`
- `OverviewSection`
- `FocusPoint`
- `ConceptMapping`
- `LanguageTypeSection`
- `KeyDirectoryItem`
- `EntrySection`
- `FlowSection`
- `LayerSection`
- `DependencySection`
- `RecommendedStep`
- `TopicIndex`
- `TeachingSkeleton`

这些模型大多属于较早期的分析 / skeleton 表达层，当前代码仍会复用其中一部分子模型，
但不应把 `AnalysisBundle`、`TeachingSkeleton` 误写成当前主接口产物。

## 枚举总表

### 运行态 / 会话

- `SessionStatus`
- `ConversationSubStatus`
- `ClientView`
- `AnalysisMode`

### 仓库来源与文件扫描

- `RepoSourceType`
- `RepoSizeLevel`
- `FileNodeType`
- `FileNodeStatus`
- `IgnoreRuleSource`
- `ScanScopeType`
- `CleanupStatus`

### 分析 / skeleton / 证据表达

- `SkeletonMode`
- `ConfidenceLevel`
- `DerivedStatus`
- `ProjectType`
- `EntryTargetType`
- `RepoSurface`
- `EntryRole`
- `ImportSourceType`
- `ModuleKind`
- `LayerType`
- `MainPathRole`
- `FlowKind`
- `ReadingTargetType`
- `EvidenceType`
- `UnknownTopic`
- `WarningType`

### 教学状态

- `LearningGoal`
- `TeachingStage`
- `DepthLevel`
- `TeachingPlanStepStatus`
- `StudentCoverageLevel`
- `TeachingDecisionAction`
- `TeachingDebugEventType`
- `MessageSection`
- `TopicRefType`

### 消息 / 协议 / 错误

- `MessageRole`
- `MessageType`
- `PromptScenario`
- `RuntimeEventType`
- `AgentActivityPhase`
- `ProgressStepKey`
- `ProgressStepState`
- `DegradationType`
- `ErrorCode`

## 当前最重要的 shape 约束

- `ApiEnvelope`：成功和失败不能混合字段
- `MessageDto` / `MessageRecord`：
  - `initial_report` 与 `initial_report_content` 成对出现
  - 结构化 agent 消息必须有 `structured_content`
  - 用户消息不能带结构化 payload
- `InitialReportAnswer`：
  - `message_type` 必须是 `initial_report`
- `RuntimeEvent`：
  - 是内部统一事件容器，具体事件字段根据 `event_type` 决定

## 维护建议

- 如果新增前端会消费的字段，先改 `domain.py` 对应模型，再补 `dto.py` 输出层和本文档。
- 如果新增事件类型，必须同时更新 `RuntimeEventType`、SSE DTO、`event_mapper.py`、
  `protocols.md`。
- 如果一个模型只保留在内部或历史兼容路径，文档里要显式标为“非当前 live path”。
