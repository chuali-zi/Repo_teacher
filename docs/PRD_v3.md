# PRD v3: Repo Tutor

版本：v3.0  
状态：架构评审版 / 可拆解实现版  
来源：基于 `docs/PRD_v2.md` 的产品、可执行性与架构交付评审修订  
目标读者：产品、架构、研发、测试

## 0. v2 评审结论

### 0.1 总体判断

`PRD_v2` 的产品目的明确，核心方向可以理解，也基本适合交给资深架构师做方案设计。

它已经把 Repo Tutor 从一个泛化的“源码学习 Agent”收敛成了：面向初学者、优先支持 Python、只读分析仓库、通过静态证据和候选流程进行教学引导的单 Agent 产品。

但 `PRD_v2` 仍更像“产品与架构边界说明”，还不是完全可执行的研发规格。架构师能看懂方向，但在拆系统、估工、写接口和定义测试样例时，还需要继续补充实现边界、数据契约、流程状态、置信度规则和验收样例。

### 0.2 v2 的优点

1. **目标清楚**  
   目标不是写代码、运行代码或修仓库，而是教初学者理解真实工程。

2. **MVP 范围明显收敛**  
   第一版聚焦 Python 仓库，避免跨语言、私有仓库、多 Agent、代码执行等高风险扩散。

3. **承认静态分析边界**  
   主流程和数据流被定义为候选流程，并要求标注证据、置信度和不确定项，这是必要的产品降风险动作。

4. **输出契约初步成型**  
   FirstRoundReport、ReadingPath、FlowWalkthrough、DependencyExplanation、LearningState 等对象已经能帮助架构师理解系统边界。

5. **内部模块边界合理**  
   RepositoryAccess、RepositoryIndexer、PythonStaticAnalyzer、ContextManager、TeachingPlanner、TeachingResponder 等拆分方向是对的。

### 0.3 v2 的主要缺点

1. **端到端工作流仍不够明确**  
   v2 没有把“输入仓库 -> 建索引 -> 静态分析 -> 生成首轮教学 -> 多轮追问 -> 状态更新”的执行链路写成可实现流程。架构师能猜到，但研发拆任务时会出现理解偏差。

2. **P0 范围仍偏大**  
   v2 把入口识别、依赖识别、结构总览、阅读路径、候选主流程、多轮状态、工程认知引导全部列为 P0。方向合理，但必须明确每项的最低可交付层级，否则第一版容易膨胀。

3. **“候选主流程”缺少分级定义**  
   静态分析能做到的流程深度差异很大。v2 说不承诺完整调用链，但没有定义最小可接受流程是什么。V3 需要把流程讲解拆成分级能力。

4. **数据契约缺少可机器处理字段**  
   v2 的输出契约是表格说明，缺少 `schemaVersion`、`sessionId`、`evidenceRefs`、`confidenceReason`、`errorCode` 等字段，不利于前后端、测试和日志统一。

5. **学习状态只有字段，没有生命周期**  
   v2 写了 LearningState 的字段，但没有定义状态什么时候创建、更新、失效、重置、切换仓库或切换目标。

6. **安全边界还需要工程化**  
   v2 写了不读敏感文件、不执行代码，但需要补充符号链接、路径逃逸、文件大小阈值、临时 clone 目录、忽略规则、敏感文件命中策略。

7. **验收标准仍偏描述性**  
   v2 要求在 3 个 Python 仓库上完成能力，但没有定义固定测试仓库、断言字段、证据覆盖率、错误兜底和性能指标。

### 0.4 v3 修订目标

V3 的目标是让资深架构师拿到后能够直接回答：

- 第一版到底交付什么，不交付什么。
- 每个模块的输入输出是什么。
- 哪些结论必须来自静态证据，哪些可以是推断。
- 候选流程讲到什么深度算合格。
- 多轮状态如何维护和切换。
- 安全边界如何落到工程实现。
- 测试和验收如何判断通过。

## 1. 产品定义

### 1.1 产品名称

Repo Tutor

### 1.2 一句话定义

Repo Tutor 是一个面向初学者的只读源码仓库教学 Agent。它通过静态分析 Python 仓库的结构、入口、依赖、模块关系和候选主流程，主动引导用户建立最小工程认知，并支持围绕同一仓库的连续追问。

### 1.3 产品定位

Repo Tutor 是教学型 Agent，不是工程执行 Agent。

它要帮助用户回答：

- 这个仓库大概是什么项目。
- 应该先看哪些文件。
- 入口候选在哪里。
- 项目自己写的模块、标准库、第三方库分别是什么。
- 一条候选主流程大概怎么走。
- 当前阶段应该继续看什么。

它不负责：

- 运行仓库代码。
- 修改仓库代码。
- 生成 PR。
- 自动修复 bug。
- 做完整代码质量审查。
- 做跨语言完整调用链分析。
- 成为通用 Agent OS。

## 2. 目标用户与核心场景

### 2.1 目标用户

核心用户是学过基础编程、能看懂单个函数或类、但缺少真实工程阅读经验的初学者，例如大学生、实习生、初级开发者。

### 2.2 用户能力假设

用户能够：

- 提供一个本地仓库路径或 GitHub 公共仓库 URL。
- 理解基础 Python 语法。
- 理解文件、目录、函数、类、import 的基础含义。

用户通常不能稳定做到：

- 判断仓库入口。
- 判断哪些模块最重要。
- 判断 import 来源。
- 沿数据流或调用关系阅读真实工程。
- 在多轮追问中自己维护工程上下文。

### 2.3 核心使用场景

1. 用户输入本地 Python 仓库路径，系统生成首轮仓库教学报告。
2. 用户输入 GitHub 公共 Python 仓库 URL，系统只读获取仓库并生成阅读路径。
3. 用户追问“启动流程怎么走”，系统围绕入口候选输出候选流程。
4. 用户追问“这个 import 是谁家的”，系统解释内部模块、标准库、第三方库或未知。
5. 用户中途说“先不要讲整体，只看某个模块”，系统更新学习目标并继续。
6. 用户连续追问同一个仓库，系统保持当前仓库、目标、阶段和已讲解内容。

## 3. MVP 决策

### 3.1 第一版必须交付

P0 只交付“只读 Python 仓库教学闭环”：

- 本地仓库路径接入。
- GitHub 公共仓库 URL 接入。
- 文件树扫描、过滤和索引。
- Python 项目类型识别。
- Python 入口候选识别。
- Python import 来源识别。
- 仓库结构总览。
- 面向初学者的阅读路径。
- 候选主流程讲解，按静态证据分级输出。
- 多轮问答学习状态维护。
- 用户显式切换学习目标。
- 证据引用、置信度和不确定项标注。
- 安全只读访问。

### 3.2 第一版有限支持

非 Python 仓库仅支持：

- 文件树级结构总览。
- 关键文件和目录提示。
- 明确标注“当前语言暂不完整支持”。

不得输出确定性的 Python 入口、Python 依赖来源或主流程结论。

### 3.3 第一版不支持

- 私有 GitHub 仓库认证。
- 在线运行代码、测试、安装命令或脚本。
- 修改、删除、格式化仓库文件。
- 自动生成 PR 或 commit。
- 多仓库联合分析。
- PDF、课件、设计文档混合输入。
- 跨语言完整调用链。
- 复杂可视化架构图作为主交互。
- 多 Agent 编排平台。
- 通用 Agent OS。

## 4. 成功标准

第一版成功的标准是：

一个会基础 Python 但不会阅读工程的用户，在使用 Repo Tutor 后，可以说清当前仓库的项目类型、入口候选、关键目录、主要模块、依赖来源、候选主流程和下一步阅读顺序。

可量化标准：

- 在 3 个固定 Python 样例仓库上，首轮报告必须包含入口候选、关键目录、阅读路径、不确定项。
- 每个确定性结论必须至少引用 1 个证据。
- 候选主流程必须明确标注分析等级和置信度。
- 连续 5 轮追问中，系统不得丢失当前仓库和学习目标。
- 用户切换目标后，下一轮输出必须围绕新目标，而不是重复首轮总览。

## 5. 核心体验原则

### 5.1 主动带路

系统默认主动提出下一步，而不是等待用户自己知道该问什么。

### 5.2 证据优先

所有仓库判断都应尽量引用文件、符号、配置、README 命令或 import 关系。无法确认时必须标注为推断或未知。

### 5.3 候选而非伪确定

静态分析无法证明真实运行路径时，输出必须使用“候选入口”“候选流程”“可能的模块关系”等措辞。

### 5.4 先骨架后细节

默认教学顺序：

1. 仓库是什么。
2. 入口在哪里。
3. 先看哪些目录。
4. 主流程候选怎么走。
5. 模块如何协作。
6. 局部实现细节。

### 5.5 可打断可改向

用户可以随时切换目标，例如只看启动流程、只看依赖来源、只看某个模块、讲浅一点或讲深一点。

## 6. 关键概念定义

### 6.1 RepoSession

一次用户围绕一个仓库进行学习的会话。

必须包含：

- `sessionId`
- `repoId`
- `repoSource`
- `repoVersion`
- `createdAt`
- `lastActiveAt`
- `learningState`

### 6.2 RepositoryIndex

仓库只读索引，不保存敏感文件内容。

必须包含：

- 文件列表。
- 目录摘要。
- 语言分布。
- 关键配置文件。
- README 线索。
- Python 模块路径映射。
- 忽略文件统计。

### 6.3 EvidenceRef

系统输出结论时引用的证据。

字段：

| 字段 | 说明 |
|---|---|
| evidenceId | 证据唯一标识 |
| type | `FILE_PATH` / `CONFIG` / `README` / `IMPORT` / `SYMBOL` / `HEURISTIC` |
| path | 文件路径 |
| symbol | 可选，函数、类、变量或配置 key |
| lineStart | 可选，起始行 |
| lineEnd | 可选，结束行 |
| excerpt | 可选，短摘录，不得包含密钥 |
| reason | 该证据支持什么判断 |

### 6.4 Confidence

置信度只允许：

- `HIGH`：有直接配置、显式入口、README 命令或明确符号证据。
- `MEDIUM`：多条启发式证据一致，但缺少直接运行配置。
- `LOW`：只有弱命名约定、目录结构或单一启发式线索。
- `UNKNOWN`：无法可靠判断。

### 6.5 TeachingStage

教学阶段只允许：

- `ONBOARDING`
- `STRUCTURE_OVERVIEW`
- `ENTRY_EXPLANATION`
- `FLOW_WALKTHROUGH`
- `MODULE_DEEP_DIVE`
- `DEPENDENCY_EXPLANATION`
- `SUMMARY`

### 6.6 FlowAnalysisLevel

候选流程分析等级：

- `LEVEL_0_NO_FLOW`：无法形成流程，只能给阅读建议。
- `LEVEL_1_ENTRY_NEIGHBORHOOD`：能识别入口及入口附近调用。
- `LEVEL_2_MODULE_PATH`：能基于 import 和文件关系给出模块级路径。
- `LEVEL_3_SYMBOL_PATH`：能基于 AST 符号关系给出函数或类级候选路径。

第一版 P0 至少要求支持 `LEVEL_1_ENTRY_NEIGHBORHOOD` 和部分 `LEVEL_2_MODULE_PATH`。`LEVEL_3_SYMBOL_PATH` 可作为 P1 增强。

## 7. 功能需求

### F1. 仓库接入

优先级：P0

系统必须支持：

- 本地路径输入。
- GitHub 公共仓库 URL 输入。
- 只读访问仓库内容。
- 生成 `repoId`、`repoSource`、`repoVersion`。

本地仓库 `repoVersion` 可使用文件清单和 mtime/hash 生成快照指纹。GitHub 仓库优先使用 commit hash。

验收：

- 本地路径不存在时，返回明确错误。
- GitHub URL 非公开或不可访问时，返回明确错误。
- 成功接入后，不执行任何仓库代码。

### F2. 文件树扫描与过滤

优先级：P0

系统必须默认忽略：

- `.git/`
- `.venv/`
- `venv/`
- `__pycache__/`
- `node_modules/`
- `dist/`
- `build/`
- `.mypy_cache/`
- `.pytest_cache/`
- 大型二进制文件
- 图片、音视频、压缩包
- 常见敏感文件内容，例如 `.env`、密钥、证书、token 文件

建议阈值：

- 单文件超过 1 MB 默认不读取正文，只记录路径和大小。
- 仓库源码文件超过 3000 个时启用分阶段索引。
- README、配置文件、小型源码文件优先读取。

验收：

- 输出关键目录摘要，而不是原样 dump 全量文件树。
- 保留完整文件索引用于后续检索。
- 敏感文件只允许记录“存在但未读取内容”。

### F3. Python 项目画像

优先级：P0

系统必须识别：

- 主语言。
- Python 项目类型候选：`CLI`、`WEB_APP`、`LIBRARY`、`SCRIPT_COLLECTION`、`NOTEBOOK_PROJECT`、`UNKNOWN`。
- 关键配置文件：`pyproject.toml`、`requirements.txt`、`setup.py`、`setup.cfg`、`Pipfile`。
- README 中的安装、运行、入口线索。

验收：

- 无法确认项目类型时输出 `UNKNOWN`。
- 非 Python 仓库不得强行输出 Python 项目画像。

### F4. 入口候选识别

优先级：P0

入口线索包括：

- `__main__.py`
- `main.py`
- `app.py`
- `manage.py`
- `if __name__ == "__main__"`
- `pyproject.toml` scripts
- `setup.py` entry_points
- README 运行命令。
- 常见框架约定入口，例如 Flask、FastAPI、Django。

输出必须包含：

- 入口候选。
- 判断依据。
- 置信度。
- 推荐优先阅读入口。
- 多入口时的排序理由。

验收：

- 每个入口候选至少有 1 条 `EvidenceRef`。
- 找不到入口时输出 `UNKNOWN`，并给出替代阅读路径。

### F5. 依赖来源识别

优先级：P0

系统必须区分：

- `INTERNAL`
- `STDLIB`
- `THIRD_PARTY`
- `UNKNOWN`

判断顺序：

1. 根据仓库内部模块路径判断 `INTERNAL`。
2. 根据当前运行环境或配置指定 Python 版本的标准库集合判断 `STDLIB`。
3. 根据依赖声明文件判断 `THIRD_PARTY`。
4. 根据 import 名称启发式补充判断。
5. 无法确认时输出 `UNKNOWN`。

输出必须包含：

- import 名称。
- 来源类型。
- 使用它的文件。
- 在当前流程中的作用。
- 当前是否值得展开阅读。
- 判断依据。

验收：

- 不能把未知依赖强行归类为第三方。
- 对相对 import 必须优先按内部模块处理。

### F6. 首轮教学报告

优先级：P0

首次分析成功后，系统必须输出 FirstRoundReport。

首轮报告必须让用户知道：

- 仓库大概是什么。
- 当前应该先抓什么观察框架。
- 关键目录有哪些。
- 入口候选在哪里。
- 第一阶段最建议看什么。
- 后续可以继续问什么。
- 当前有哪些不确定项。

验收：

- 单轮默认不超过 4 个核心认知点。
- 必须包含下一步建议。
- 必须包含不确定项，即使为空也要显式输出。

### F7. 阅读路径生成

优先级：P0

系统必须生成 3 到 6 步阅读路径。

每一步包含：

- 目标文件、目录或模块。
- 为什么看它。
- 看完应建立什么认知。
- 暂时可以跳过什么。
- 证据。
- 下一步。

验收：

- 阅读路径必须基于当前仓库证据。
- 不得生成脱离仓库的通用学习路线。

### F8. 候选主流程讲解

优先级：P0

系统必须围绕一个入口候选输出候选主流程。

P0 最小交付：

- 识别入口文件或入口命令。
- 说明入口附近直接调用或导入的模块。
- 给出模块级候选路径。
- 标注 FlowAnalysisLevel。
- 标注 confidence。
- 标注 unknowns。

不要求：

- 证明真实运行时调用链。
- 覆盖动态注册、反射、装饰器副作用、框架注入。
- 完整跨进程或跨服务数据流。

验收：

- 如果没有足够证据，必须输出 `LEVEL_0_NO_FLOW`。
- 不得把候选流程描述成确定真实流程。
- 每个流程步骤尽量引用证据；无法引用时必须说明是推断。

### F9. 模块关系讲解

优先级：P0

系统必须解释核心模块的：

- 职责。
- 上游。
- 下游。
- 是否在候选主路径上。
- 当前是否值得深入。

验收：

- 至少覆盖首轮报告中提到的关键模块。
- 不能把目录名直接等同于职责，必须结合文件名、import、README 或配置证据。

### F10. 多轮状态维护

优先级：P0

系统必须维护 LearningState。

字段：

| 字段 | 说明 |
|---|---|
| currentRepoId | 当前仓库 |
| learningGoal | 当前学习目标 |
| teachingStage | 当前教学阶段 |
| focusModule | 当前聚焦模块 |
| selectedEntry | 当前入口候选 |
| selectedFlow | 当前流程候选 |
| explainedFiles | 已解释文件 |
| explainedModules | 已解释模块 |
| dependencyMapVersion | 依赖归类版本 |
| repositoryIndexVersion | 仓库索引版本 |
| lastUserIntent | 最近用户意图 |
| nextSuggestion | 下一步建议 |

状态更新规则：

- 新仓库输入时创建新 RepoSession。
- 同仓库追问时复用当前 RepoSession。
- 用户显式切换目标时更新 `learningGoal` 和 `teachingStage`。
- 用户指定模块时更新 `focusModule`。
- 仓库版本变化时索引和分析缓存失效。

验收：

- 连续 5 轮追问不得重复从零介绍仓库。
- 用户切换目标后，下一轮必须围绕新目标。

### F11. 学习目标切换

优先级：P0

用户可以切换到：

- `STRUCTURE`
- `ENTRY`
- `FLOW`
- `MODULE`
- `DEPENDENCY`
- `SUMMARY`

系统必须基于已有索引和分析结果重组讲解，不应重新接入仓库。

验收：

- 用户说“只看依赖来源”时，下一轮不得继续讲阅读路径。
- 用户说“讲浅一点”时，输出应降低术语密度。
- 用户说“讲深一点”时，可以增加证据、调用关系和实现细节。

### F12. 上下文管理 MVP

优先级：P0

第一版 ContextManager 不要求复杂实验能力，但必须具备清晰边界。

必须支持：

- 从 RepositoryIndex 取文件和摘要。
- 从 PythonStaticAnalyzer 取入口、依赖、模块关系和流程候选。
- 从 LearningState 取当前目标和阶段。
- 从对话历史取最近上下文。
- 控制上下文预算。
- 为 TeachingPlanner 提供带证据的上下文包。

验收：

- TeachingResponder 不得直接读取文件系统。
- ContextManager 不得修改分析结论。
- 上下文包必须可日志化。

### F13. 阶段性总结

优先级：P1

系统在一个阶段结束时输出：

- 已经理解了什么。
- 还缺什么。
- 下一阶段建议。
- 可选自查问题。

自查问题不应阻塞继续学习。

### F14. 摘要缓存

优先级：P1

系统应缓存：

- 文件摘要。
- 模块摘要。
- 入口候选分析。
- 依赖归类结果。
- 流程候选结果。

缓存必须随 `repoVersion` 或文件 hash 变化失效。

### F15. 实验日志

优先级：P2

系统应记录：

- 用户问题。
- 用户意图。
- 当前 LearningState。
- 召回的上下文单元。
- 使用的 EvidenceRef。
- 最终输出关联证据。

日志不得包含敏感文件正文。

## 8. 输出数据契约

### 8.1 通用响应 Envelope

所有结构化输出建议包含：

| 字段 | 说明 |
|---|---|
| schemaVersion | 输出契约版本 |
| sessionId | 当前会话 |
| repoId | 当前仓库 |
| responseType | 响应类型 |
| teachingStage | 当前教学阶段 |
| confidence | 总体置信度 |
| evidenceRefs | 本轮使用的证据 |
| uncertainty | 不确定项 |
| nextSuggestion | 下一步建议 |

### 8.2 FirstRoundReport

字段：

| 字段 | 说明 |
|---|---|
| repoSummary | 仓库一句话概览 |
| languageProfile | 主语言与项目类型候选 |
| observationFrame | 当前仓库应先观察什么 |
| keyDirectories | 关键目录和原因 |
| entryCandidates | 入口候选 |
| recommendedFirstStep | 推荐第一步 |
| readingPathPreview | 阅读路径预览 |
| nextOptions | 后续可选方向 |
| uncertainty | 不确定项 |

### 8.3 ReadingPath

字段：

| 字段 | 说明 |
|---|---|
| steps | 3 到 6 个阅读步骤 |
| target | 文件、目录或模块 |
| purpose | 为什么看 |
| learningOutcome | 看完建立什么认知 |
| skipForNow | 暂时跳过什么 |
| evidenceRefs | 证据 |
| nextStep | 下一步 |

### 8.4 FlowWalkthrough

字段：

| 字段 | 说明 |
|---|---|
| flowName | 流程名称 |
| analysisLevel | FlowAnalysisLevel |
| confidence | 置信度 |
| entryPoint | 入口文件、命令或符号 |
| steps | 候选流程步骤 |
| dataMovement | 数据如何流转 |
| moduleRoles | 模块角色 |
| evidenceRefs | 证据 |
| unknowns | 无法确认的部分 |

### 8.5 DependencyExplanation

字段：

| 字段 | 说明 |
|---|---|
| importName | import 名称 |
| sourceType | `INTERNAL` / `STDLIB` / `THIRD_PARTY` / `UNKNOWN` |
| usedBy | 使用文件 |
| roleInFlow | 在当前流程中的作用 |
| shouldExpandNow | 是否值得展开 |
| evidenceRefs | 证据 |
| confidence | 置信度 |

## 9. 系统架构边界

### 9.1 对外形态

对外是单 Agent 对话体验。用户不需要理解内部模块，也不需要选择分析器或上下文策略。

### 9.2 内部模块

第一版至少包含：

1. **RepositoryAccess**  
   只读接入本地仓库或 GitHub 公共仓库。

2. **RepositoryIndexer**  
   扫描文件树、过滤文件、识别语言、生成索引。

3. **PythonStaticAnalyzer**  
   识别 Python 入口、import 来源、模块关系和候选流程线索。

4. **LearningStateTracker**  
   创建、更新、重置和读取 RepoSession 与 LearningState。

5. **ContextManager**  
   根据当前目标召回索引、摘要、证据和历史上下文。

6. **TeachingPlanner**  
   决定本轮讲什么、讲多深、下一步建议什么。

7. **TeachingResponder**  
   生成面向初学者的自然语言讲解。

8. **TraceLogger**  
   记录证据、上下文召回和状态变化。

### 9.3 依赖约束

- RepositoryAccess 不执行仓库代码。
- RepositoryIndexer 不生成教学文案。
- PythonStaticAnalyzer 不直接面对用户输出。
- ContextManager 不改变分析结论。
- TeachingPlanner 不直接读取文件系统。
- TeachingResponder 只能使用 ContextManager 提供的上下文。
- LearningStateTracker 不保存仓库全文。

推荐依赖方向：

```text
RepositoryAccess -> RepositoryIndexer -> PythonStaticAnalyzer
RepositoryIndexer -> ContextManager
PythonStaticAnalyzer -> ContextManager
LearningStateTracker -> ContextManager
LearningStateTracker -> TeachingPlanner
ContextManager -> TeachingPlanner -> TeachingResponder
TeachingPlanner -> LearningStateTracker
ContextManager -> TraceLogger
PythonStaticAnalyzer -> TraceLogger
TeachingResponder -> TraceLogger
```

## 10. 端到端工作流

### 10.1 创建仓库学习会话

1. 用户输入本地路径或 GitHub URL。
2. RepositoryAccess 校验来源。
3. RepositoryAccess 只读获取仓库。
4. RepositoryIndexer 建立文件索引。
5. PythonStaticAnalyzer 生成 Python 分析结果。
6. LearningStateTracker 创建 RepoSession。
7. ContextManager 组装首轮上下文。
8. TeachingPlanner 生成首轮教学计划。
9. TeachingResponder 输出 FirstRoundReport。

### 10.2 多轮追问

1. 用户提出问题。
2. 系统识别用户意图和目标。
3. LearningStateTracker 更新学习状态。
4. ContextManager 根据目标召回相关证据。
5. TeachingPlanner 决定回答范围和深度。
6. TeachingResponder 输出回答。
7. LearningStateTracker 记录已解释内容和下一步建议。

### 10.3 切换学习目标

1. 用户显式改变目标。
2. 系统更新 `learningGoal`。
3. 如果目标需要新分析，调用 PythonStaticAnalyzer 的已有结果或增量分析。
4. 输出围绕新目标的回答。
5. 保留同一 RepoSession，不重新介绍整个仓库。

### 10.4 仓库变化

如果本地仓库文件变化或 GitHub commit 变化：

- RepositoryIndex 失效。
- PythonStaticAnalyzer 结果失效。
- 摘要缓存失效。
- LearningState 可保留，但必须标注分析版本已更新。

## 11. 安全与隐私

### 11.1 禁止行为

系统不得：

- 执行仓库代码。
- 运行测试。
- 安装依赖。
- 执行 shell 脚本。
- 修改或删除文件。
- 输出疑似密钥。
- 读取敏感文件正文。

### 11.2 敏感文件处理

命中以下模式时默认不读取正文：

- `.env`
- `.env.*`
- `*.pem`
- `*.key`
- `*.crt`
- `id_rsa`
- `id_ed25519`
- `credentials*`
- `secrets*`
- `token*`

系统可以记录：

- 文件存在。
- 文件路径。
- 文件类型。
- “因安全策略未读取内容”。

### 11.3 路径与符号链接

本地仓库访问必须防止路径逃逸：

- 解析真实路径。
- 确保读取目标仍在仓库根目录内。
- 符号链接指向仓库外部时默认不跟随。

### 11.4 GitHub 仓库

第一版只支持公开仓库。

如果需要 clone：

- 使用临时只读工作目录。
- 不执行 hook。
- 不安装依赖。
- 记录 commit hash。

## 12. 非功能需求

### 12.1 性能

目标：

- 小型仓库：少于 500 个源码文件，30 秒内开始首轮输出。
- 中型仓库：500 到 3000 个源码文件，90 秒内开始首轮输出。
- 大型仓库：超过 3000 个源码文件，必须启用过滤、采样、分阶段分析。

### 12.2 准确性

- 确定性结论必须有证据。
- 推断必须标注推断。
- 无法判断必须输出 `UNKNOWN`。
- 候选流程必须标注 FlowAnalysisLevel。

### 12.3 可维护性

- 分析模块、上下文模块、教学模块必须分离。
- 输出契约必须版本化。
- 新增语言支持时，不应重写 TeachingResponder。

### 12.4 可测试性

以下模块必须可单独测试：

- RepositoryAccess
- RepositoryIndexer
- PythonStaticAnalyzer
- LearningStateTracker
- ContextManager
- TeachingPlanner

## 13. 验收标准

### 13.1 固定样例仓库

第一版至少准备 3 个固定测试仓库，使用固定 commit 或本地 fixture：

1. 小型 Python CLI 项目。
2. 小型 Python Web 项目，例如 Flask、FastAPI 或 Django。
3. Python library/package 项目。

每个样例仓库必须预先标注：

- 期望入口候选。
- 关键目录。
- 主要内部模块。
- 代表性标准库 import。
- 代表性第三方 import。
- 至少一条候选主流程。

### 13.2 功能验收

每个样例仓库必须通过：

- 成功创建 RepoSession。
- 成功生成 RepositoryIndex。
- 成功生成 FirstRoundReport。
- 至少识别 1 个入口候选，或明确输出 `UNKNOWN`。
- 生成 3 到 6 步 ReadingPath。
- 能解释至少 5 个 import 来源。
- 能输出 1 条 FlowWalkthrough，或输出 `LEVEL_0_NO_FLOW` 并说明原因。
- 支持连续 5 轮追问。
- 支持用户切换学习目标。

### 13.3 输出验收

首轮输出必须包含：

- 仓库一句话概览。
- 主语言和项目类型候选。
- 关键目录。
- 入口候选。
- 推荐第一步。
- 下一步建议。
- 不确定项。

每个确定性判断必须关联至少 1 条 EvidenceRef。

### 13.4 状态验收

连续 5 轮对话中：

- `currentRepoId` 不应丢失。
- `learningGoal` 不应无故变化。
- `focusModule` 变化时必须符合用户意图或系统解释。
- 已解释内容不应重复从零讲。

### 13.5 安全验收

测试仓库中放置 `.env`、`secrets.json`、`id_rsa` 等文件时：

- 系统不得读取正文。
- 输出不得包含敏感文件内容。
- RepositoryIndex 只记录安全元信息。

### 13.6 架构验收

必须满足：

- TeachingResponder 不能直接读文件系统。
- PythonStaticAnalyzer 能单独运行并输出结构化分析结果。
- ContextManager 能替换召回策略。
- LearningStateTracker 能单独创建和更新状态。
- TraceLogger 能记录 evidence、context、state，不记录敏感正文。

## 14. 优先级

### P0

- 本地仓库接入。
- GitHub 公共仓库接入。
- 文件树扫描和过滤。
- Python 项目画像。
- 入口候选识别。
- import 来源识别。
- FirstRoundReport。
- ReadingPath。
- FlowWalkthrough P0 分级能力。
- LearningState。
- 学习目标切换。
- ContextManager MVP。
- 安全只读策略。

### P1

- 文件和模块摘要缓存。
- 阶段性总结。
- LEVEL_3_SYMBOL_PATH 候选流程。
- 更细分的模块职责解释。
- 用户深浅讲解偏好持久化。

### P2

- 实验日志分析后台。
- 多种 Context Policy 对比。
- 更多语言支持。
- 私有仓库认证。
- 更复杂可视化。
- 文档混合输入。

## 15. 里程碑

### M1. 只读仓库索引

完成 RepositoryAccess、RepositoryIndexer、安全过滤、RepositoryIndex 输出。

验收重点：

- 能读本地仓库和公开 GitHub 仓库。
- 不执行代码。
- 不读取敏感文件正文。

### M2. Python 静态分析

完成 PythonStaticAnalyzer 的入口识别、依赖归类、项目画像和基础模块关系。

验收重点：

- 能输出入口候选和 import 来源。
- 每项判断有证据或明确 UNKNOWN。

### M3. 首轮教学闭环

完成 ContextManager MVP、TeachingPlanner、TeachingResponder、FirstRoundReport、ReadingPath。

验收重点：

- 用户首轮知道仓库是什么、先看什么、为什么。

### M4. 候选流程与多轮状态

完成 FlowWalkthrough P0、LearningStateTracker、学习目标切换。

验收重点：

- 连续 5 轮追问不丢上下文。
- 用户切换目标后系统能改向。

### M5. 缓存与实验预留

完成摘要缓存、TraceLogger、Context Policy 抽象。

验收重点：

- 可支撑后续 Virtual Context / Working Context Manager 实验。

## 16. 架构师交付要求

请基于本 PRD 输出系统架构方案，至少包含：

- 模块划分。
- 模块职责。
- 核心数据结构。
- 端到端时序图或流程说明。
- RepositoryIndex、PythonAnalysisResult、LearningState、ContextPackage 的字段设计。
- 入口识别和依赖归类策略。
- 候选主流程的分级实现方案。
- 安全只读策略。
- 缓存与失效策略。
- 测试方案。
- P0/P1/P2 拆解估算。

## 17. 给架构师的一句话任务

请设计一个对外单 Agent、内部模块化的 Repo Tutor 系统。第一版只做 Python 仓库的只读静态教学分析，必须围绕“仓库接入、文件索引、入口候选、依赖来源、候选主流程、多轮学习状态、证据引用、上下文管理 MVP”落地。不得扩展成代码执行平台、自动修复工具、通用 Agent OS 或多 Agent 编排平台。

