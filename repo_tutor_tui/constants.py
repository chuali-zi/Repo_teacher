from __future__ import annotations

BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                    Repo Tutor Terminal UI                   ║
║         输入仓库路径或 GitHub URL，完成首轮与多轮教学         ║
╚══════════════════════════════════════════════════════════════╝
"""

HELP_TEXT = """
命令：
  /help    显示帮助
  /new     清理当前会话并重新输入仓库
  /status  查看当前会话状态
  /debug   查看最近 5 条教学调试事件
  /quit    退出
"""

STEP_LABELS = {
    "repo_access": "仓库接入",
    "file_tree_scan": "文件树扫描",
    "entry_and_module_analysis": "入口与模块分析",
    "dependency_analysis": "依赖来源分析",
    "skeleton_assembly": "教学骨架组装",
    "initial_report_generation": "首轮报告生成",
}

STEP_ICONS = {
    "pending": "○",
    "running": "●",
    "done": "✓",
    "error": "✗",
}

QUIT_COMMANDS = {"/quit", "/exit", "/q"}
