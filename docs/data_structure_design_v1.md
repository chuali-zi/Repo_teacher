# Repo Tutor — 核心数据结构设计 v1

> **文档类型**：数据结构规格
> **对应架构**：`technical_architecture_v1.md`
> **对应 PRD**：`PRD_v5_agent.md`
> **对应交互设计**：`interaction_design_v1.md`
> **作者角色**：数据结构设计师
> **适用范围**：第一版单 Agent、只读、教学型 Repo Tutor
> **日期**：2026-04-12

---

## 索引

| 编号 | 章节 | 说明 | 下游引用建议 |
|------|------|------|-------------|
| [DS-01](#ds-01) | 设计边界与约束来源 | 本文负责范围、排除范围、引用依据 | 后续 Agent 先读，避免越界 |
| [DS-02](#ds-02) | 总体建模原则 | 核心建模方法与统一约束 | 后端 Agent、状态管理 Agent |
| [DS-03](#ds-03) | 核心实体总览 | 全部核心实体与职责一览 | 所有下游 Agent |
| [DS-04](#ds-04) | 实体 S1 — SessionContext | 单会话根对象 | 状态管理、协调层实现 |
| [DS-05](#ds-05) | 实体 S2 — RepositoryContext | 仓库接入后的统一仓库描述 | 仓库接入层、清理逻辑 |
| [DS-06](#ds-06) | 实体 S3 — FileTreeSnapshot | 文件树扫描与过滤产物 | 文件树扫描、过滤模块 |
| [DS-07](#ds-07) | 实体 S4 — AnalysisBundle | M3 静态分析核心产物 | 分析引擎实现 |
| [DS-08](#ds-08) | 实体 S5 — TeachingSkeleton | M4 教学骨架组织产物 | 骨架组装、回答生成 |
| [DS-09](#ds-09) | 实体 S6 — ConversationState | 多轮对话状态 | 对话管理器实现 |
| [DS-10](#ds-10) | 实体 S7 — MessageRecord | 消息记录结构 | 消息流渲染、上下文维护 |
| [DS-11](#ds-11) | 实体 S8 — RuntimeEvent | 运行态事件结构 | SSE 推送、进度和流式输出 |
| [DS-12](#ds-12) | 通用值对象与枚举建议 | 复用值对象、枚举口径 | 避免字段风格分裂 |
| [DS-13](#ds-13) | 实体关系与生命周期 | 聚合关系、创建顺序、清理规则 | 状态机与资源回收 |
| [DS-14](#ds-14) | 存储策略 | 内存存储、缓存层次、清理策略 | 后端实现、性能设计 |
| [DS-15](#ds-15) | 不确定项与待确认点 | 当前仍需确认的少量决策 | 产品/架构评审 |

---

## <a id="ds-01"></a>DS-01 设计边界与约束来源

### 本文负责范围

本文仅负责以下内容：

1. 核心实体
2. 关键字段
3. 实体关系
4. 生命周期
5. 存储策略

### 本文明确不负责

本文不负责：

1. 接口规范
2. 路由设计
3. HTTP/SSE 协议字段
4. 前端组件 props 设计
5. 数据库表设计

### 约束来源

本文严格以以下文档为准：

- `technical_architecture_v1.md`
- `PRD_v5_agent.md`
- `interaction_design_v1.md`

### 关键约束摘要

1. 第一版为单用户、本地部署、单会话
2. 系统为只读，不执行仓库代码，不修改仓库
3. 第一版不引入数据库，状态以内存维护
4. 敏感文件只记录“存在但未读取内容”
5. 分析结果必须支持“未知优先于硬猜”
6. 多轮对话必须保持仓库与学习目标状态
7. 降级场景必须通过统一结构表达，而不是另起一套数据模型

---

## <a id="ds-02"></a>DS-02 总体建模原则

### 原则 1：区分“事实层”和“教学层”

- M2/M3 产物属于结构化事实层
- M4 产物属于教学组织层
- M6 只消费教学层和会话状态，不反向污染分析事实

### 原则 2：区分“仓库上下文”和“对话上下文”

- 仓库相关内容应聚合在仓库上下文中
- 对话相关内容应聚合在会话/对话状态中
- 不把对话推进过程写回分析结论对象

### 原则 3：所有推断结果必须可追溯

凡是候选性、推断性、启发式结论，必须附带：

- `confidence`
- `evidence_refs`
- `uncertainty_note` 或 `unknown_items`

### 原则 4：统一支持降级

大型仓库、非 Python 仓库、入口未知、流程不足、分层不足，都应通过统一字段标注：

- 当前模式
- 降级标记
- 未知项
- 面向用户的降级说明

### 原则 5：统一支持清理

切换仓库时必须能明确释放：

- 会话中的仓库相关对象
- 临时 clone 目录引用
- 流式事件缓存
- 已有分析结果缓存

---

## <a id="ds-03"></a>DS-03 核心实体总览

### 核心实体清单

| 实体 | 作用 | 对应模块 |
|------|------|---------|
| `SessionContext` | 单会话根对象，聚合当前全部运行状态 | M5 |
| `RepositoryContext` | 仓库输入与访问结果统一描述 | M1 |
| `FileTreeSnapshot` | 文件树扫描、过滤、规模与语言判定结果 | M2 |
| `AnalysisBundle` | 静态分析结构化产物总包 | M3 |
| `TeachingSkeleton` | 教学骨架与主题索引 | M4 |
| `ConversationState` | 多轮对话状态 | M5 |
| `MessageRecord` | 用户/Agent 消息记录 | M5/M6/M7 |
| `RuntimeEvent` | 进度、流式输出、错误、降级等运行态事件 | M5/M6/M7 |

---

## <a id="ds-04"></a>DS-04 实体 S1 — SessionContext

### 作用

当前唯一会话根对象，是第一版系统的最高层状态聚合体。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | `str` | 会话唯一标识 |
| `status` | `SessionStatus` | 当前全局状态 |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 最近更新时间 |
| `repository` | `RepositoryContext \| null` | 当前仓库上下文 |
| `file_tree` | `FileTreeSnapshot \| null` | 当前文件树快照 |
| `analysis` | `AnalysisBundle \| null` | 当前分析产物 |
| `teaching_skeleton` | `TeachingSkeleton \| null` | 当前教学骨架 |
| `conversation` | `ConversationState` | 当前对话状态 |
| `last_error` | `UserFacingError \| null` | 最近一次面向用户的错误 |
| `active_degradations` | `list[DegradationFlag]` | 当前生效的降级标记 |
| `temp_resources` | `TempResourceSet \| null` | 临时目录等可清理资源引用 |

### 设计说明

1. `SessionContext` 是 M5 的内存存储单位
2. 第一版建议默认只维护一个活跃 `SessionContext`
3. 所有跨模块共享状态都从该对象进入，不做分散全局变量

---

## <a id="ds-05"></a>DS-05 实体 S2 — RepositoryContext

### 作用

统一承接“本地路径”和“GitHub URL”两类仓库输入，并保存访问验证后的仓库事实。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo_id` | `str` | 仓库上下文唯一标识 |
| `source_type` | `RepoSourceType` | `local_path` 或 `github_url` |
| `display_name` | `str` | 对外展示名称 |
| `input_value` | `str` | 用户原始输入 |
| `root_path` | `str` | 校验后的仓库根路径 |
| `is_temp_dir` | `bool` | 是否为 clone 出来的临时目录 |
| `owner` | `str \| null` | GitHub owner |
| `name` | `str \| null` | 仓库名 |
| `branch_or_ref` | `str \| null` | 当前分支或引用，v1 可空 |
| `access_verified` | `bool` | 可访问性是否已验证 |
| `primary_language` | `str \| null` | 主语言 |
| `repo_size_level` | `RepoSizeLevel \| null` | 仓库规模级别 |
| `source_code_file_count` | `int \| null` | 源码文件数 |
| `read_policy` | `ReadPolicySnapshot` | 当前读取与安全策略快照 |

### 设计说明

1. `root_path` 必须是校验后的绝对路径
2. 本地仓库和 GitHub 仓库在下游统一按 `root_path` 使用
3. `read_policy` 固化本次会话所采用的只读、安全、敏感文件策略

---

## <a id="ds-06"></a>DS-06 实体 S3 — FileTreeSnapshot

### 作用

作为 M2 的稳定输出，承接文件树结构、过滤结果、规模判定和语言判定。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `snapshot_id` | `str` | 文件树快照唯一标识 |
| `repo_id` | `str` | 所属仓库上下文 |
| `generated_at` | `datetime` | 生成时间 |
| `root_path` | `str` | 扫描根目录 |
| `nodes` | `list[FileNode]` | 文件树节点列表 |
| `ignored_rules` | `list[IgnoreRule]` | 生效的忽略规则 |
| `sensitive_matches` | `list[SensitiveFileRef]` | 命中敏感规则的文件 |
| `language_stats` | `list[LanguageStat]` | 各语言统计 |
| `primary_language` | `str` | 主语言 |
| `repo_size_level` | `RepoSizeLevel` | 小型/中型/大型 |
| `degraded_scan_scope` | `ScanScope \| null` | 大仓库时的扫描范围说明 |

### 子对象 `FileNode`

| 字段 | 类型 | 说明 |
|------|------|------|
| `node_id` | `str` | 节点唯一标识 |
| `relative_path` | `str` | 相对仓库根路径 |
| `node_type` | `FileNodeType` | `file` 或 `directory` |
| `extension` | `str \| null` | 文件扩展名 |
| `status` | `FileNodeStatus` | 节点状态 |
| `is_python_source` | `bool` | 是否 Python 源文件 |
| `size_bytes` | `int \| null` | 文件大小 |
| `depth` | `int` | 树深度 |
| `parent_path` | `str \| null` | 父节点路径 |
| `real_path` | `str` | 解析后的真实路径 |

### `FileNodeStatus` 建议值

- `normal`
- `ignored`
- `sensitive_skipped`
- `unreadable`
- `out_of_scope`

### 设计说明

1. 敏感文件不进入内容读取流程，但仍在树上留痕
2. `real_path` 用于路径越界防护
3. `relative_path` 是所有下游引用路径的主口径

---

## <a id="ds-07"></a>DS-07 实体 S4 — AnalysisBundle

### 作用

承接 M3 的全部结构化分析产物，是系统最核心的事实层对象。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `bundle_id` | `str` | 分析包唯一标识 |
| `repo_id` | `str` | 所属仓库 |
| `generated_at` | `datetime` | 生成时间 |
| `analysis_mode` | `AnalysisMode` | 正常或降级模式 |
| `project_profile` | `ProjectProfileResult` | 项目画像结果 |
| `entry_candidates` | `list[EntryCandidate]` | 入口候选集合 |
| `import_classifications` | `list[ImportClassification]` | import 来源分类结果 |
| `module_summaries` | `list[ModuleSummary]` | 关键模块总结 |
| `layer_view` | `LayerViewResult \| null` | 分层视图 |
| `flow_summaries` | `list[FlowSummary]` | 候选流程骨架 |
| `reading_path` | `list[ReadingStep]` | 阅读路径 |
| `evidence_catalog` | `list[EvidenceRef]` | 证据目录 |
| `unknown_items` | `list[UnknownItem]` | 未知项集合 |
| `warnings` | `list[AnalysisWarning]` | 非致命警告 |

### 子对象 `ProjectProfileResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_types` | `list[ProjectTypeCandidate]` | 项目类型候选 |
| `summary_text` | `str \| null` | 项目画像摘要 |

### 子对象 `EntryCandidate`

| 字段 | 类型 | 说明 |
|------|------|------|
| `entry_id` | `str` | 候选入口 ID |
| `target_type` | `EntryTargetType` | 文件、命令或配置入口 |
| `target_value` | `str` | 具体位置或命令 |
| `reason` | `str` | 候选理由 |
| `confidence` | `ConfidenceLevel` | 高/中/低/未知 |
| `rank` | `int` | 推荐顺序 |
| `evidence_refs` | `list[str]` | 对应证据 ID 列表 |

### 子对象 `ImportClassification`

| 字段 | 类型 | 说明 |
|------|------|------|
| `import_name` | `str` | import 名称 |
| `source_type` | `ImportSourceType` | 内部/标准库/第三方/未知 |
| `used_by_files` | `list[str]` | 被哪些文件使用 |
| `basis` | `str` | 判断依据 |
| `confidence` | `ConfidenceLevel` | 置信度 |
| `evidence_refs` | `list[str]` | 证据引用 |

### 子对象 `ModuleSummary`

| 字段 | 类型 | 说明 |
|------|------|------|
| `module_id` | `str` | 模块 ID |
| `path` | `str` | 模块路径 |
| `module_kind` | `ModuleKind` | 目录、包、文件等 |
| `responsibility` | `str \| null` | 推断职责 |
| `importance_rank` | `int \| null` | 重要性排序 |
| `likely_layer` | `LayerType \| null` | 可能位于哪一层 |
| `upstream_modules` | `list[str]` | 上游模块 |
| `downstream_modules` | `list[str]` | 下游模块 |
| `worth_reading_now` | `bool \| null` | 当前阶段是否值得读 |
| `evidence_refs` | `list[str]` | 证据引用 |
| `confidence` | `ConfidenceLevel` | 置信度 |

### 子对象 `LayerViewResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | `DerivedStatus` | 已形成 / 启发式 / 未知 |
| `layers` | `list[LayerAssignment]` | 层次映射列表 |
| `uncertainty_note` | `str \| null` | 不确定说明 |

### 子对象 `FlowSummary`

| 字段 | 类型 | 说明 |
|------|------|------|
| `flow_id` | `str` | 流程 ID |
| `entry_candidate_id` | `str \| null` | 对应入口候选 |
| `input_source` | `str \| null` | 输入来源 |
| `module_path` | `list[str]` | 模块路径 |
| `layer_path` | `list[LayerType]` | 经过的层 |
| `output_target` | `str \| null` | 输出去向 |
| `confidence` | `ConfidenceLevel` | 置信度 |
| `uncertainty_note` | `str \| null` | 不确定说明 |
| `evidence_refs` | `list[str]` | 证据引用 |

### 子对象 `ReadingStep`

| 字段 | 类型 | 说明 |
|------|------|------|
| `step_no` | `int` | 步骤序号 |
| `target` | `str` | 阅读目标 |
| `reason` | `str` | 为什么先看 |
| `learning_gain` | `str` | 学习收益 |
| `skippable` | `str \| null` | 暂时可跳过内容 |
| `next_step_hint` | `str \| null` | 下一步提示 |
| `evidence_refs` | `list[str]` | 证据引用 |

### 设计说明

1. `AnalysisBundle` 不承载任何自然语言展示格式
2. 未知必须显式存入 `unknown_items`
3. 非 Python 降级时，允许部分字段为空，但对象仍保持统一结构
4. 所有候选性结果都必须带置信度和证据引用

---

## <a id="ds-08"></a>DS-08 实体 S5 — TeachingSkeleton

### 作用

承接 M4 输出，把分析事实组织成教学可消费结构，供首轮报告和多轮回答按主题抽取。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `skeleton_id` | `str` | 骨架唯一标识 |
| `repo_id` | `str` | 所属仓库 |
| `generated_at` | `datetime` | 生成时间 |
| `skeleton_mode` | `SkeletonMode` | 正常/降级模式 |
| `overview` | `OverviewSection` | 仓库概览 |
| `focus_points` | `list[FocusPoint]` | 当前应先抓的重点 |
| `repo_mapping` | `list[ConceptMapping]` | 观察框架到当前仓库的映射 |
| `language_and_type` | `LanguageTypeSection` | 主语言与项目类型 |
| `key_directories` | `list[KeyDirectoryItem]` | 关键目录说明 |
| `entry_section` | `EntrySection` | 入口候选区块 |
| `recommended_first_step` | `RecommendedStep` | 推荐第一步 |
| `reading_path_preview` | `list[ReadingStep]` | 阅读路径预览 |
| `unknown_section` | `list[UnknownItem]` | 不确定项区块 |
| `topic_index` | `TopicIndex` | 按主题索引分析产物 |
| `suggested_next_questions` | `list[str]` | 首轮建议追问 |

### 子对象 `TopicIndex`

| 字段 | 类型 | 说明 |
|------|------|------|
| `structure_refs` | `list[TopicRef]` | 结构相关引用 |
| `entry_refs` | `list[TopicRef]` | 入口相关引用 |
| `flow_refs` | `list[TopicRef]` | 流程相关引用 |
| `layer_refs` | `list[TopicRef]` | 分层相关引用 |
| `dependency_refs` | `list[TopicRef]` | 依赖相关引用 |
| `module_refs` | `list[TopicRef]` | 模块相关引用 |

### 设计说明

1. `TeachingSkeleton` 是“教学组织层”，不是分析事实替代品
2. 首轮报告必须严格按 PRD OUT-1 顺序组装
3. 多轮对话时，通过 `topic_index` 进行主题切片抽取
4. 非 Python 降级时，仅保留保守结构总览和阅读建议相关区块

---

## <a id="ds-09"></a>DS-09 实体 S6 — ConversationState

### 作用

承接 PRD OUT-9 与交互设计中的多轮状态要求。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `current_learning_goal` | `LearningGoal` | 当前学习目标 |
| `current_stage` | `TeachingStage` | 当前讲解阶段 |
| `current_focus_module` | `str \| null` | 当前聚焦模块 |
| `current_entry_candidate_id` | `str \| null` | 当前聚焦入口 |
| `current_flow_id` | `str \| null` | 当前聚焦流程 |
| `current_layer_view_id` | `str \| null` | 当前分层视图引用 |
| `explained_items` | `list[ExplainedItemRef]` | 已讲解对象 |
| `last_suggestions` | `list[str]` | 上一轮建议 |
| `depth_level` | `DepthLevel` | 浅/默认/深 |
| `messages` | `list[MessageRecord]` | 消息历史 |
| `history_summary` | `str \| null` | 近 N 轮摘要 |
| `sub_status` | `ConversationSubStatus` | 对话态子状态 |

### `ConversationSubStatus`

- `waiting_user`
- `agent_thinking`
- `agent_streaming`

### 设计说明

1. `ConversationState` 从会话创建即存在
2. 进入对话态后，`messages` 持续追加
3. 切换仓库后，`depth_level` 重置为 `default`
4. `explained_items` 用于避免重复讲解和重复推荐

---

## <a id="ds-10"></a>DS-10 实体 S7 — MessageRecord

### 作用

统一承接首轮报告、用户提问、Agent 回答、阶段性总结等消息数据。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `message_id` | `str` | 消息唯一标识 |
| `role` | `MessageRole` | `user` 或 `agent` |
| `message_type` | `MessageType` | 首轮报告/追问/回答/总结/错误 |
| `created_at` | `datetime` | 创建时间 |
| `raw_text` | `str` | 原始文本 |
| `structured_content` | `StructuredMessageContent \| null` | 结构化内容 |
| `related_goal` | `LearningGoal \| null` | 关联学习目标 |
| `related_topic_refs` | `list[TopicRef]` | 关联主题引用 |
| `suggestions` | `list[str]` | 当前消息附带建议 |
| `streaming_complete` | `bool` | 是否已流式完成 |
| `error_state` | `MessageErrorState \| null` | 错误状态 |

### 子对象 `StructuredMessageContent`

| 字段 | 类型 | 说明 |
|------|------|------|
| `focus` | `str \| null` | 本轮重点 |
| `direct_explanation` | `str \| null` | 直接解释 |
| `relation_to_overall` | `str \| null` | 与整体关系 |
| `evidence_lines` | `list[EvidenceLine]` | 判断依据 |
| `uncertainties` | `list[str]` | 不确定项 |
| `next_steps` | `list[str]` | 下一步建议 |

### 设计说明

1. 首轮教学报告也应作为一条 `agent` 消息记录
2. 结构化内容应与 IX-04/OUT-11 顺序一致
3. `raw_text` 负责原始渲染，`structured_content` 负责结构化复用

---

## <a id="ds-11"></a>DS-11 实体 S8 — RuntimeEvent

### 作用

统一承接进度推送、流式回答、错误和降级提示等运行态事件。

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | `str` | 事件唯一标识 |
| `session_id` | `str` | 所属会话 |
| `event_type` | `RuntimeEventType` | 事件类型 |
| `occurred_at` | `datetime` | 发生时间 |
| `status_snapshot` | `SessionStatus \| null` | 事件发生时的状态 |
| `step_key` | `str \| null` | 进度步骤标识 |
| `step_state` | `ProgressStepState \| null` | ✓ / ● / ○ 对应状态 |
| `message_chunk` | `str \| null` | 流式文本片段 |
| `user_notice` | `str \| null` | 面向用户的说明 |
| `error_code` | `ErrorCode \| null` | 错误码 |
| `degradation_flag` | `DegradationFlag \| null` | 降级标记 |
| `payload` | `dict \| null` | 扩展信息 |

### 设计说明

1. `RuntimeEvent` 属于运行态核心结构，不是长期业务事实
2. 用统一事件对象更适合前端进度和流式输出消费
3. 第一版仅保留短时内存队列，不做长期持久化

---

## <a id="ds-12"></a>DS-12 通用值对象与枚举建议

### 通用值对象

#### `EvidenceRef`

| 字段 | 类型 | 说明 |
|------|------|------|
| `evidence_id` | `str` | 证据 ID |
| `type` | `EvidenceType` | 证据类型 |
| `source_path` | `str \| null` | 来源文件路径 |
| `source_location` | `str \| null` | 行号或区块位置 |
| `content_excerpt` | `str \| null` | 摘录内容 |
| `note` | `str \| null` | 补充说明 |

约束：
- 若来源为敏感文件，`content_excerpt` 必须为空

#### `UnknownItem`

| 字段 | 类型 | 说明 |
|------|------|------|
| `topic` | `str` | 未知主题 |
| `description` | `str` | 未知内容描述 |
| `related_paths` | `list[str]` | 关联路径 |
| `reason` | `str \| null` | 未知原因 |

#### `UserFacingError`

| 字段 | 类型 | 说明 |
|------|------|------|
| `error_code` | `ErrorCode` | 错误码 |
| `message` | `str` | 面向用户的提示 |
| `retryable` | `bool` | 是否可重试 |
| `stage` | `SessionStatus` | 错误发生阶段 |

#### `DegradationFlag`

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | `DegradationType` | 降级类型 |
| `reason` | `str` | 原因 |
| `user_notice` | `str` | 面向用户的提示 |

#### `ReadPolicySnapshot`

| 字段 | 类型 | 说明 |
|------|------|------|
| `sensitive_patterns` | `list[str]` | 敏感文件模式 |
| `ignore_patterns` | `list[str]` | 忽略规则 |
| `read_only` | `bool` | 是否只读 |
| `allow_exec` | `bool` | 是否允许执行代码，v1 必须为 `false` |
| `allow_dependency_install` | `bool` | 是否允许安装依赖，v1 必须为 `false` |

### 枚举建议

#### `SessionStatus`

- `idle`
- `accessing`
- `access_error`
- `analyzing`
- `analysis_error`
- `chatting`

#### `RepoSourceType`

- `local_path`
- `github_url`

#### `RepoSizeLevel`

- `small`
- `medium`
- `large`

#### `ConfidenceLevel`

- `high`
- `medium`
- `low`
- `unknown`

#### `AnalysisMode`

- `full_python`
- `degraded_large_repo`
- `degraded_non_python`

#### `SkeletonMode`

- `full`
- `degraded_large_repo`
- `degraded_non_python`

#### `DepthLevel`

- `shallow`
- `default`
- `deep`

---

## <a id="ds-13"></a>DS-13 实体关系与生命周期

### 聚合关系

1. `SessionContext` 聚合全部核心对象
2. `RepositoryContext` 是仓库级根对象
3. `FileTreeSnapshot` 依附于 `RepositoryContext`
4. `AnalysisBundle` 依赖 `FileTreeSnapshot`
5. `TeachingSkeleton` 依赖 `AnalysisBundle`
6. `ConversationState` 依附于 `SessionContext`
7. `MessageRecord` 依附于 `ConversationState`
8. `RuntimeEvent` 围绕 `SessionContext` 运行

### 创建顺序

1. 创建 `SessionContext`
2. 仓库接入成功后创建 `RepositoryContext`
3. 文件树扫描完成后创建 `FileTreeSnapshot`
4. 分析完成后创建 `AnalysisBundle`
5. 教学骨架组装完成后创建 `TeachingSkeleton`
6. 首轮报告生成后写入第一条 `MessageRecord`
7. 多轮追问中持续追加消息并更新 `ConversationState`

### 清理顺序

当用户切换仓库时：

1. 停止当前流式输出
2. 清理 `RuntimeEvent` 队列
3. 删除临时 clone 目录引用
4. 清空 `repository`
5. 清空 `file_tree`
6. 清空 `analysis`
7. 清空 `teaching_skeleton`
8. 重置 `conversation`
9. `status` 置回 `idle`

---

## <a id="ds-14"></a>DS-14 存储策略

### 总体策略

第一版严格采用内存存储，不引入数据库。

### 存储层次

| 层次 | 对象 | 策略 |
|------|------|------|
| 会话主存储 | `SessionContext` | 内存常驻，单会话 |
| 仓库分析缓存 | `FileTreeSnapshot`, `AnalysisBundle`, `TeachingSkeleton` | 同会话复用，不落盘 |
| 对话状态 | `ConversationState`, `MessageRecord` | 同会话内存维护 |
| 运行态事件 | `RuntimeEvent` | 短时队列，完成后可丢弃 |

### 根存储结构建议

```text
SessionStore
└── active_session: SessionContext | null
```

### 缓存策略

1. 同一仓库的多轮对话不重新触发 M2/M3/M4
2. 仅在切换仓库时失效
3. 不做磁盘缓存
4. 不做跨会话缓存
5. 不保留敏感文件正文缓存

### 错误场景存储策略

#### 接入错误
- 保留用户输入
- 保留 `last_error`
- 不创建分析相关对象

#### 分析错误
- 可保留 `RepositoryContext`
- 可保留部分 `FileTreeSnapshot`
- 不要求生成完整 `AnalysisBundle`
- `last_error` 记录为面向用户错误

#### 非致命错误
- 写入 `warnings`
- 不中断主流程
- 必要时进入 `unknown_items`

### 安全策略落地

1. 敏感文件仅在 `sensitive_matches` 中登记
2. 证据对象不能保留敏感文件正文摘录
3. 所有路径必须使用校验后的真实路径参与安全判断
4. 所有下游显示路径统一使用 `relative_path`

### 降级策略落地

降级不另建新模型，而是在统一模型上标记：

- `analysis_mode`
- `skeleton_mode`
- `active_degradations`
- `unknown_items`
- `warnings`

这样可以保证：
- 下游 Agent 不需要维护两套 schema
- 回答生成器只需按模式裁剪内容
- 状态管理更稳定

---

## <a id="ds-15"></a>DS-15 不确定项与待确认点

### 当前保留的不确定项

#### 1. 实体命名语言

建议：
- 实体名与字段名使用英文
- 文档说明使用中文

理由：
- 更利于后续代码实现与 Agent 稳定引用
- 也更贴近架构文档中的模块命名方式

#### 2. `RuntimeEvent` 是否算作核心数据结构

建议：
- 纳入核心数据结构

理由：
- 架构与交互设计都明确依赖分析进度、状态变化、流式回答事件
- 它不是持久业务实体，但属于运行态核心结构

### 当前结论

在不扩展接口规范、不引入数据库、不增加超出 v1 范围的前提下，上述 8 个核心实体已足以覆盖：

1. 仓库接入
2. 文件树扫描
3. 静态分析
4. 教学骨架组装
5. 多轮状态管理
6. 消息记录
7. 进度与流式输出
8. 降级与异常表达

---
