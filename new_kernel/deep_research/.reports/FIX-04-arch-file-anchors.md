# FIX-04 · arch 默认 anchors 混入文件 (D1)

## What

按 RECON-E §D1 把 `_arch_default_anchors` 从"只挑目录"改成"≤3 目录 + ≤3 文件 (≤6 总数,目录在前)"。让 Investigator 在 arch 节既有目录可 `list_dir`,也有文件可 `read_file_range`,打破"目录-only anchors → round 2 必 list_dir"的结构性偏置。

## Why

RECON-E 关键发现 #1:arch 仅剩 1 轮 LLM ReAct,FIX-03 的 prefab 笔记开头("我们先扫了一眼仓库的顶层布局..." + `[dir]` 列表)叠加 `investigate.yaml:27-28` 的"路径优先选 anchors 中已有的"+"能 list 一个具体目录就不要 search 全仓",再加上原 `_arch_default_anchors` 只返回目录路径,导致 round 2 LLM 最阻力最小路径就是 `list_dir(api/)` 这种"再深一层目录"。Composer 拿到的 arch 笔记最终不含任何源码引用。混入 entry_candidates 文件 anchor 后,LLM 在 anchors 优先级框架内**就有了**合法的文件路径可以喂给 `read_file_range`。

## Changes

- **`deep_research/agents/decomposer.py:40-66`**:重写 `_arch_default_anchors`,签名不变。新逻辑遍历 reachable,前 3 个目录 + 前 3 个非目录分别收集,目录在前拼接,空 reachable 时返回 `()`(尾部 `tuple(reachable[:6])` 兜底)。25 行变 19 行 prod 代码改动。
- **`tests/test_deep_research_decomposer.py`**:
  - 更新 2 个既有 fallback 测试:`test_decomposer_invalid_json_falls_back_to_defaults_standard` 和 `test_decomposer_falls_back_to_default_pillars_on_llm_exception` 的 `anchor_map["arch"]` 期望值从 `("src/", "tests/")` 改成 `("src/", "tests/", "README.md", "package.json")`(`_FakeOverview` 的默认 `top_level_paths` 含 README.md + package.json 两个文件)。
  - 新增 3 个测试:`test_arch_default_anchors_mixes_dirs_and_files`(直接调用 helper,验证混合 + 顺序 + ≤6)、`test_arch_default_anchors_falls_back_when_no_files`(纯目录降级)、`test_decomposer_validate_subtopics_arch_anchors_include_files_when_overview_has_them`(端到端,LLM 返回 `{}` → fallback,验证 entry_candidates 文件出现在 arch.anchors)。

## Tests

测试总数从 6 → 8(test_deep_research_decomposer.py 末尾)。

- `test_arch_default_anchors_mixes_dirs_and_files`:reachable 含 4 dirs + 3 files,assert ≥1 dir、≥1 file、len≤6、dirs 全部下标 < files 全部下标。
- `test_arch_default_anchors_falls_back_when_no_files`:reachable=`("api/", "deep_research/")`,assert 结果原样返回。
- `test_decomposer_validate_subtopics_arch_anchors_include_files_when_overview_has_them`:`_FakeOverview` 含 entry_candidates `README.md` + `src/main.py`,LLM 返回 `{}` 触发 fallback,assert `arch.anchors` 含 ≥1 文件且至少 1 条来自 entry_candidates。

**验证状态**:`compileall` 与 `pytest` 在沙箱中无 Bash/PowerShell 权限,**已延期**至 chief engineer 三 fix 落地后统一 run。

## Risks

- **既有测试 breakage**:`_FakeOverview` 默认 `top_level_paths` 含 `README.md` 和 `package.json` 两个文件,所以"src/" 加 "tests/" 模式翻转成"目录在前 + 文件在后"4 元 tuple——已同步更新两处 assert。其他文件没用到 `_arch_default_anchors`,搜过无第三处 fallout。
- **prod 行为差异**:对 `top_level_paths` 全是文件 + 0 目录的边界仓库,新行为返回 `(file1, file2, file3)` 而非 `(file1,...,file6)` —— 损失了 3 个 anchor 槽位。但 RECON-E 没把"全文件仓库"列入威胁,且 ≥3 个文件已经够 LLM 选;接受。
- **签名稳定**:`_arch_default_anchors(reachable)` 入参出参类型未变,调用方 `_default_anchors_for` 与 `_validate_subtopics` 的 arch 注入分支无须修改。
