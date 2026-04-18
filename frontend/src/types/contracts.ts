export type SessionStatus =
  | 'idle'
  | 'accessing'
  | 'access_error'
  | 'analyzing'
  | 'analysis_error'
  | 'chatting';

export type ConversationSubStatus = 'waiting_user' | 'agent_thinking' | 'agent_streaming';
export type ClientView = 'input' | 'analysis' | 'chat';
export type RepoSourceType = 'local_path' | 'github_url';
export type RepoSizeLevel = 'small' | 'medium' | 'large';
export type ConfidenceLevel = 'high' | 'medium' | 'low' | 'unknown';
export type DerivedStatus = 'formed' | 'heuristic' | 'unknown';
export type ProjectType = 'cli' | 'web_app' | 'library' | 'package' | 'script_collection' | 'unknown';
export type EntryTargetType = 'file' | 'command' | 'config_script' | 'framework_object' | 'unknown';
export type MainPathRole = 'main_path' | 'supporting' | 'unknown';
export type ReadingTargetType = 'file' | 'directory' | 'module' | 'flow' | 'unknown';
export type UnknownTopic =
  | 'project_type'
  | 'entry'
  | 'dependency'
  | 'module_role'
  | 'layer'
  | 'flow'
  | 'output_target'
  | 'security_skipped'
  | 'other';
export type LearningGoal =
  | 'overview'
  | 'structure'
  | 'entry'
  | 'flow'
  | 'module'
  | 'dependency'
  | 'layer'
  | 'summary';
export type MessageRole = 'user' | 'agent' | 'system';
export type MessageType =
  | 'initial_report'
  | 'user_question'
  | 'agent_answer'
  | 'goal_switch_confirmation'
  | 'stage_summary'
  | 'error';
export type RuntimeEventType =
  | 'status_changed'
  | 'analysis_progress'
  | 'degradation_notice'
  | 'agent_activity'
  | 'answer_stream_start'
  | 'answer_stream_delta'
  | 'answer_stream_end'
  | 'message_completed'
  | 'error';
export type AgentActivityPhase =
  | 'thinking'
  | 'planning_tool_call'
  | 'tool_running'
  | 'tool_succeeded'
  | 'tool_failed'
  | 'degraded_continue'
  | 'waiting_llm_after_tool'
  | 'slow_warning';
export type ProgressStepKey =
  | 'repo_access'
  | 'file_tree_scan'
  | 'entry_and_module_analysis'
  | 'dependency_analysis'
  | 'skeleton_assembly'
  | 'initial_report_generation';
export type ProgressStepState = 'pending' | 'running' | 'done' | 'error';
export type DegradationType =
  | 'large_repo'
  | 'non_python_repo'
  | 'entry_not_found'
  | 'flow_not_reliable'
  | 'layer_not_reliable'
  | 'analysis_timeout';
export type ErrorCode =
  | 'invalid_request'
  | 'local_path_not_found'
  | 'local_path_not_directory'
  | 'local_path_not_readable'
  | 'github_url_invalid'
  | 'github_repo_inaccessible'
  | 'git_clone_timeout'
  | 'git_clone_failed'
  | 'path_escape_detected'
  | 'analysis_timeout'
  | 'analysis_failed'
  | 'llm_api_failed'
  | 'llm_api_timeout'
  | 'invalid_state';

export type RepositorySummaryDto = {
  display_name: string;
  source_type: RepoSourceType;
  input_value: string;
  primary_language: string | null;
  repo_size_level: RepoSizeLevel | null;
  source_code_file_count: number | null;
};

export type ProgressStepStateItem = {
  step_key: ProgressStepKey;
  step_state: ProgressStepState;
};

export type SuggestionDto = {
  suggestion_id: string;
  text: string;
  target_goal: LearningGoal | null;
};

export type EvidenceLineDto = {
  text: string;
  evidence_refs: string[];
  confidence: ConfidenceLevel | null;
};

export type EntryCandidateDto = {
  entry_id: string;
  target_type: EntryTargetType;
  target_value: string;
  reason: string;
  confidence: ConfidenceLevel;
  rank: number;
  evidence_refs: string[];
};

export type ReadingStepDto = {
  step_no: number;
  target: string;
  target_type: ReadingTargetType;
  reason: string;
  learning_gain: string;
  skippable: string | null;
  next_step_hint: string | null;
  evidence_refs: string[];
};

export type UnknownItemDto = {
  unknown_id: string;
  topic: UnknownTopic;
  description: string;
  related_paths: string[];
  reason: string | null;
};

export type InitialReportContentDto = {
  overview: {
    summary: string;
    confidence: ConfidenceLevel;
    evidence_refs: string[];
  };
  focus_points: {
    title: string;
    reason: string;
    topic: LearningGoal;
  }[];
  repo_mapping: {
    concept: LearningGoal;
    explanation: string;
    mapped_paths: string[];
    confidence: ConfidenceLevel;
    evidence_refs: string[];
  }[];
  language_and_type: {
    primary_language: string;
    project_types: {
      type: ProjectType;
      reason: string;
      confidence: ConfidenceLevel;
      evidence_refs: string[];
    }[];
    degradation_notice: string | null;
  };
  key_directories: {
    path: string;
    role: string;
    main_path_role: MainPathRole;
    confidence: ConfidenceLevel;
    evidence_refs: string[];
  }[];
  entry_section: {
    status: DerivedStatus;
    entries: EntryCandidateDto[];
    fallback_advice: string | null;
  };
  recommended_first_step: {
    target: string;
    reason: string;
    learning_gain: string;
    evidence_refs: string[];
  };
  reading_path_preview: ReadingStepDto[];
  unknown_section: UnknownItemDto[];
  suggested_next_questions: SuggestionDto[];
};

export type StructuredMessageContentDto = {
  focus: string;
  direct_explanation: string;
  relation_to_overall: string;
  evidence_lines: EvidenceLineDto[];
  uncertainties: string[];
  next_steps: SuggestionDto[];
};

export type UserFacingErrorDto = {
  error_code: ErrorCode;
  message: string;
  retryable: boolean;
  stage: SessionStatus;
  input_preserved: boolean;
  internal_detail?: string | null;
};

export type MessageErrorStateDto = {
  error: UserFacingErrorDto;
  failed_during_stream: boolean;
  partial_text_available: boolean;
};

export type MessageDto = {
  message_id: string;
  role: MessageRole;
  message_type: MessageType;
  created_at: string;
  raw_text: string;
  structured_content: StructuredMessageContentDto | null;
  initial_report_content: InitialReportContentDto | null;
  related_goal: LearningGoal | null;
  suggestions: SuggestionDto[];
  streaming_complete: boolean;
  error_state: MessageErrorStateDto | null;
};

export type DegradationFlagDto = {
  degradation_id: string;
  type: DegradationType;
  reason: string;
  user_notice: string;
  related_paths: string[];
};

export type AgentActivityDto = {
  activity_id: string;
  phase: AgentActivityPhase;
  summary: string;
  tool_name?: string | null;
  tool_arguments: Record<string, unknown>;
  round_index?: number | null;
  elapsed_ms?: number | null;
  soft_timed_out: boolean;
  failed: boolean;
  retryable: boolean;
};

export type SessionSnapshotDto = {
  session_id: string | null;
  status: SessionStatus;
  sub_status: ConversationSubStatus | null;
  view: ClientView;
  repository: RepositorySummaryDto | null;
  progress_steps: ProgressStepStateItem[];
  degradation_notices: DegradationFlagDto[];
  messages: MessageDto[];
  active_agent_activity: AgentActivityDto | null;
  active_error: UserFacingErrorDto | null;
};

export type ApiEnvelope<T> =
  | {
      ok: true;
      session_id: string | null;
      data: T;
    }
  | {
      ok: false;
      session_id: string | null;
      error: UserFacingErrorDto;
    };

export type ValidateRepoData = {
  input_kind: 'local_path' | 'github_url' | 'unknown';
  is_valid: boolean;
  normalized_input: string | null;
  message: string | null;
};

export type SubmitRepoData = {
  accepted: true;
  status: SessionStatus;
  sub_status: ConversationSubStatus | null;
  view: ClientView;
  repository: RepositorySummaryDto;
  analysis_stream_url: string;
};

export type SendMessageData = {
  accepted: true;
  status: 'chatting';
  sub_status: 'agent_thinking';
  user_message_id: string;
  chat_stream_url: string;
};

export type ClearSessionData = {
  status: 'idle';
  sub_status: null;
  view: 'input';
  cleanup_completed: boolean;
};

export type ValidateRepoResponse = ApiEnvelope<ValidateRepoData>;
export type SubmitRepoResponse = ApiEnvelope<SubmitRepoData>;
export type GetSessionResponse = ApiEnvelope<SessionSnapshotDto>;
export type SendMessageResponse = ApiEnvelope<SendMessageData>;
export type ClearSessionResponse = ApiEnvelope<ClearSessionData>;

export type SseEventDto = {
  event_id: string;
  event_type: RuntimeEventType;
  session_id: string;
  occurred_at: string;
};

export type StatusChangedEvent = SseEventDto & {
  event_type: 'status_changed';
  status: SessionStatus;
  sub_status: ConversationSubStatus | null;
  view: ClientView;
};

export type AnalysisProgressEvent = SseEventDto & {
  event_type: 'analysis_progress';
  step_key: ProgressStepKey;
  step_state: ProgressStepState;
  user_notice: string;
  progress_steps: ProgressStepStateItem[];
};

export type DegradationNoticeEvent = SseEventDto & {
  event_type: 'degradation_notice';
  degradation: DegradationFlagDto;
};

export type AgentActivityEvent = SseEventDto & {
  event_type: 'agent_activity';
  activity: AgentActivityDto;
};

export type AnswerStreamStartEvent = SseEventDto & {
  event_type: 'answer_stream_start';
  message_id: string;
  message_type: MessageType;
};

export type AnswerStreamDeltaEvent = SseEventDto & {
  event_type: 'answer_stream_delta';
  message_id: string;
  delta_text: string;
  structured_delta: Record<string, unknown> | null;
};

export type AnswerStreamEndEvent = SseEventDto & {
  event_type: 'answer_stream_end';
  message_id: string;
};

export type MessageCompletedEvent = SseEventDto & {
  event_type: 'message_completed';
  message: MessageDto;
  status: SessionStatus;
  sub_status: ConversationSubStatus | null;
  view: ClientView;
};

export type ErrorEvent = SseEventDto & {
  event_type: 'error';
  error: UserFacingErrorDto;
  status: SessionStatus;
  sub_status: ConversationSubStatus | null;
  view: ClientView;
};

export type AnalysisSseEvent =
  | StatusChangedEvent
  | AnalysisProgressEvent
  | DegradationNoticeEvent
  | AgentActivityEvent
  | AnswerStreamStartEvent
  | AnswerStreamDeltaEvent
  | AnswerStreamEndEvent
  | MessageCompletedEvent
  | ErrorEvent;

export type ChatSseEvent =
  | StatusChangedEvent
  | AgentActivityEvent
  | AnswerStreamStartEvent
  | AnswerStreamDeltaEvent
  | AnswerStreamEndEvent
  | MessageCompletedEvent
  | ErrorEvent;

export type ClientSessionStore = {
  sessionId: string | null;
  currentView: ClientView;
  status: SessionStatus;
  subStatus: ConversationSubStatus | null;
  repoDisplayName: string | null;
  progressSteps: ProgressStepStateItem[];
  degradationNotices: DegradationFlagDto[];
  messages: MessageDto[];
  activeAgentActivity: AgentActivityDto | null;
  activeError: UserFacingErrorDto | null;
};

export type CloseFn = () => void;
