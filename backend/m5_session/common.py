from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from backend.contracts.domain import ProgressStepStateItem
from backend.contracts.enums import LearningGoal, ProgressStepKey, ProgressStepState


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def initial_progress_steps() -> list[ProgressStepStateItem]:
    return [
        ProgressStepStateItem(step_key=key, step_state=ProgressStepState.PENDING)
        for key in (
            ProgressStepKey.REPO_ACCESS,
            ProgressStepKey.FILE_TREE_SCAN,
            ProgressStepKey.INITIAL_REPORT_GENERATION,
        )
    ]


GOAL_KEYWORDS: tuple[tuple[LearningGoal, tuple[str, ...]], ...] = (
    (LearningGoal.ENTRY, ("入口", "启动", "main", "app", "route", "路由")),
    (LearningGoal.FLOW, ("流程", "调用链", "怎么走", "请求", "数据流", "flow")),
    (LearningGoal.MODULE, ("模块", "文件", "类", "函数", "module")),
    (LearningGoal.DEPENDENCY, ("依赖", "import", "包", "第三方")),
    (LearningGoal.LAYER, ("分层", "架构", "层", "layer")),
    (LearningGoal.STRUCTURE, ("结构", "目录", "先看哪里", "阅读顺序")),
    (LearningGoal.SUMMARY, ("总结", "小结", "回顾")),
)


TOPIC_ATTRS_BY_GOAL: dict[LearningGoal, tuple[str, ...]] = {}
