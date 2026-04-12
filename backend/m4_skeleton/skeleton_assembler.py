from __future__ import annotations

from backend.contracts.domain import (
    AnalysisBundle,
    ConceptMapping,
    DependencySection,
    EntrySection,
    FlowSection,
    FocusPoint,
    KeyDirectoryItem,
    LanguageTypeSection,
    LayerSection,
    OverviewSection,
    RecommendedStep,
    Suggestion,
    TeachingSkeleton,
)
from backend.contracts.enums import (
    AnalysisMode,
    ConfidenceLevel,
    DerivedStatus,
    LearningGoal,
    MainPathRole,
    SkeletonMode,
    UnknownTopic,
)
from backend.m4_skeleton.topic_indexer import build_topic_index
from backend.m4_skeleton.unknown_aggregator import aggregate_user_visible_unknowns


INITIAL_REPORT_FIELD_ORDER: tuple[str, ...] = (
    "overview",
    "focus_points",
    "repo_mapping",
    "language_and_type",
    "key_directories",
    "entry_section",
    "recommended_first_step",
    "reading_path_preview",
    "unknown_section",
    "suggested_next_questions",
)


def assemble_skeleton(analysis: AnalysisBundle) -> TeachingSkeleton:
    topic_index = build_topic_index(analysis)
    unknown_section = aggregate_user_visible_unknowns(analysis)

    key_directories = _build_key_directories(analysis)
    entry_section = _build_entry_section(analysis, unknown_section)
    flow_section = _build_flow_section(analysis)
    layer_section = _build_layer_section(analysis)
    dependency_section = _build_dependency_section(analysis, unknown_section)
    reading_path_preview = analysis.reading_path[:6]

    return TeachingSkeleton(
        skeleton_id=f"skeleton_{analysis.bundle_id}",
        repo_id=analysis.repo_id,
        analysis_bundle_id=analysis.bundle_id,
        generated_at=analysis.generated_at,
        skeleton_mode=_skeleton_mode(analysis),
        overview=_build_overview(analysis),
        focus_points=_build_focus_points(analysis, topic_index),
        repo_mapping=_build_repo_mapping(analysis, key_directories),
        language_and_type=_build_language_and_type(analysis),
        key_directories=key_directories,
        entry_section=entry_section,
        flow_section=flow_section,
        layer_section=layer_section,
        dependency_section=dependency_section,
        recommended_first_step=_build_recommended_first_step(analysis, key_directories),
        reading_path_preview=reading_path_preview,
        unknown_section=unknown_section,
        topic_index=topic_index,
        suggested_next_questions=_build_suggested_questions(topic_index),
    )


def _skeleton_mode(analysis: AnalysisBundle) -> SkeletonMode:
    return {
        AnalysisMode.FULL_PYTHON: SkeletonMode.FULL,
        AnalysisMode.DEGRADED_LARGE_REPO: SkeletonMode.DEGRADED_LARGE_REPO,
        AnalysisMode.DEGRADED_NON_PYTHON: SkeletonMode.DEGRADED_NON_PYTHON,
    }[analysis.analysis_mode]


def _build_overview(analysis: AnalysisBundle) -> OverviewSection:
    summary = analysis.project_profile.summary_text or (
        f"This repository is primarily {analysis.project_profile.primary_language} and needs a guided read from its key paths."
    )
    return OverviewSection(
        summary=summary,
        confidence=analysis.project_profile.confidence,
        evidence_refs=analysis.project_profile.evidence_refs,
    )


def _build_focus_points(analysis: AnalysisBundle, topic_index) -> list[FocusPoint]:
    focus_points: list[FocusPoint] = []

    if topic_index.structure_refs:
        focus_points.append(
            FocusPoint(
                focus_id="focus_structure",
                topic=LearningGoal.STRUCTURE,
                title="先看仓库结构",
                reason="先建立主路径、关键目录和模块分布，再看入口和流程会更稳。",
                related_refs=topic_index.structure_refs[:2],
            )
        )
    if analysis.entry_candidates:
        focus_points.append(
            FocusPoint(
                focus_id="focus_entry",
                topic=LearningGoal.ENTRY,
                title="确认入口候选",
                reason="入口决定程序从哪里开始，能帮助你快速建立运行视角。",
                related_refs=topic_index.entry_refs[:2],
            )
        )
    if analysis.flow_summaries:
        focus_points.append(
            FocusPoint(
                focus_id="focus_flow",
                topic=LearningGoal.FLOW,
                title="再追主流程",
                reason="沿候选流程看调用顺序，比逐文件散读更容易形成整体认知。",
                related_refs=topic_index.flow_refs[:2],
            )
        )
    if analysis.import_classifications:
        focus_points.append(
            FocusPoint(
                focus_id="focus_dependency",
                topic=LearningGoal.DEPENDENCY,
                title="区分内部模块和外部依赖",
                reason="先知道哪些能力来自仓库内部、哪些来自第三方，能减少阅读误判。",
                related_refs=topic_index.dependency_refs[:2],
            )
        )
    elif analysis.layer_view.status != DerivedStatus.UNKNOWN:
        focus_points.append(
            FocusPoint(
                focus_id="focus_layer",
                topic=LearningGoal.LAYER,
                title="建立分层视角",
                reason="分层能把入口、业务逻辑和支撑代码分开理解。",
                related_refs=topic_index.layer_refs[:2],
            )
        )

    return focus_points[:4]


def _build_repo_mapping(
    analysis: AnalysisBundle,
    key_directories: list[KeyDirectoryItem],
) -> list[ConceptMapping]:
    mappings: list[ConceptMapping] = []

    if key_directories:
        mappings.append(
            ConceptMapping(
                concept=LearningGoal.STRUCTURE,
                mapped_paths=[item.path for item in key_directories[:3]],
                mapped_module_ids=[],
                explanation="这些路径构成首轮理解仓库结构的主线。",
                confidence=key_directories[0].confidence,
                evidence_refs=_merge_refs(*(item.evidence_refs for item in key_directories[:3])),
            )
        )
    if analysis.entry_candidates:
        mappings.append(
            ConceptMapping(
                concept=LearningGoal.ENTRY,
                mapped_paths=[entry.target_value for entry in analysis.entry_candidates[:2]],
                mapped_module_ids=[],
                explanation="这些对象更像程序启动或接收请求的起点。",
                confidence=analysis.entry_candidates[0].confidence,
                evidence_refs=_merge_refs(*(entry.evidence_refs for entry in analysis.entry_candidates[:2])),
            )
        )
    if analysis.module_summaries:
        mappings.append(
            ConceptMapping(
                concept=LearningGoal.MODULE,
                mapped_paths=[module.path for module in analysis.module_summaries[:3]],
                mapped_module_ids=[module.module_id for module in analysis.module_summaries[:3]],
                explanation="这些模块更值得优先阅读，因为它们更接近主路径或职责描述更明确。",
                confidence=analysis.module_summaries[0].confidence,
                evidence_refs=_merge_refs(*(module.evidence_refs for module in analysis.module_summaries[:3])),
            )
        )

    return mappings


def _build_language_and_type(analysis: AnalysisBundle) -> LanguageTypeSection:
    notice = None
    if analysis.analysis_mode == AnalysisMode.DEGRADED_LARGE_REPO:
        notice = "仓库较大，当前骨架基于受限范围分析，建议优先沿主路径阅读。"
    elif analysis.analysis_mode == AnalysisMode.DEGRADED_NON_PYTHON:
        notice = "当前仓库不是 Python 主仓库，骨架已降级为基于结构的保守教学视图。"
    return LanguageTypeSection(
        primary_language=analysis.project_profile.primary_language,
        project_types=analysis.project_profile.project_types,
        degradation_notice=notice,
    )


def _build_key_directories(analysis: AnalysisBundle) -> list[KeyDirectoryItem]:
    ranked_modules = sorted(
        analysis.module_summaries,
        key=lambda item: (
            item.main_path_role != MainPathRole.MAIN_PATH,
            item.importance_rank is None,
            item.importance_rank or 999,
            item.path,
        ),
    )
    items: list[KeyDirectoryItem] = []
    seen_paths: set[str] = set()
    for module in ranked_modules:
        if module.path in seen_paths:
            continue
        role = module.responsibility or f"{module.module_kind} on the repository path"
        items.append(
            KeyDirectoryItem(
                path=module.path,
                role=role,
                main_path_role=module.main_path_role,
                confidence=module.confidence,
                evidence_refs=module.evidence_refs,
            )
        )
        seen_paths.add(module.path)
        if len(items) == 5:
            break
    return items


def _build_entry_section(analysis: AnalysisBundle, unknown_section) -> EntrySection:
    if analysis.entry_candidates:
        top_confidence = analysis.entry_candidates[0].confidence
        status = DerivedStatus.FORMED if top_confidence == ConfidenceLevel.HIGH else DerivedStatus.HEURISTIC
        return EntrySection(
            status=status,
            entries=analysis.entry_candidates,
            fallback_advice=None,
            unknown_items=[item for item in unknown_section if item.topic == UnknownTopic.ENTRY],
        )
    return EntrySection(
        status=DerivedStatus.UNKNOWN,
        entries=[],
        fallback_advice="先按阅读路径查看关键目录，再从配置脚本、命令入口或路由注册点反推入口。",
        unknown_items=[item for item in unknown_section if item.topic == UnknownTopic.ENTRY],
    )


def _build_flow_section(analysis: AnalysisBundle) -> FlowSection:
    if analysis.flow_summaries:
        status = DerivedStatus.FORMED
        if all(flow.confidence != ConfidenceLevel.HIGH for flow in analysis.flow_summaries):
            status = DerivedStatus.HEURISTIC
        return FlowSection(status=status, flows=analysis.flow_summaries, fallback_advice=None)
    return FlowSection(
        status=DerivedStatus.UNKNOWN,
        flows=[],
        fallback_advice="当前还没有可靠流程，可先从入口候选和关键模块之间的调用关系开始读。",
    )


def _build_layer_section(analysis: AnalysisBundle) -> LayerSection:
    fallback_advice = None
    if analysis.layer_view.status == DerivedStatus.UNKNOWN:
        fallback_advice = analysis.layer_view.uncertainty_note or "当前无法稳定形成分层视图，先按目录与入口组织阅读。"
    return LayerSection(
        status=analysis.layer_view.status,
        layer_view=analysis.layer_view,
        fallback_advice=fallback_advice,
    )


def _build_dependency_section(analysis: AnalysisBundle, unknown_section) -> DependencySection:
    unknown_count = sum(1 for item in analysis.import_classifications if item.source_type == "unknown")
    unknown_count += sum(1 for item in unknown_section if item.topic == UnknownTopic.DEPENDENCY)
    summary = None
    if analysis.import_classifications:
        summary = f"已识别 {len(analysis.import_classifications)} 个依赖来源，其中 {unknown_count} 个仍不确定。"
    elif unknown_count:
        summary = "当前没有可靠的依赖分类结果，部分依赖来源仍不确定。"
    return DependencySection(
        items=analysis.import_classifications,
        unknown_count=unknown_count,
        summary=summary,
    )


def _build_recommended_first_step(
    analysis: AnalysisBundle,
    key_directories: list[KeyDirectoryItem],
) -> RecommendedStep:
    if analysis.reading_path:
        first = analysis.reading_path[0]
        return RecommendedStep(
            target=first.target,
            reason=first.reason,
            learning_gain=first.learning_gain,
            evidence_refs=first.evidence_refs,
        )
    if analysis.entry_candidates:
        first_entry = analysis.entry_candidates[0]
        return RecommendedStep(
            target=first_entry.target_value,
            reason="先验证最可能的入口候选，能最快把结构阅读和运行路径连接起来。",
            learning_gain="你会先建立程序从哪里开始的最小认知。",
            evidence_refs=first_entry.evidence_refs,
        )
    if key_directories:
        first_dir = key_directories[0]
        return RecommendedStep(
            target=first_dir.path,
            reason="先从主路径目录建立结构感，再决定后续要跟哪条入口或流程。",
            learning_gain="你会先知道核心代码大概分布在哪些位置。",
            evidence_refs=first_dir.evidence_refs,
        )
    return RecommendedStep(
        target="repository root",
        reason="当前缺少更具体的阅读线索，先从仓库根目录确认顶层结构。",
        learning_gain="你会先建立目录级别的整体地图。",
        evidence_refs=[],
    )


def _build_suggested_questions(topic_index) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    if topic_index.entry_refs:
        suggestions.append(
            Suggestion(
                suggestion_id="suggest_entry",
                text="入口候选之间有什么区别？",
                target_goal=LearningGoal.ENTRY,
                related_topic_refs=topic_index.entry_refs[:2],
            )
        )
    if topic_index.structure_refs:
        suggestions.append(
            Suggestion(
                suggestion_id="suggest_structure",
                text="关键目录应该按什么顺序读？",
                target_goal=LearningGoal.STRUCTURE,
                related_topic_refs=topic_index.structure_refs[:2],
            )
        )
    if topic_index.flow_refs:
        suggestions.append(
            Suggestion(
                suggestion_id="suggest_flow",
                text="主流程大致是怎么串起来的？",
                target_goal=LearningGoal.FLOW,
                related_topic_refs=topic_index.flow_refs[:2],
            )
        )
    elif topic_index.module_refs:
        suggestions.append(
            Suggestion(
                suggestion_id="suggest_module",
                text="哪个核心模块最值得先深挖？",
                target_goal=LearningGoal.MODULE,
                related_topic_refs=topic_index.module_refs[:2],
            )
        )
    return suggestions[:3]


def _merge_refs(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for ref in group:
            if ref in seen:
                continue
            merged.append(ref)
            seen.add(ref)
    return merged
