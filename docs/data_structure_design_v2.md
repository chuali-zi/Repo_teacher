# Repo Tutor — 核心数据结构设计 v2

> **文档类型**：数据结构规格
> **对应架构**：`technical_architecture_v2.md`
> **对应 PRD**：`PRD_v5_agent.md`
> **对应交互设计**：`interaction_design_v1.md`
> **修订来源**：审计 `data_structure_design_v1.md`
> **适用范围**：第一版单 Agent、只读、教学型 Repo Tutor
> **日期**：2026-04-12

---

## 索引

| 编号 | 章节 | 说明 |
|------|------|------|
| [DS2-00](#ds2-00) | 审计结论 | v1 偏移与 v2 修正范围 |
| [DS2-01](#ds2-01) | 设计边界 | 本文负责范围与不负责范围 |
| [DS2-02](#ds2-02) | 总体约束 | 命名、序列化、证据、安全、降级约束 |
| [DS2-03](#ds2-03) | 架构覆盖矩阵 | M1-M7 输入输出结构映射 |
| [DS2-04](#ds2-04) | 会话根结构 | `SessionStore`, `SessionContext` |
| [DS2-05](#ds2-05) | 仓库接入结构 | `RepositoryContext`, `TempResourceSet`, `ReadPolicySnapshot` |
| [DS2-06](#ds2-06) | 文件树结构 | `FileTreeSnapshot`, `FileNode`, 过滤与规模对象 |
| [DS2-07](#ds2-07) | 静态分析结构 | `AnalysisBundle` 与 M3 全部子产物 |
| [DS2-08](#ds2-08) | 教学骨架结构 | `TeachingSkeleton`, `TopicIndex` 与首轮报告区块 |
| [DS2-09](#ds2-09) | 对话与回答结构 | `ConversationState`, `MessageRecord`, M6 prompt/response 输入输出 |
| [DS2-10](#ds2-10) | 运行态事件结构 | 仅定义内部 `RuntimeEvent`，不定义接口规范 |
| [DS2-11](#ds2-11) | 错误与降级结构 | `UserFacingError`, `DegradationFlag`, warning |
| [DS2-12](#ds2-12) | 枚举口径 | 全量枚举值 |
| [DS2-13](#ds2-13) | 生命周期与存储 | 创建、缓存、清理规则 |
| [DS2-14](#ds2-14) | 下游验收清单 | 后续 Agent 必须核对的硬约束 |

---

## <a id="ds2-00"></a>DS2-00 审计结论

### 总体判断

`data_structure_design_v1.md` 的产品方向和主实体拆分基本贴合 `technical_architecture_v2.md`、`PRD_v5_agent.md` 与 `interaction_design_v1.md`，但作为后续实现 Agent 的输入不够可靠，存在不可接受的执行风险。

### 不可接受偏移

1. **大量引用类型未定义**：如 `TempResourceSet`, `IgnoreRule`, `SensitiveFileRef`, `LanguageStat`, `LayerAssignment`, `TopicRef`, `LearningGoal`, `MessageType`, `RuntimeEventType`, `ErrorCode` 等。后续 Agent 会自行补齐，导致 schema 分裂。
2. **M6 数据契约不足**：ARCH-08 明确需要 prompt 模板结构、回答结构、流式解析结构；v1 只定义了 `MessageRecord`，没有稳定的 prompt 输入和回答输出契约。
3. **M7 通信结构缺口需要后续接口规范承接**：ARCH-09/ARCH-10 明确要求前后端通信结构；本文不补接口规范，只保留后端内部运行态事件对象，避免后续接口 Agent 被 v1 的模糊边界误导。
4. **降级语义不够严格**：非 Python 降级、大仓库降级、入口未知、流程无法形成、分层无法稳定应统一表达，且不能让下游误输出确定性 Python 入口、import、流程或分层。
5. **证据结构不足以约束安全**：敏感文件证据必须能保留“存在”而不能保留正文摘录；v1 只有说明，没有完整字段约束。
6. **状态保持与交互子状态不完整**：OUT-9 要求的跨轮状态、IX-06 的全局状态、对话子状态、下一步建议按钮状态，需要形成一致枚举口径。

### v2 修正原则

v2 保留 v1 的 8 个核心实体，但补齐所有引用类型，并新增 M6 prompt 与回答数据契约和验证规则。本文不定义接口规范、路由实现细节、协议细节、前端组件 props 或数据库表。

### 架构口径裁决

`technical_architecture_v2.md` 曾保留过少量旧口径表述。该问题属于后续接口规范的裁决范围；本文只记录边界，不定义接口。

---

## <a id="ds2-01"></a>DS2-01 设计边界

### 本文负责

1. 后端内存中的核心实体结构。
2. M1-M7 跨模块传递的稳定数据对象。
3. M6 prompt 构建输入与结构化回答输出。
4. 降级、错误、证据、安全策略的统一值对象。
5. 生命周期、缓存、清理和验证约束。

### 本文不负责

1. FastAPI route 函数签名与协议细节。
2. 前端组件 props、样式、布局实现。
3. LLM provider SDK 参数细节。
4. 数据库表设计或持久化 schema。
5. 多 Agent、私有仓库、代码执行、自动修复等 v1 范围外能力。

---

## <a id="ds2-02"></a>DS2-02 总体约束

### 命名与序列化

- 实体名使用 PascalCase，字段名使用 snake_case。
- 时间字段使用 ISO 8601 字符串序列化，内部实现可用 `datetime`。
- `root_path` / `real_path` 仅后端安全判断使用，不直接展示给用户。
- `relative_path` 是下游显示和证据引用的默认路径口径。
- 列表字段默认为空列表，不使用 `null` 表示空集合；可缺失单值字段使用 `null`。

### 事实层与教学层

- M2/M3 输出属于事实层，不写入对话推进状态。
- M4 输出属于教学组织层，可引用事实层对象，但不替代事实层对象。
- M6 只能消费 `TeachingSkeleton`、`ConversationState` 和必要证据切片，不反向修改 `AnalysisBundle`。

### 证据与候选

凡是入口、项目类型、模块职责、import 来源、分层、流程、阅读路径等候选或推断结论，必须满足：

- `confidence` 非空。
- `evidence_refs` 非空；如确实无证据，`confidence` 必须为 `unknown`，并写入 `unknown_items`。
- 静态推断不得被标记为确定运行事实。
- `FlowSummary` 必须使用候选语义，不能表达为真实运行时调用链。

### 安全

- 所有模块不得执行仓库代码。
- 除 `git clone` 外，不调用仓库相关 shell 命令。
- 不安装依赖。
- 命中敏感规则的文件只能记录存在，不能读取正文。
- `EvidenceRef.content_excerpt` 对敏感文件必须为 `null`。
- M6 prompt 不得包含敏感文件正文，也不得包含疑似密钥。

### 降级

降级不创建另一套 schema，统一通过以下字段表达：

- `SessionContext.active_degradations`
- `AnalysisBundle.analysis_mode`
- `TeachingSkeleton.skeleton_mode`
- `UnknownItem`
- `AnalysisWarning`
- `RuntimeEvent.degradation`

---

## <a id="ds2-03"></a>DS2-03 架构覆盖矩阵

| 架构模块 | 输入 | 输出 | 本文结构 |
|---------|------|------|---------|
| M1 仓库接入 | 用户输入字符串 | `RepositoryContext` 或 `UserFacingError` | DS2-05, DS2-11 |
| M2 文件树扫描 | `RepositoryContext.root_path`, `ReadPolicySnapshot` | `FileTreeSnapshot` | DS2-06 |
| M3 静态分析 | `FileTreeSnapshot` | `AnalysisBundle` | DS2-07 |
| M4 教学骨架组装 | `AnalysisBundle` | `TeachingSkeleton` | DS2-08 |
| M5 对话管理 | 用户请求、会话状态、M1-M4 产物 | `SessionContext`, `RuntimeEvent` | DS2-04, DS2-09, DS2-10 |
| M6 回答生成 | `PromptBuildInput` | `InitialReportAnswer \| StructuredAnswer`, `MessageRecord` | DS2-09 |
| M7 前端展示 | 后续接口规范定义 | 后续接口规范定义 | 不在本文范围 |

---

## <a id="ds2-04"></a>DS2-04 会话根结构

### `SessionStore`

```text
SessionStore
└── active_session: SessionContext | null
```

第一版只有一个活跃会话，不支持多用户、多租户或跨会话缓存。

### `SessionContext`

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | `str` | 会话唯一标识 |
| `status` | `SessionStatus` | 全局状态 |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 最近更新时间 |
| `repository` | `RepositoryContext \| null` | 当前仓库上下文 |
| `file_tree` | `FileTreeSnapshot \| null` | 当前文件树快照 |
| `analysis` | `AnalysisBundle \| null` | 当前分析产物 |
| `teaching_skeleton` | `TeachingSkeleton \| null` | 当前教学骨架 |
| `conversation` | `ConversationState` | 当前对话状态 |
| `last_error` | `UserFacingError \| null` | 最近一次面向用户错误 |
| `active_degradations` | `list[DegradationFlag]` | 当前生效降级 |
| `runtime_events` | `list[RuntimeEvent]` | 短时运行事件队列 |
| `temp_resources` | `TempResourceSet \| null` | 可清理临时资源 |

### 约束

- `status=idle` 时，`repository`, `file_tree`, `analysis`, `teaching_skeleton` 必须为 `null`。
- `status=chatting` 时，`repository`, `file_tree`, `analysis`, `teaching_skeleton` 必须非空。
- `runtime_events` 只为运行过程短时状态记录使用，完成后可丢弃，不持久化。

---

## <a id="ds2-05"></a>DS2-05 仓库接入结构

### `RepositoryContext`

| 字段 | 类型 | 说明 |
|------|------|------|
| `repo_id` | `str` | 仓库上下文唯一标识 |
| `source_type` | `RepoSourceType` | `local_path` 或 `github_url` |
| `display_name` | `str` | UI 展示名称，如 `owner/repo` 或目录名 |
| `input_value` | `str` | 用户原始输入，错误时也应保留 |
| `root_path` | `str` | 校验后的绝对真实路径 |
| `is_temp_dir` | `bool` | GitHub clone 临时目录为 `true` |
| `owner` | `str \| null` | GitHub owner，本地仓库为空 |
| `name` | `str \| null` | 仓库名 |
| `branch_or_ref` | `str \| null` | v1 可空 |
| `access_verified` | `bool` | 可访问性是否已验证 |
| `primary_language` | `str \| null` | M2 回填主语言 |
| `repo_size_level` | `RepoSizeLevel \| null` | M2 回填规模 |
| `source_code_file_count` | `int \| null` | M2 回填源码文件数 |
| `read_policy` | `ReadPolicySnapshot` | 读取与安全策略快照 |

### `TempResourceSet`

| 字段 | 类型 | 说明 |
|------|------|------|
| `clone_dir` | `str \| null` | GitHub clone 临时目录 |
| `created_by` | `str` | 创建模块，固定为 `m1_repo_access` |
| `cleanup_required` | `bool` | 切换仓库或关闭应用时是否必须清理 |
| `cleanup_status` | `CleanupStatus` | 清理状态 |
| `cleanup_error` | `str \| null` | 清理失败时的内部说明，不直接展示 |

### `ReadPolicySnapshot`

| 字段 | 类型 | 说明 |
|------|------|------|
| `read_only` | `bool` | v1 必须为 `true` |
| `allow_exec` | `bool` | v1 必须为 `false` |
| `allow_dependency_install` | `bool` | v1 必须为 `false` |
| `allow_private_github` | `bool` | v1 必须为 `false` |
| `sensitive_patterns` | `list[str]` | 敏感文件规则 |
| `ignore_patterns` | `list[str]` | 忽略规则 |
| `max_source_files_full_analysis` | `int` | 全量分析上限，默认 3000 |

### v1 默认敏感规则

```text
.env
.env.*
*.pem
*.key
*.crt
id_rsa
id_ed25519
credentials*
secrets*
token*
```

---

## <a id="ds2-06"></a>DS2-06 文件树结构

### `FileTreeSnapshot`

| 字段 | 类型 | 说明 |
|------|------|------|
| `snapshot_id` | `str` | 文件树快照 ID |
| `repo_id` | `str` | 所属仓库 |
| `generated_at` | `datetime` | 生成时间 |
| `root_path` | `str` | 扫描根目录，仅后端使用 |
| `nodes` | `list[FileNode]` | 文件树节点 |
| `ignored_rules` | `list[IgnoreRule]` | 生效忽略规则 |
| `sensitive_matches` | `list[SensitiveFileRef]` | 命中敏感规则的文件 |
| `language_stats` | `list[LanguageStat]` | 语言统计 |
| `primary_language` | `str` | 主语言，不确定时为 `unknown` |
| `repo_size_level` | `RepoSizeLevel` | 仓库规模 |
| `source_code_file_count` | `int` | 源码文件总数 |
| `degraded_scan_scope` | `ScanScope \| null` | 大仓库时的实际扫描范围 |

### `FileNode`

| 字段 | 类型 | 说明 |
|------|------|------|
| `node_id` | `str` | 节点 ID |
| `relative_path` | `str` | 相对仓库根路径，显示和引用主口径 |
| `real_path` | `str` | 真实路径，仅安全判断使用 |
| `node_type` | `FileNodeType` | 文件或目录 |
| `extension` | `str \| null` | 文件扩展名 |
| `status` | `FileNodeStatus` | 节点读取状态 |
| `is_source_file` | `bool` | 是否计入源码文件 |
| `is_python_source` | `bool` | 是否 Python 源文件 |
| `size_bytes` | `int \| null` | 文件大小 |
| `depth` | `int` | 树深度 |
| `parent_path` | `str \| null` | 父级相对路径 |
| `matched_rule_ids` | `list[str]` | 命中的忽略或敏感规则 |

### `IgnoreRule`

| 字段 | 类型 | 说明 |
|------|------|------|
| `rule_id` | `str` | 规则 ID |
| `pattern` | `str` | 匹配模式 |
| `source` | `IgnoreRuleSource` | 内置规则、`.gitignore` 或安全规则 |
| `action` | `FileNodeStatus` | 命中后的节点状态 |

### `SensitiveFileRef`

| 字段 | 类型 | 说明 |
|------|------|------|
| `relative_path` | `str` | 命中文件相对路径 |
| `matched_pattern` | `str` | 命中的敏感模式 |
| `content_read` | `bool` | 必须为 `false` |
| `user_notice` | `str` | 面向用户说明 |

### `LanguageStat`

| 字段 | 类型 | 说明 |
|------|------|------|
| `language` | `str` | 语言名，如 `Python`, `JavaScript`, `unknown` |
| `file_count` | `int` | 文件数 |
| `source_file_count` | `int` | 源码文件数 |
| `ratio` | `float` | 占比，0 到 1 |

### `ScanScope`

| 字段 | 类型 | 说明 |
|------|------|------|
| `scope_type` | `ScanScopeType` | 全量或降级范围 |
| `included_paths` | `list[str]` | 被纳入分析的相对路径 |
| `excluded_reason` | `str \| null` | 未全量分析的原因 |
| `user_notice` | `str \| null` | 面向用户说明 |

---

## <a id="ds2-07"></a>DS2-07 静态分析结构

### `AnalysisBundle`

| 字段 | 类型 | 说明 |
|------|------|------|
| `bundle_id` | `str` | 分析包 ID |
| `repo_id` | `str` | 所属仓库 |
| `file_tree_snapshot_id` | `str` | 对应文件树快照 |
| `generated_at` | `datetime` | 生成时间 |
| `analysis_mode` | `AnalysisMode` | 全量或降级模式 |
| `project_profile` | `ProjectProfileResult` | 项目画像 |
| `entry_candidates` | `list[EntryCandidate]` | 入口候选 |
| `import_classifications` | `list[ImportClassification]` | import 来源分类 |
| `module_summaries` | `list[ModuleSummary]` | 关键模块 |
| `layer_view` | `LayerViewResult` | 教学式分层视图 |
| `flow_summaries` | `list[FlowSummary]` | 候选流程骨架 |
| `reading_path` | `list[ReadingStep]` | 阅读路径 |
| `evidence_catalog` | `list[EvidenceRef]` | 证据集合 |
| `unknown_items` | `list[UnknownItem]` | 未知项 |
| `warnings` | `list[AnalysisWarning]` | 非致命警告 |

### `ProjectProfileResult` 与 `ProjectTypeCandidate`

| 对象 | 字段 |
|------|------|
| `ProjectProfileResult` | `project_types: list[ProjectTypeCandidate]`, `primary_language: str`, `summary_text: str \| null`, `confidence: ConfidenceLevel`, `evidence_refs: list[str]` |
| `ProjectTypeCandidate` | `type: ProjectType`, `reason: str`, `confidence: ConfidenceLevel`, `evidence_refs: list[str]` |

### `EntryCandidate`

| 字段 | 类型 | 说明 |
|------|------|------|
| `entry_id` | `str` | 入口候选 ID |
| `target_type` | `EntryTargetType` | 文件、命令、配置脚本、框架对象 |
| `target_value` | `str` | 相对路径、命令或配置项 |
| `reason` | `str` | 候选理由 |
| `confidence` | `ConfidenceLevel` | 置信度 |
| `rank` | `int` | 推荐顺序，从 1 开始 |
| `evidence_refs` | `list[str]` | 证据 ID |
| `unknown_items` | `list[UnknownItem]` | 该入口相关未知项 |

### `ImportClassification`

| 字段 | 类型 | 说明 |
|------|------|------|
| `import_id` | `str` | import 记录 ID |
| `import_name` | `str` | import 名称 |
| `source_type` | `ImportSourceType` | 内部、标准库、第三方、未知 |
| `used_by_files` | `list[str]` | 使用该 import 的相对路径 |
| `declared_in` | `list[str]` | 依赖声明文件，如 `pyproject.toml` |
| `basis` | `str` | 判断依据 |
| `worth_expanding_now` | `bool \| null` | 是否值得当前阶段展开 |
| `confidence` | `ConfidenceLevel` | 置信度 |
| `evidence_refs` | `list[str]` | 证据 ID |

### `ModuleSummary`

| 字段 | 类型 | 说明 |
|------|------|------|
| `module_id` | `str` | 模块 ID |
| `path` | `str` | 相对路径 |
| `module_kind` | `ModuleKind` | 目录、包、文件 |
| `responsibility` | `str \| null` | 候选职责 |
| `importance_rank` | `int \| null` | 重要性排序 |
| `likely_layer` | `LayerType \| null` | 候选层 |
| `main_path_role` | `MainPathRole` | 主路径、支撑路径或未知 |
| `upstream_modules` | `list[str]` | 上游模块 ID |
| `downstream_modules` | `list[str]` | 下游模块 ID |
| `related_entry_ids` | `list[str]` | 相关入口 |
| `related_flow_ids` | `list[str]` | 相关流程 |
| `worth_reading_now` | `bool \| null` | 是否建议当前阶段阅读 |
| `confidence` | `ConfidenceLevel` | 置信度 |
| `evidence_refs` | `list[str]` | 证据 ID |

### `LayerViewResult` 与 `LayerAssignment`

| 对象 | 字段 |
|------|------|
| `LayerViewResult` | `layer_view_id: str`, `status: DerivedStatus`, `layers: list[LayerAssignment]`, `uncertainty_note: str \| null`, `evidence_refs: list[str]` |
| `LayerAssignment` | `layer_type: LayerType`, `module_ids: list[str]`, `paths: list[str]`, `role_description: str`, `main_path_role: MainPathRole`, `confidence: ConfidenceLevel`, `evidence_refs: list[str]` |

### `FlowSummary` 与 `FlowStep`

| 对象 | 字段 |
|------|------|
| `FlowSummary` | `flow_id: str`, `entry_candidate_id: str \| null`, `flow_kind: FlowKind`, `input_source: str \| null`, `steps: list[FlowStep]`, `module_path: list[str]`, `layer_path: list[LayerType]`, `output_target: str \| null`, `fallback_reading_advice: str \| null`, `confidence: ConfidenceLevel`, `uncertainty_note: str \| null`, `evidence_refs: list[str]` |
| `FlowStep` | `step_no: int`, `description: str`, `module_id: str \| null`, `path: str \| null`, `layer_type: LayerType \| null`, `evidence_refs: list[str]`, `confidence: ConfidenceLevel` |

### `ReadingStep`

| 字段 | 类型 | 说明 |
|------|------|------|
| `step_no` | `int` | 1 到 6 |
| `target` | `str` | 文件、目录或模块 |
| `target_type` | `ReadingTargetType` | file / directory / module / flow / unknown |
| `reason` | `str` | 为什么先看 |
| `learning_gain` | `str` | 看完建立什么认知 |
| `skippable` | `str \| null` | 暂时可跳过内容 |
| `next_step_hint` | `str \| null` | 下一步 |
| `evidence_refs` | `list[str]` | 证据 ID |

### `EvidenceRef`

| 字段 | 类型 | 说明 |
|------|------|------|
| `evidence_id` | `str` | 证据 ID |
| `type` | `EvidenceType` | 证据类型 |
| `source_path` | `str \| null` | 相对路径 |
| `source_location` | `str \| null` | 行号、区块或配置键 |
| `content_excerpt` | `str \| null` | 非敏感摘录 |
| `is_sensitive_source` | `bool` | 是否来自敏感文件 |
| `note` | `str \| null` | 补充说明 |

### `UnknownItem`

| 字段 | 类型 | 说明 |
|------|------|------|
| `unknown_id` | `str` | 未知项 ID |
| `topic` | `UnknownTopic` | 未知主题 |
| `description` | `str` | 未知内容 |
| `related_paths` | `list[str]` | 相关相对路径 |
| `reason` | `str \| null` | 为什么未知 |
| `user_visible` | `bool` | 是否应进入首轮报告或回答的不确定项 |

### `AnalysisWarning`

| 字段 | 类型 | 说明 |
|------|------|------|
| `warning_id` | `str` | 警告 ID |
| `type` | `WarningType` | 警告类型 |
| `message` | `str` | 内部说明 |
| `user_notice` | `str \| null` | 可展示说明 |
| `related_paths` | `list[str]` | 相关路径 |

### 非 Python 降级约束

当 `analysis_mode=degraded_non_python`：

- `entry_candidates` 必须为空列表。
- `import_classifications` 必须为空列表。
- `flow_summaries` 必须为空列表，或仅包含 `flow_kind=no_reliable_flow` 且说明不可形成 Python 流程。
- `layer_view.status` 必须为 `unknown`，不得伪造教学式 Python 分层。
- `reading_path` 只能基于文件树结构给保守建议。
- 必须写入 `DegradationFlag(type=non_python_repo)`。

---

## <a id="ds2-08"></a>DS2-08 教学骨架结构

### `TeachingSkeleton`

| 字段 | 类型 | 说明 |
|------|------|------|
| `skeleton_id` | `str` | 骨架 ID |
| `repo_id` | `str` | 所属仓库 |
| `analysis_bundle_id` | `str` | 来源分析包 |
| `generated_at` | `datetime` | 生成时间 |
| `skeleton_mode` | `SkeletonMode` | full / degraded_large_repo / degraded_non_python |
| `overview` | `OverviewSection` | 仓库概览 |
| `focus_points` | `list[FocusPoint]` | 先抓什么，2-4 项 |
| `repo_mapping` | `list[ConceptMapping]` | 观察框架到当前仓库的映射 |
| `language_and_type` | `LanguageTypeSection` | 主语言与项目类型 |
| `key_directories` | `list[KeyDirectoryItem]` | 关键目录 |
| `entry_section` | `EntrySection` | 入口候选区块 |
| `flow_section` | `FlowSection` | 候选流程区块 |
| `layer_section` | `LayerSection` | 分层区块 |
| `dependency_section` | `DependencySection` | 依赖来源区块 |
| `recommended_first_step` | `RecommendedStep` | 推荐第一步 |
| `reading_path_preview` | `list[ReadingStep]` | 3-6 步阅读路径 |
| `unknown_section` | `list[UnknownItem]` | 不确定项 |
| `topic_index` | `TopicIndex` | 主题索引 |
| `suggested_next_questions` | `list[Suggestion]` | 首轮建议追问，1-3 条 |

### 首轮报告顺序约束

M4 组装首轮报告时必须按以下顺序消费骨架字段：

1. `overview`
2. `focus_points`
3. `repo_mapping`
4. `language_and_type`
5. `key_directories`
6. `entry_section`
7. `recommended_first_step`
8. `reading_path_preview`
9. `unknown_section`
10. `suggested_next_questions`

这对应 PRD OUT-1 和 IX-08。`flow_section`, `layer_section`, `dependency_section` 可以被 `focus_points`、`repo_mapping`、`topic_index` 引用，但首轮不应无节制展开。

### 教学区块对象

| 对象 | 字段 |
|------|------|
| `OverviewSection` | `summary: str`, `confidence: ConfidenceLevel`, `evidence_refs: list[str]` |
| `FocusPoint` | `focus_id: str`, `topic: LearningGoal`, `title: str`, `reason: str`, `related_refs: list[TopicRef]` |
| `ConceptMapping` | `concept: LearningGoal`, `mapped_paths: list[str]`, `mapped_module_ids: list[str]`, `explanation: str`, `confidence: ConfidenceLevel`, `evidence_refs: list[str]` |
| `LanguageTypeSection` | `primary_language: str`, `project_types: list[ProjectTypeCandidate]`, `degradation_notice: str \| null` |
| `KeyDirectoryItem` | `path: str`, `role: str`, `main_path_role: MainPathRole`, `confidence: ConfidenceLevel`, `evidence_refs: list[str]` |
| `EntrySection` | `status: DerivedStatus`, `entries: list[EntryCandidate]`, `fallback_advice: str \| null`, `unknown_items: list[UnknownItem]` |
| `FlowSection` | `status: DerivedStatus`, `flows: list[FlowSummary]`, `fallback_advice: str \| null` |
| `LayerSection` | `status: DerivedStatus`, `layer_view: LayerViewResult`, `fallback_advice: str \| null` |
| `DependencySection` | `items: list[ImportClassification]`, `unknown_count: int`, `summary: str \| null` |
| `RecommendedStep` | `target: str`, `reason: str`, `learning_gain: str`, `evidence_refs: list[str]` |

### `TopicIndex`

| 字段 | 类型 | 说明 |
|------|------|------|
| `structure_refs` | `list[TopicRef]` | 结构总览相关引用 |
| `entry_refs` | `list[TopicRef]` | 入口相关引用 |
| `flow_refs` | `list[TopicRef]` | 流程相关引用 |
| `layer_refs` | `list[TopicRef]` | 分层相关引用 |
| `dependency_refs` | `list[TopicRef]` | 依赖相关引用 |
| `module_refs` | `list[TopicRef]` | 模块相关引用 |
| `reading_path_refs` | `list[TopicRef]` | 阅读路径相关引用 |
| `unknown_refs` | `list[TopicRef]` | 未知项相关引用 |

### `TopicRef`

| 字段 | 类型 | 说明 |
|------|------|------|
| `ref_id` | `str` | 引用 ID |
| `ref_type` | `TopicRefType` | 引用对象类型 |
| `target_id` | `str` | 被引用对象 ID |
| `topic` | `LearningGoal` | 主题 |
| `summary` | `str \| null` | 给 M6 的简短说明 |

---

## <a id="ds2-09"></a>DS2-09 对话与回答结构

### `ConversationState`

| 字段 | 类型 | 说明 |
|------|------|------|
| `current_repo_id` | `str \| null` | 当前仓库指针，必须与 `SessionContext.repository.repo_id` 一致 |
| `current_learning_goal` | `LearningGoal` | 当前学习目标 |
| `current_stage` | `TeachingStage` | 当前讲解阶段 |
| `current_focus_module_id` | `str \| null` | 当前聚焦模块 |
| `current_entry_candidate_id` | `str \| null` | 当前聚焦入口 |
| `current_flow_id` | `str \| null` | 当前聚焦流程 |
| `current_layer_view_id` | `str \| null` | 当前分层视图 |
| `explained_items` | `list[ExplainedItemRef]` | 已讲解对象 |
| `last_suggestions` | `list[Suggestion]` | 上一轮建议 |
| `depth_level` | `DepthLevel` | 浅/默认/深 |
| `messages` | `list[MessageRecord]` | 消息历史 |
| `history_summary` | `str \| null` | 近 N 轮摘要 |
| `sub_status` | `ConversationSubStatus` | 对话态子状态 |

### `ExplainedItemRef`

| 字段 | 类型 | 说明 |
|------|------|------|
| `item_type` | `TopicRefType` | 已讲解对象类型 |
| `item_id` | `str` | 对象 ID |
| `topic` | `LearningGoal` | 所属主题 |
| `explained_at_message_id` | `str` | 首次讲解所在消息 |

### `MessageRecord`

| 字段 | 类型 | 说明 |
|------|------|------|
| `message_id` | `str` | 消息 ID |
| `role` | `MessageRole` | user / agent / system |
| `message_type` | `MessageType` | 首轮报告、追问、回答、总结、错误、目标切换确认 |
| `created_at` | `datetime` | 创建时间 |
| `raw_text` | `str` | 原始文本，供 Markdown 渲染 |
| `structured_content` | `StructuredMessageContent \| null` | 结构化内容 |
| `initial_report_content` | `InitialReportContent \| null` | 首轮报告结构化载荷；仅 `message_type=initial_report` 时允许非空 |
| `related_goal` | `LearningGoal \| null` | 关联学习目标 |
| `related_topic_refs` | `list[TopicRef]` | 关联主题引用 |
| `suggestions` | `list[Suggestion]` | 当前消息建议 |
| `streaming_complete` | `bool` | 是否流式完成 |
| `error_state` | `MessageErrorState \| null` | 错误状态 |

### `InitialReportContent`

用于持久保存首轮报告的最终结构化区块，供 `GET /api/session` 恢复和前端最终渲染使用。该对象是 `TeachingSkeleton` 面向首轮报告的受控投影，不等同于完整骨架。

| 对象 | 字段 |
|------|------|
| `InitialReportContent` | `overview: OverviewSection`, `focus_points: list[FocusPoint]`, `repo_mapping: list[ConceptMapping]`, `language_and_type: LanguageTypeSection`, `key_directories: list[KeyDirectoryItem]`, `entry_section: EntrySection`, `recommended_first_step: RecommendedStep`, `reading_path_preview: list[ReadingStep]`, `unknown_section: list[UnknownItem]`, `suggested_next_questions: list[Suggestion]` |

约束：

- `message_type=initial_report` 时，`initial_report_content` 必须非空，`structured_content` 必须为 `null`。
- `message_type!=initial_report` 时，`initial_report_content` 必须为 `null`。
- `initial_report_content` 字段顺序必须对应 PRD OUT-1 与接口文档 `InitialReportContentDto`。

### `StructuredMessageContent`

对应 IX-04 / OUT-11 六段式结构。

| 字段 | 类型 | 说明 |
|------|------|------|
| `focus` | `str \| null` | 本轮重点 |
| `direct_explanation` | `str \| null` | 直接解释 |
| `relation_to_overall` | `str \| null` | 与整体关系 |
| `evidence_lines` | `list[EvidenceLine]` | 证据或判断依据 |
| `uncertainties` | `list[str]` | 不确定项 |
| `next_steps` | `list[Suggestion]` | 下一步建议 |

### `EvidenceLine`

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | `str` | 面向用户的证据说明 |
| `evidence_refs` | `list[str]` | 证据 ID |
| `confidence` | `ConfidenceLevel \| null` | 可选置信度 |

### `Suggestion`

| 字段 | 类型 | 说明 |
|------|------|------|
| `suggestion_id` | `str` | 建议 ID |
| `text` | `str` | 用户可点击文本 |
| `target_goal` | `LearningGoal \| null` | 点击后聚焦目标 |
| `related_topic_refs` | `list[TopicRef]` | 相关主题 |

### `PromptBuildInput`

M5 传给 M6 的稳定输入，避免 M6 直接读取全量会话对象。

| 字段 | 类型 | 说明 |
|------|------|------|
| `scenario` | `PromptScenario` | 首轮报告、多轮追问、目标切换、深浅调整、阶段性总结 |
| `user_message` | `str \| null` | 当前用户消息 |
| `teaching_skeleton` | `TeachingSkeleton` | 教学骨架 |
| `topic_slice` | `list[TopicRef]` | 根据意图抽取的主题切片 |
| `conversation_state` | `ConversationState` | 当前对话状态 |
| `history_summary` | `str \| null` | 历史摘要 |
| `depth_level` | `DepthLevel` | 深浅级别 |
| `output_contract` | `OutputContract` | 输出结构约束 |

### `OutputContract`

| 字段 | 类型 | 说明 |
|------|------|------|
| `required_sections` | `list[MessageSection]` | 必须按顺序输出的区块 |
| `max_core_points` | `int` | 默认 4，浅层级可为 2 |
| `must_include_next_steps` | `bool` | 必须为 `true` |
| `must_mark_uncertainty` | `bool` | 必须为 `true` |
| `must_use_candidate_wording` | `bool` | 对候选流程/分层必须为 `true` |

### `StructuredAnswer`

M6 完成回答解析后返回给 M5 的结构。

| 字段 | 类型 | 说明 |
|------|------|------|
| `answer_id` | `str` | 回答 ID |
| `message_type` | `MessageType` | 回答类型 |
| `raw_text` | `str` | 完整文本 |
| `structured_content` | `StructuredMessageContent` | 六段式内容 |
| `suggestions` | `list[Suggestion]` | 下一步建议，1-3 条 |
| `related_topic_refs` | `list[TopicRef]` | 相关主题 |
| `used_evidence_refs` | `list[str]` | 使用证据 ID |
| `warnings` | `list[AnalysisWarning]` | 回答阶段非致命问题 |

### `InitialReportAnswer`

M6 在首轮报告场景返回给 M5 的稳定结构，避免首轮报告只保留自由文本而缺失可恢复的结构化载荷。

| 字段 | 类型 | 说明 |
|------|------|------|
| `answer_id` | `str` | 回答 ID |
| `message_type` | `MessageType` | 必须为 `initial_report` |
| `raw_text` | `str` | 完整首轮报告文本 |
| `initial_report_content` | `InitialReportContent` | 最终首轮报告结构化载荷 |
| `suggestions` | `list[Suggestion]` | 首轮建议追问，1-3 条 |
| `used_evidence_refs` | `list[str]` | 使用证据 ID |
| `warnings` | `list[AnalysisWarning]` | 生成阶段非致命问题 |

---

## <a id="ds2-10"></a>DS2-10 运行态事件结构

本节只定义后端内部运行态事件对象，不定义接口协议或前端订阅方式。

### `RuntimeEvent`

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | `str` | 事件 ID |
| `session_id` | `str` | 所属会话 |
| `event_type` | `RuntimeEventType` | 事件类型 |
| `occurred_at` | `datetime` | 发生时间 |
| `status_snapshot` | `SessionStatus \| null` | 事件发生时全局状态 |
| `sub_status_snapshot` | `ConversationSubStatus \| null` | 对话子状态 |
| `step_key` | `ProgressStepKey \| null` | 分析步骤 |
| `step_state` | `ProgressStepState \| null` | pending/running/done/error |
| `message_id` | `str \| null` | 关联消息 |
| `message_chunk` | `str \| null` | 流式文本片段，仅作为内部事件内容 |
| `structured_delta` | `dict \| null` | 可选结构化增量 |
| `user_notice` | `str \| null` | 面向用户说明 |
| `error` | `UserFacingError \| null` | 错误 |
| `degradation` | `DegradationFlag \| null` | 降级 |
| `payload` | `dict \| null` | 小范围扩展字段 |

### 事件对象约束

- `RuntimeEvent` 属于运行态数据结构，不是长期业务事实。
- `event_id` 必须可去重。
- 进度、状态变化、降级、错误、回答文本片段都可以用该对象表达。
- 后续接口规范可以选择如何把该对象暴露给前端；本文不定义映射。

---

## <a id="ds2-11"></a>DS2-11 错误与降级结构

### `UserFacingError`

| 字段 | 类型 | 说明 |
|------|------|------|
| `error_code` | `ErrorCode` | 错误码 |
| `message` | `str` | 面向用户提示，不含堆栈 |
| `retryable` | `bool` | 是否可重试 |
| `stage` | `SessionStatus` | 错误发生阶段 |
| `input_preserved` | `bool` | 是否保留用户输入 |
| `internal_detail` | `str \| null` | 内部日志用，不发给前端或 LLM |

### `MessageErrorState`

| 字段 | 类型 | 说明 |
|------|------|------|
| `error` | `UserFacingError` | 错误 |
| `failed_during_stream` | `bool` | 是否流式中失败 |
| `partial_text_available` | `bool` | 是否有部分回答 |

### `DegradationFlag`

| 字段 | 类型 | 说明 |
|------|------|------|
| `degradation_id` | `str` | 降级 ID |
| `type` | `DegradationType` | 降级类型 |
| `reason` | `str` | 原因 |
| `user_notice` | `str` | 面向用户说明 |
| `started_at` | `datetime` | 启用时间 |
| `related_paths` | `list[str]` | 相关路径 |

### 错误码必须覆盖

- 本地路径不存在。
- 本地路径不是目录。
- 本地路径不可读。
- GitHub URL 格式非法。
- GitHub 仓库不可访问。
- Git clone 超时或失败。
- 路径越界或符号链接越界。
- 分析超时。
- 分析失败。
- LLM API 失败。
- LLM API 超时。
- 当前状态不允许该操作。

---

## <a id="ds2-12"></a>DS2-12 枚举口径

### 状态

#### `SessionStatus`

- `idle`
- `accessing`
- `access_error`
- `analyzing`
- `analysis_error`
- `chatting`

#### `ConversationSubStatus`

- `waiting_user`
- `agent_thinking`
- `agent_streaming`

#### `ClientView`

- `input`
- `analysis`
- `chat`

### 仓库与文件

#### `RepoSourceType`

- `local_path`
- `github_url`

#### `RepoSizeLevel`

- `small`
- `medium`
- `large`

#### `FileNodeType`

- `file`
- `directory`

#### `FileNodeStatus`

- `normal`
- `ignored`
- `sensitive_skipped`
- `unreadable`
- `out_of_scope`

#### `IgnoreRuleSource`

- `built_in`
- `gitignore`
- `security_policy`

#### `ScanScopeType`

- `full`
- `entry_neighborhood`
- `top_level_only`
- `conservative_structure_only`

#### `CleanupStatus`

- `not_needed`
- `pending`
- `completed`
- `failed`

### 分析

#### `AnalysisMode`

- `full_python`
- `degraded_large_repo`
- `degraded_non_python`

#### `SkeletonMode`

- `full`
- `degraded_large_repo`
- `degraded_non_python`

#### `ConfidenceLevel`

- `high`
- `medium`
- `low`
- `unknown`

#### `DerivedStatus`

- `formed`
- `heuristic`
- `unknown`

#### `ProjectType`

- `cli`
- `web_app`
- `library`
- `package`
- `script_collection`
- `unknown`

#### `EntryTargetType`

- `file`
- `command`
- `config_script`
- `framework_object`
- `unknown`

#### `ImportSourceType`

- `internal`
- `stdlib`
- `third_party`
- `unknown`

#### `ModuleKind`

- `directory`
- `package`
- `file`

#### `LayerType`

- `entry`
- `route_or_controller`
- `business_logic`
- `data_access`
- `utility_or_config`
- `unknown`

#### `MainPathRole`

- `main_path`
- `supporting`
- `unknown`

#### `FlowKind`

- `no_reliable_flow`
- `entry_neighborhood`
- `module_level_path`
- `teaching_data_flow`

#### `ReadingTargetType`

- `file`
- `directory`
- `module`
- `flow`
- `unknown`

#### `EvidenceType`

- `file_path`
- `readme_instruction`
- `config_entry`
- `dependency_declaration`
- `import_relation`
- `symbol`
- `directory_structure`
- `naming_convention`

#### `UnknownTopic`

- `project_type`
- `entry`
- `dependency`
- `module_role`
- `layer`
- `flow`
- `output_target`
- `security_skipped`
- `other`

#### `WarningType`

- `ast_parse_failed`
- `file_unreadable`
- `large_repo_limited`
- `insufficient_evidence`
- `sensitive_file_skipped`

### 对话与回答

#### `LearningGoal`

- `overview`
- `structure`
- `entry`
- `flow`
- `module`
- `dependency`
- `layer`
- `summary`

#### `TeachingStage`

- `not_started`
- `initial_report`
- `structure_overview`
- `entry_explained`
- `flow_explained`
- `layer_explained`
- `dependency_explained`
- `module_deep_dive`
- `summary`

#### `DepthLevel`

- `shallow`
- `default`
- `deep`

#### `MessageRole`

- `user`
- `agent`
- `system`

#### `MessageType`

- `initial_report`
- `user_question`
- `agent_answer`
- `goal_switch_confirmation`
- `stage_summary`
- `error`

#### `PromptScenario`

- `initial_report`
- `follow_up`
- `goal_switch`
- `depth_adjustment`
- `stage_summary`

#### `MessageSection`

- `focus`
- `direct_explanation`
- `relation_to_overall`
- `evidence`
- `uncertainty`
- `next_steps`

#### `TopicRefType`

- `overview`
- `entry_candidate`
- `import_classification`
- `module_summary`
- `layer_assignment`
- `flow_summary`
- `reading_step`
- `unknown_item`
- `evidence`

### 事件、错误、降级

#### `RuntimeEventType`

- `status_changed`
- `analysis_progress`
- `degradation_notice`
- `answer_stream_start`
- `answer_stream_delta`
- `answer_stream_end`
- `message_completed`
- `error`

#### `ProgressStepKey`

- `repo_access`
- `file_tree_scan`
- `entry_and_module_analysis`
- `dependency_analysis`
- `skeleton_assembly`
- `initial_report_generation`

#### `ProgressStepState`

- `pending`
- `running`
- `done`
- `error`

#### `DegradationType`

- `large_repo`
- `non_python_repo`
- `entry_not_found`
- `flow_not_reliable`
- `layer_not_reliable`
- `analysis_timeout`

#### `ErrorCode`

- `local_path_not_found`
- `local_path_not_directory`
- `local_path_not_readable`
- `github_url_invalid`
- `github_repo_inaccessible`
- `git_clone_timeout`
- `git_clone_failed`
- `path_escape_detected`
- `analysis_timeout`
- `analysis_failed`
- `llm_api_failed`
- `llm_api_timeout`
- `invalid_state`

---

## <a id="ds2-13"></a>DS2-13 生命周期与存储

### 创建顺序

1. 应用启动后创建 `SessionStore(active_session=null)`。
2. 用户提交仓库后创建或重置 `SessionContext`，状态置为 `accessing`。
3. M1 成功后写入 `RepositoryContext` 和 `TempResourceSet`。
4. M2 完成后写入 `FileTreeSnapshot`，回填 `RepositoryContext.primary_language`, `repo_size_level`, `source_code_file_count`。
5. M3 完成后写入 `AnalysisBundle`。
6. M4 完成后写入 `TeachingSkeleton`。
7. M6 首轮报告流式完成后，写入 `MessageRecord(message_type=initial_report)`。
8. M5 将 `status` 置为 `chatting`，`conversation.sub_status` 置为 `waiting_user`。
9. 多轮追问中追加 `MessageRecord`，更新 `ConversationState`。

### 清理顺序

用户切换仓库时：

1. 停止当前流式输出。
2. 记录状态变化运行事件。
3. 清理 `runtime_events` 队列。
4. 如 `temp_resources.cleanup_required=true`，删除临时 clone 目录并更新 `cleanup_status`。
5. 清空 `repository`, `file_tree`, `analysis`, `teaching_skeleton`, `active_degradations`, `last_error`。
6. 重置 `conversation`，其中 `depth_level=default`。
7. 将 `status` 置为 `idle`。

### 缓存策略

- 同一会话、同一仓库内，多轮对话复用 M2/M3/M4 产物。
- 不做磁盘缓存。
- 不做跨会话缓存。
- 不缓存敏感文件正文。
- LLM prompt caching 只属于 M6 调用优化，不改变本数据结构的持久化策略。

---

## <a id="ds2-14"></a>DS2-14 下游验收清单

后续 Agent 使用本文时必须核对：

1. M3 输出必须覆盖 PRD ANALYSIS 的 9 项最低产出：项目画像、关键目录/模块、入口、依赖、分层、流程、阅读路径、证据、未知项。
2. M3 不得依赖 LLM 生成分析事实。
3. M4 必须按 OUT-1 顺序组装首轮教学骨架。
4. M5 必须保持 OUT-9 的跨轮状态，且切换仓库时完整清理。
5. M6 每轮回答必须符合 OUT-11 六段式结构，且保留下一步建议。
6. 本文不定义接口规范；相关内容由后续接口规范处理。
7. 非 Python 仓库不得输出确定性 Python 入口、Python import、Python 主流程或伪造分层。
8. 大仓库必须标注降级，并限制 M3 分析范围。
9. 所有确定性判断必须有证据；证据不足时使用未知、候选或替代阅读建议。
10. 敏感文件只能记录存在，不能读取正文，不能进入 M6 prompt。
11. 所有面向用户错误必须使用 `UserFacingError.message`，不得暴露堆栈。
12. 第一版只维护单个 `SessionContext`，不得引入数据库或多租户结构。

---
