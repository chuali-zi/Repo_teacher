# Codex Project AGENTS Super Strict Prompt

你现在的任务是：为当前仓库严格审计、重写、升级或新建一份项目级 `AGENTS.md`。

这是一个高标准交付任务，不是普通建议任务。
你的目标不是“写一份看起来像 AGENTS.md 的文档”，而是产出一份能够真实约束未来 agent 行为、提高修改质量、提高验收质量、减少低质量交付的项目级 `AGENTS.md`。

你必须做到：
- 先调研，再判断，再生成
- 不猜测，不编造，不偷懒
- 不只给抽象提纲，必须产出可直接落地的内容
- 对测试、验收、source of truth、风险边界写得严格、可执行、可审计

请严格按以下流程执行，不允许跳步。

==================================================
一、先研究高质量来源，不允许闭门造车
==================================================

先阅读以下高质量来源，优先使用 GitHub 仓库原文和官方文档，不要依赖二手总结：

- openai/openai-agents-python 的 AGENTS.md
- openai/codex 的 AGENTS.md
- vercel/vercel 的 AGENTS.md
- vercel/ai 的 AGENTS.md
- langchain-ai/langgraph 的 AGENTS.md
- langchain-ai/langchainjs 的 AGENTS.md
- openclaw/openclaw 的 AGENTS.md
- browser-use/browser-use 的 AGENTS.md
- significant-gravitas/autogpt 的 AGENTS.md
- generalaction/emdash 的 AGENTS.md
- agentsmd/agents.md
- OpenAI 官方关于 Codex / AGENTS 的说明

阅读目标：

1. 提炼优秀 `AGENTS.md` 中真正高价值的内容
2. 区分哪些模式适合：
   - 小项目
   - 中型项目
   - 大型 monorepo
   - AI / agent 项目
   - 通用仓库
3. 识别哪些写法是低价值噪音，例如：
   - 空泛原则
   - 无法执行的建议
   - 没有仓库依据的规则
   - 看起来完整但没有约束力的章节
4. 提炼哪些写法最能提高：
   - source of truth 的清晰度
   - 修改范围控制
   - 验收严格度
   - 测试完整性
   - 交付质量

你后续必须明确说明：
- 你实际参考了哪些来源
- 每类来源分别借鉴了什么
- 哪些模式你故意没有采纳，以及为什么没有采纳

==================================================
二、阅读当前仓库，禁止猜测
==================================================

在写任何 `AGENTS.md` 之前，必须先阅读当前仓库的实际内容。

至少检查这些内容（如果存在）：

- 根目录文件和目录
- README / docs / contributing 文档
- package.json / pnpm-workspace.yaml / turbo.json / nx.json
- pyproject.toml / uv.lock / requirements / Makefile / justfile
- Cargo.toml / go.mod / build scripts
- .github/workflows
- tests / examples / fixtures
- schema / contract / OpenAPI / GraphQL / protobuf / codegen 相关目录
- migrations / database / infra / deployment 相关目录
- 现有 `AGENTS.md`（如果存在）
- PR 模板、changesets、changelog、release 脚本（如果存在）

你必须确认这些事实，而不是猜：

1. 当前仓库是什么类型项目
2. 当前仓库的主要技术栈
3. 当前仓库的主要目录结构
4. 当前仓库的真实命令入口是什么
5. 当前仓库的 source of truth 在哪里
6. 当前仓库的高风险区域有哪些
7. 当前仓库的测试体系和验收路径是什么
8. 当前仓库是否适合分层 `AGENTS.md`
9. 当前仓库已有 `AGENTS.md` 是否有效、过时、冲突或空泛

禁止行为：
- 不要编造命令
- 不要编造目录职责
- 不要编造测试能力
- 不要把别的项目规则直接套进来
- 不要看到一个文件名就假设整个架构

如果信息不够，就继续读文件，直到足以支撑一个严谨的项目级 `AGENTS.md`。

==================================================
三、在生成之前，先做显式判断
==================================================

在真正生成 `AGENTS.md` 之前，先判断并说明：

1. 当前仓库最适合以下哪一种结构：
   - 单一根级 `AGENTS.md`
   - 根级 `AGENTS.md` + 少量子目录 `AGENTS.md`
   - 根级 `AGENTS.md` + 多个局部 `AGENTS.md`
2. 当前仓库最需要写清楚的内容是什么：
   - setup / commands
   - source of truth
   - 高风险边界
   - codegen 规则
   - release / changeset 规则
   - 测试 / 验收 / run order
   - 多 package / 多 app 边界
3. 当前仓库最不应该写进 `AGENTS.md` 的内容是什么：
   - README 式背景介绍
   - 与仓库无关的最佳实践
   - 没验证过的命令
   - 只适用于别的仓库的条款
4. 当前仓库未来最容易让 agent 出错的点是什么：
   - 改错目录
   - 改错 source of truth
   - 漏同步生成文件
   - 漏测边界条件
   - 只测 happy path
   - 忽略 release / changeset / migration 规则
   - 覆盖其他人的改动

你后续生成的 `AGENTS.md` 必须优先解决这些真实风险，而不是追求模板完整度。

==================================================
四、严格的生成标准
==================================================

请生成一份真正适用于当前仓库的 `AGENTS.md`，满足以下标准：

1. 面向当前仓库，不能泛泛而谈
2. 信息必须具体、可执行、可验证
3. 章节必须服务于实际开发，不为“看起来完整”而存在
4. 必须明确 source of truth
5. 必须明确命令入口，前提是这些命令已被仓库内容支撑
6. 必须明确验证和验收要求
7. 必须明确高风险区域和处理方式
8. 必须明确交付标准
9. 如果仓库是 monorepo，必须考虑 package / app / workspace 层级边界
10. 如果仓库有 codegen / contract / migration / release / changeset 机制，必须明确写规则
11. 如果仓库已有 `AGENTS.md`，先吸收有效内容，再进行重组、精简和加强，不要粗暴覆盖
12. 若无明确团队语言偏好，默认生成英文 `AGENTS.md`

==================================================
五、对测试、验收、交付质量的要求必须超严格
==================================================

最终生成的项目级 `AGENTS.md` 必须明确阻止未来 agent 做出以下低质量行为：

- 只做表面阅读就开始改
- 没搞清 source of truth 就动手
- 只改 happy path，不考虑边界
- 只跑一个浅层测试就宣称完成
- 用“理论上应该可以”替代真实验证
- 改动范围很大却只做局部验证
- 明明缺测试，却不补测试
- 没有说明风险、假设和未验证项就直接交付

因此，最终 `AGENTS.md` 必须明确体现以下原则：

1. Analyze enough to act correctly
2. Validation is part of the task, not an optional follow-up
3. Validation depth must match risk, surface area, and user impact
4. Happy paths are not enough for non-trivial changes
5. Edge cases and plausible failure modes must be considered
6. If relevant automated tests exist, run them
7. If important behavior lacks tests and adding one is practical, add one
8. High-risk changes require broader, not narrower, validation
9. Final handoff must explain:
   - what changed
   - why it changed
   - what was verified
   - how it was verified
   - what was not verified
   - why it was not verified
   - what risks or assumptions remain

如果当前仓库的测试体系不完善，也必须在 `AGENTS.md` 中明确写出：
- 现有测试能力边界
- 哪些区域容易漏测
- agent 应如何补足人工验证
- 在什么情况下不能把工作轻率地标记为完成

==================================================
六、推荐章节，但必须按仓库裁剪
==================================================

以下章节只是候选，不是强制目录。
你必须根据当前仓库实际情况裁剪，而不是机械照抄：

- Project Overview
- Repository Map
- Setup / Commands
- Source Of Truth
- Mandatory Rules
- Where To Change What
- High-Risk Areas
- Validation And Run Order
- Testing Expectations
- Task Completion Standards
- PR / Release Rules
- Collaboration Safety
- Final Handoff Expectations
- Nested AGENTS Strategy

要求：
- 小仓库不要硬写成企业级模板
- 大仓库不要只给一份极简空壳
- 只保留对当前仓库有价值的章节
- 章节标题可以调整，但内容职责必须覆盖到位

==================================================
七、输出格式必须可审计
==================================================

最终请按以下顺序输出结果：

1. 你实际参考了哪些优秀来源
2. 你从这些来源中提炼出的高价值模式
3. 你明确拒绝采纳了哪些模式，以及原因
4. 你对当前仓库的实际判断：
   - 项目类型
   - 技术栈
   - 目录结构
   - source of truth
   - 测试 / 验收方式
   - 高风险区域
   - 是否适合分层 AGENTS
5. 你打算如何生成或修改当前仓库的 `AGENTS.md`
6. 你最终产出的 `AGENTS.md`
7. 如果合适，附加建议的子目录 `AGENTS.md`
8. 最后列出三类清单：
   - 明确来自当前仓库事实的内容
   - 明确借鉴优秀仓库模式的内容
   - 仍需人工确认的内容

==================================================
八、禁止事项
==================================================

绝对不要做这些事：

- 只给提纲，不给成品
- 只给建议，不给可落地文本
- 只写原则，不写执行规则
- 编造命令
- 编造目录用途
- 编造测试能力
- 编造 release / changeset / codegen 规则
- 复制别的仓库规则后稍微改词就当成当前仓库产物
- 用空泛措辞替代真实约束
- 把浅层验证包装成“已充分验收”
- 为了模板完整而写低价值章节
- 因为仓库复杂就退回到抽象总结

==================================================
九、完成定义
==================================================

只有在满足以下条件时，任务才算完成：

1. 你已经读取了足够的优秀来源
2. 你已经读取了足够的当前仓库事实
3. 你已经明确 source of truth、验证路径和高风险边界
4. 你产出了一份可直接落地的项目级 `AGENTS.md`
5. 这份 `AGENTS.md` 明确提高了未来 agent 的：
   - 修改质量
   - 验收质量
   - 测试完整性
   - 交付清晰度

最终目标不是“写一份文档”，而是“建立一套能真实约束未来 agent 行为的项目级规则”。
