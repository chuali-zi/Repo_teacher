from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.enums import (
    AnalysisMode,
    CleanupStatus,
    ConfidenceLevel,
    ConversationSubStatus,
    DegradationType,
    DepthLevel,
    DerivedStatus,
    EntryTargetType,
    ErrorCode,
    EvidenceType,
    FileNodeStatus,
    FileNodeType,
    FlowKind,
    IgnoreRuleSource,
    ImportSourceType,
    LayerType,
    LearningGoal,
    MainPathRole,
    MessageRole,
    MessageSection,
    MessageType,
    ModuleKind,
    ProgressStepKey,
    ProgressStepState,
    ProjectType,
    PromptScenario,
    ReadingTargetType,
    RepoSizeLevel,
    RepoSourceType,
    RuntimeEventType,
    ScanScopeType,
    SessionStatus,
    SkeletonMode,
    StudentCoverageLevel,
    TeachingDebugEventType,
    TeachingDecisionAction,
    TeachingStage,
    TeachingPlanStepStatus,
    TopicRefType,
    UnknownTopic,
    WarningType,
)


class ContractModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True, arbitrary_types_allowed=True)


class ProgressStepStateItem(ContractModel):
    step_key: ProgressStepKey
    step_state: ProgressStepState


class ReadPolicySnapshot(ContractModel):
    read_only: bool
    allow_exec: bool
    allow_dependency_install: bool
    allow_private_github: bool
    sensitive_patterns: list[str] = Field(default_factory=list)
    ignore_patterns: list[str] = Field(default_factory=list)
    max_source_files_full_analysis: int = 3000


class RepositoryContext(ContractModel):
    repo_id: str
    source_type: RepoSourceType
    display_name: str
    input_value: str
    root_path: str
    is_temp_dir: bool
    owner: str | None = None
    name: str | None = None
    branch_or_ref: str | None = None
    access_verified: bool = False
    primary_language: str | None = None
    repo_size_level: RepoSizeLevel | None = None
    source_code_file_count: int | None = None
    read_policy: ReadPolicySnapshot


class TempResourceSet(ContractModel):
    clone_dir: str | None = None
    created_by: str = "m1_repo_access"
    cleanup_required: bool
    cleanup_status: CleanupStatus
    cleanup_error: str | None = None


class IgnoreRule(ContractModel):
    rule_id: str
    pattern: str
    source: IgnoreRuleSource
    action: FileNodeStatus


class SensitiveFileRef(ContractModel):
    relative_path: str
    matched_pattern: str
    content_read: bool = False
    user_notice: str


class LanguageStat(ContractModel):
    language: str
    file_count: int
    source_file_count: int
    ratio: float


class ScanScope(ContractModel):
    scope_type: ScanScopeType
    included_paths: list[str] = Field(default_factory=list)
    excluded_reason: str | None = None
    user_notice: str | None = None


class FileNode(ContractModel):
    node_id: str
    relative_path: str
    real_path: str
    node_type: FileNodeType
    extension: str | None = None
    status: FileNodeStatus
    is_source_file: bool
    is_python_source: bool
    size_bytes: int | None = None
    depth: int
    parent_path: str | None = None
    matched_rule_ids: list[str] = Field(default_factory=list)


class FileTreeSnapshot(ContractModel):
    snapshot_id: str
    repo_id: str
    generated_at: datetime
    root_path: str
    nodes: list[FileNode] = Field(default_factory=list)
    ignored_rules: list[IgnoreRule] = Field(default_factory=list)
    sensitive_matches: list[SensitiveFileRef] = Field(default_factory=list)
    language_stats: list[LanguageStat] = Field(default_factory=list)
    primary_language: str
    repo_size_level: RepoSizeLevel
    source_code_file_count: int
    degraded_scan_scope: ScanScope | None = None


class ProjectTypeCandidate(ContractModel):
    type: ProjectType
    reason: str
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class ProjectProfileResult(ContractModel):
    project_types: list[ProjectTypeCandidate] = Field(default_factory=list)
    primary_language: str
    summary_text: str | None = None
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class UnknownItem(ContractModel):
    unknown_id: str
    topic: UnknownTopic
    description: str
    related_paths: list[str] = Field(default_factory=list)
    reason: str | None = None
    user_visible: bool


class EntryCandidate(ContractModel):
    entry_id: str
    target_type: EntryTargetType
    target_value: str
    reason: str
    confidence: ConfidenceLevel
    rank: int
    evidence_refs: list[str] = Field(default_factory=list)
    unknown_items: list[UnknownItem] = Field(default_factory=list)


class ImportClassification(ContractModel):
    import_id: str
    import_name: str
    source_type: ImportSourceType
    used_by_files: list[str] = Field(default_factory=list)
    declared_in: list[str] = Field(default_factory=list)
    basis: str
    worth_expanding_now: bool | None = None
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class ModuleSummary(ContractModel):
    module_id: str
    path: str
    module_kind: ModuleKind
    responsibility: str | None = None
    importance_rank: int | None = None
    likely_layer: LayerType | None = None
    main_path_role: MainPathRole
    upstream_modules: list[str] = Field(default_factory=list)
    downstream_modules: list[str] = Field(default_factory=list)
    related_entry_ids: list[str] = Field(default_factory=list)
    related_flow_ids: list[str] = Field(default_factory=list)
    worth_reading_now: bool | None = None
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class LayerAssignment(ContractModel):
    layer_type: LayerType
    module_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    role_description: str
    main_path_role: MainPathRole
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class LayerViewResult(ContractModel):
    layer_view_id: str
    status: DerivedStatus
    layers: list[LayerAssignment] = Field(default_factory=list)
    uncertainty_note: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class FlowStep(ContractModel):
    step_no: int
    description: str
    module_id: str | None = None
    path: str | None = None
    layer_type: LayerType | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel


class FlowSummary(ContractModel):
    flow_id: str
    entry_candidate_id: str | None = None
    flow_kind: FlowKind
    input_source: str | None = None
    steps: list[FlowStep] = Field(default_factory=list)
    module_path: list[str] = Field(default_factory=list)
    layer_path: list[LayerType] = Field(default_factory=list)
    output_target: str | None = None
    fallback_reading_advice: str | None = None
    confidence: ConfidenceLevel
    uncertainty_note: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ReadingStep(ContractModel):
    step_no: int
    target: str
    target_type: ReadingTargetType
    reason: str
    learning_gain: str
    skippable: str | None = None
    next_step_hint: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class EvidenceRef(ContractModel):
    evidence_id: str
    type: EvidenceType
    source_path: str | None = None
    source_location: str | None = None
    content_excerpt: str | None = None
    is_sensitive_source: bool
    note: str | None = None


class AnalysisWarning(ContractModel):
    warning_id: str
    type: WarningType
    message: str
    user_notice: str | None = None
    related_paths: list[str] = Field(default_factory=list)


class AnalysisBundle(ContractModel):
    bundle_id: str
    repo_id: str
    file_tree_snapshot_id: str
    generated_at: datetime
    analysis_mode: AnalysisMode
    project_profile: ProjectProfileResult
    entry_candidates: list[EntryCandidate] = Field(default_factory=list)
    import_classifications: list[ImportClassification] = Field(default_factory=list)
    module_summaries: list[ModuleSummary] = Field(default_factory=list)
    layer_view: LayerViewResult
    flow_summaries: list[FlowSummary] = Field(default_factory=list)
    reading_path: list[ReadingStep] = Field(default_factory=list)
    evidence_catalog: list[EvidenceRef] = Field(default_factory=list)
    unknown_items: list[UnknownItem] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)


class TopicRef(ContractModel):
    ref_id: str
    ref_type: TopicRefType
    target_id: str
    topic: LearningGoal
    summary: str | None = None


class OverviewSection(ContractModel):
    summary: str
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class FocusPoint(ContractModel):
    focus_id: str
    topic: LearningGoal
    title: str
    reason: str
    related_refs: list[TopicRef] = Field(default_factory=list)


class ConceptMapping(ContractModel):
    concept: LearningGoal
    mapped_paths: list[str] = Field(default_factory=list)
    mapped_module_ids: list[str] = Field(default_factory=list)
    explanation: str
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class LanguageTypeSection(ContractModel):
    primary_language: str
    project_types: list[ProjectTypeCandidate] = Field(default_factory=list)
    degradation_notice: str | None = None


class KeyDirectoryItem(ContractModel):
    path: str
    role: str
    main_path_role: MainPathRole
    confidence: ConfidenceLevel
    evidence_refs: list[str] = Field(default_factory=list)


class EntrySection(ContractModel):
    status: DerivedStatus
    entries: list[EntryCandidate] = Field(default_factory=list)
    fallback_advice: str | None = None
    unknown_items: list[UnknownItem] = Field(default_factory=list)


class FlowSection(ContractModel):
    status: DerivedStatus
    flows: list[FlowSummary] = Field(default_factory=list)
    fallback_advice: str | None = None


class LayerSection(ContractModel):
    status: DerivedStatus
    layer_view: LayerViewResult
    fallback_advice: str | None = None


class DependencySection(ContractModel):
    items: list[ImportClassification] = Field(default_factory=list)
    unknown_count: int
    summary: str | None = None


class RecommendedStep(ContractModel):
    target: str
    reason: str
    learning_gain: str
    evidence_refs: list[str] = Field(default_factory=list)


class TopicIndex(ContractModel):
    structure_refs: list[TopicRef] = Field(default_factory=list)
    entry_refs: list[TopicRef] = Field(default_factory=list)
    flow_refs: list[TopicRef] = Field(default_factory=list)
    layer_refs: list[TopicRef] = Field(default_factory=list)
    dependency_refs: list[TopicRef] = Field(default_factory=list)
    module_refs: list[TopicRef] = Field(default_factory=list)
    reading_path_refs: list[TopicRef] = Field(default_factory=list)
    unknown_refs: list[TopicRef] = Field(default_factory=list)


class TeachingSkeleton(ContractModel):
    skeleton_id: str
    repo_id: str
    analysis_bundle_id: str
    generated_at: datetime
    skeleton_mode: SkeletonMode
    overview: OverviewSection
    focus_points: list[FocusPoint] = Field(default_factory=list)
    repo_mapping: list[ConceptMapping] = Field(default_factory=list)
    language_and_type: LanguageTypeSection
    key_directories: list[KeyDirectoryItem] = Field(default_factory=list)
    entry_section: EntrySection
    flow_section: FlowSection
    layer_section: LayerSection
    dependency_section: DependencySection
    recommended_first_step: RecommendedStep
    reading_path_preview: list[ReadingStep] = Field(default_factory=list)
    unknown_section: list[UnknownItem] = Field(default_factory=list)
    topic_index: TopicIndex
    suggested_next_questions: list[Suggestion] = Field(default_factory=list)


class ExplainedItemRef(ContractModel):
    item_type: TopicRefType
    item_id: str
    topic: LearningGoal
    explained_at_message_id: str


class EvidenceLine(ContractModel):
    text: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel | None = None


class Suggestion(ContractModel):
    suggestion_id: str
    text: str
    target_goal: LearningGoal | None = None
    related_topic_refs: list[TopicRef] = Field(default_factory=list)


class InitialReportContent(ContractModel):
    overview: OverviewSection
    focus_points: list[FocusPoint] = Field(default_factory=list)
    repo_mapping: list[ConceptMapping] = Field(default_factory=list)
    language_and_type: LanguageTypeSection
    key_directories: list[KeyDirectoryItem] = Field(default_factory=list)
    entry_section: EntrySection
    recommended_first_step: RecommendedStep
    reading_path_preview: list[ReadingStep] = Field(default_factory=list)
    unknown_section: list[UnknownItem] = Field(default_factory=list)
    suggested_next_questions: list[Suggestion] = Field(default_factory=list)


class StructuredMessageContent(ContractModel):
    focus: str | None = None
    direct_explanation: str | None = None
    relation_to_overall: str | None = None
    evidence_lines: list[EvidenceLine] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    next_steps: list[Suggestion] = Field(default_factory=list)


class UserFacingError(ContractModel):
    error_code: ErrorCode
    message: str
    retryable: bool
    stage: SessionStatus
    input_preserved: bool
    internal_detail: str | None = None


class UserFacingErrorException(Exception):
    def __init__(self, error: UserFacingError) -> None:
        self.error = error
        super().__init__(error.message)

    def __str__(self) -> str:
        return self.error.message


class MessageErrorState(ContractModel):
    error: UserFacingError
    failed_during_stream: bool
    partial_text_available: bool


class MessageRecord(ContractModel):
    message_id: str
    role: MessageRole
    message_type: MessageType
    created_at: datetime
    raw_text: str
    structured_content: StructuredMessageContent | None = None
    initial_report_content: InitialReportContent | None = None
    related_goal: LearningGoal | None = None
    related_topic_refs: list[TopicRef] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    streaming_complete: bool
    error_state: MessageErrorState | None = None

    @model_validator(mode="after")
    def validate_message_shape(self) -> MessageRecord:
        if self.message_type == MessageType.INITIAL_REPORT:
            if self.initial_report_content is None or self.structured_content is not None:
                raise ValueError(
                    "initial_report messages must include initial_report_content and omit structured_content"
                )
        else:
            if self.initial_report_content is not None:
                raise ValueError("non-initial-report messages must omit initial_report_content")
            if self.message_type in {
                MessageType.AGENT_ANSWER,
                MessageType.GOAL_SWITCH_CONFIRMATION,
                MessageType.STAGE_SUMMARY,
            } and self.structured_content is None:
                raise ValueError("structured agent messages must include structured_content")
        if self.role == MessageRole.USER:
            if self.structured_content is not None or self.initial_report_content is not None:
                raise ValueError("user messages must not include structured payloads")
        return self


class TeachingPlanStep(ContractModel):
    step_id: str
    title: str
    goal: LearningGoal
    target_scope: str
    reason: str
    expected_learning_gain: str
    status: TeachingPlanStepStatus
    priority: int
    depends_on: list[str] = Field(default_factory=list)
    source_topic_refs: list[TopicRef] = Field(default_factory=list)
    adaptation_note: str | None = None


class TeachingPlanState(ContractModel):
    plan_id: str
    generated_from_skeleton_id: str
    current_step_id: str | None = None
    steps: list[TeachingPlanStep] = Field(default_factory=list)
    update_notes: list[str] = Field(default_factory=list)
    updated_at: datetime


class StudentLearningTopicState(ContractModel):
    topic: LearningGoal
    coverage_level: StudentCoverageLevel
    confidence_of_estimate: ConfidenceLevel
    last_explained_at_message_id: str | None = None
    student_signal: str | None = None
    likely_gap: str | None = None
    recommended_intervention: str | None = None
    supporting_evidence: list[str] = Field(default_factory=list)


class StudentLearningState(ContractModel):
    state_id: str
    topics: list[StudentLearningTopicState] = Field(default_factory=list)
    update_notes: list[str] = Field(default_factory=list)
    updated_at: datetime


class TeacherWorkingLog(ContractModel):
    log_id: str
    current_teaching_objective: str
    why_now: str
    active_topic_refs: list[TopicRef] = Field(default_factory=list)
    current_plan_step_id: str | None = None
    planned_transition: str | None = None
    student_risk_notes: list[str] = Field(default_factory=list)
    recent_decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    updated_at: datetime


class TeachingDecisionSnapshot(ContractModel):
    decision_id: str
    scenario: PromptScenario
    user_message_summary: str | None = None
    selected_action: TeachingDecisionAction
    selected_plan_step_id: str | None = None
    selected_plan_step_title: str | None = None
    teaching_objective: str
    decision_reason: str
    student_state_notes: list[str] = Field(default_factory=list)
    planned_transition: str | None = None
    topic_refs: list[TopicRef] = Field(default_factory=list)
    created_at: datetime


class TeachingDebugEvent(ContractModel):
    debug_event_id: str
    event_type: TeachingDebugEventType
    occurred_at: datetime
    message_id: str | None = None
    plan_step_id: str | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class ConversationState(ContractModel):
    current_repo_id: str | None = None
    current_learning_goal: LearningGoal = LearningGoal.OVERVIEW
    current_stage: TeachingStage = TeachingStage.NOT_STARTED
    current_focus_module_id: str | None = None
    current_entry_candidate_id: str | None = None
    current_flow_id: str | None = None
    current_layer_view_id: str | None = None
    explained_items: list[ExplainedItemRef] = Field(default_factory=list)
    last_suggestions: list[Suggestion] = Field(default_factory=list)
    depth_level: DepthLevel = DepthLevel.DEFAULT
    messages: list[MessageRecord] = Field(default_factory=list)
    history_summary: str | None = None
    teaching_plan_state: TeachingPlanState | None = None
    student_learning_state: StudentLearningState | None = None
    teacher_working_log: TeacherWorkingLog | None = None
    current_teaching_decision: TeachingDecisionSnapshot | None = None
    teaching_debug_events: list[TeachingDebugEvent] = Field(default_factory=list)
    sub_status: ConversationSubStatus | None = None


class OutputContract(ContractModel):
    required_sections: list[MessageSection] = Field(default_factory=list)
    max_core_points: int = 4
    must_include_next_steps: bool = True
    must_mark_uncertainty: bool = True
    must_use_candidate_wording: bool = True


class LlmToolDefinition(ContractModel):
    tool_name: str
    source_module: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_contract: str | None = None
    safety_notes: list[str] = Field(default_factory=list)
    deterministic: bool = True


class LlmToolResult(ContractModel):
    result_id: str
    tool_name: str
    source_module: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reference_only: bool = True
    generated_at: datetime | None = None


class LlmToolContext(ContractModel):
    policy: str
    tools: list[LlmToolDefinition] = Field(default_factory=list)
    tool_results: list[LlmToolResult] = Field(default_factory=list)


class PromptBuildInput(ContractModel):
    scenario: PromptScenario
    user_message: str | None = None
    teaching_skeleton: TeachingSkeleton
    topic_slice: list[TopicRef] = Field(default_factory=list)
    tool_context: LlmToolContext | None = None
    conversation_state: ConversationState
    history_summary: str | None = None
    depth_level: DepthLevel
    output_contract: OutputContract


class StructuredAnswer(ContractModel):
    answer_id: str
    message_type: MessageType
    raw_text: str
    structured_content: StructuredMessageContent
    suggestions: list[Suggestion] = Field(default_factory=list)
    related_topic_refs: list[TopicRef] = Field(default_factory=list)
    used_evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)


class InitialReportAnswer(ContractModel):
    answer_id: str
    message_type: MessageType
    raw_text: str
    initial_report_content: InitialReportContent
    suggestions: list[Suggestion] = Field(default_factory=list)
    used_evidence_refs: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_message_type(self) -> InitialReportAnswer:
        if self.message_type != MessageType.INITIAL_REPORT:
            raise ValueError("initial report answers must use message_type=initial_report")
        return self


class DegradationFlag(ContractModel):
    degradation_id: str
    type: DegradationType
    reason: str
    user_notice: str
    started_at: datetime
    related_paths: list[str] = Field(default_factory=list)


class RuntimeEvent(ContractModel):
    event_id: str
    session_id: str
    event_type: RuntimeEventType
    occurred_at: datetime
    status_snapshot: SessionStatus | None = None
    sub_status_snapshot: ConversationSubStatus | None = None
    step_key: ProgressStepKey | None = None
    step_state: ProgressStepState | None = None
    message_id: str | None = None
    message_chunk: str | None = None
    structured_delta: dict[str, Any] | None = None
    user_notice: str | None = None
    error: UserFacingError | None = None
    degradation: DegradationFlag | None = None
    payload: dict[str, Any] | None = None


class SessionContext(ContractModel):
    session_id: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    repository: RepositoryContext | None = None
    file_tree: FileTreeSnapshot | None = None
    analysis: AnalysisBundle | None = None
    teaching_skeleton: TeachingSkeleton | None = None
    conversation: ConversationState
    last_error: UserFacingError | None = None
    progress_steps: list[ProgressStepStateItem] = Field(default_factory=list)
    active_degradations: list[DegradationFlag] = Field(default_factory=list)
    runtime_events: list[RuntimeEvent] = Field(default_factory=list)
    temp_resources: TempResourceSet | None = None

    @model_validator(mode="after")
    def validate_session_shape(self) -> SessionContext:
        if self.status == SessionStatus.IDLE:
            if any(item is not None for item in (self.repository, self.file_tree, self.analysis, self.teaching_skeleton)):
                raise ValueError("idle sessions must not retain repository analysis state")
            if self.progress_steps:
                raise ValueError("idle sessions must have empty progress_steps")
        if self.status == SessionStatus.CHATTING:
            if any(item is None for item in (self.repository, self.file_tree, self.analysis, self.teaching_skeleton)):
                raise ValueError("chatting sessions must include repository, file_tree, analysis, and teaching_skeleton")
        elif self.conversation.sub_status is not None:
            raise ValueError("conversation sub_status is only valid while session status is chatting")
        return self


class SessionStore(ContractModel):
    active_session: SessionContext | None = None
