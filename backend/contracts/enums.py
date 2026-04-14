from enum import StrEnum


class SessionStatus(StrEnum):
    IDLE = "idle"
    ACCESSING = "accessing"
    ACCESS_ERROR = "access_error"
    ANALYZING = "analyzing"
    ANALYSIS_ERROR = "analysis_error"
    CHATTING = "chatting"


class ConversationSubStatus(StrEnum):
    WAITING_USER = "waiting_user"
    AGENT_THINKING = "agent_thinking"
    AGENT_STREAMING = "agent_streaming"


class ClientView(StrEnum):
    INPUT = "input"
    ANALYSIS = "analysis"
    CHAT = "chat"


class RepoSourceType(StrEnum):
    LOCAL_PATH = "local_path"
    GITHUB_URL = "github_url"


class RepoSizeLevel(StrEnum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class FileNodeType(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"


class FileNodeStatus(StrEnum):
    NORMAL = "normal"
    IGNORED = "ignored"
    SENSITIVE_SKIPPED = "sensitive_skipped"
    UNREADABLE = "unreadable"
    OUT_OF_SCOPE = "out_of_scope"


class IgnoreRuleSource(StrEnum):
    BUILT_IN = "built_in"
    GITIGNORE = "gitignore"
    SECURITY_POLICY = "security_policy"


class ScanScopeType(StrEnum):
    FULL = "full"
    ENTRY_NEIGHBORHOOD = "entry_neighborhood"
    TOP_LEVEL_ONLY = "top_level_only"
    CONSERVATIVE_STRUCTURE_ONLY = "conservative_structure_only"


class CleanupStatus(StrEnum):
    NOT_NEEDED = "not_needed"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisMode(StrEnum):
    FULL_PYTHON = "full_python"
    DEGRADED_LARGE_REPO = "degraded_large_repo"
    DEGRADED_NON_PYTHON = "degraded_non_python"


class SkeletonMode(StrEnum):
    FULL = "full"
    DEGRADED_LARGE_REPO = "degraded_large_repo"
    DEGRADED_NON_PYTHON = "degraded_non_python"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class DerivedStatus(StrEnum):
    FORMED = "formed"
    HEURISTIC = "heuristic"
    UNKNOWN = "unknown"


class ProjectType(StrEnum):
    CLI = "cli"
    WEB_APP = "web_app"
    LIBRARY = "library"
    PACKAGE = "package"
    SCRIPT_COLLECTION = "script_collection"
    UNKNOWN = "unknown"


class EntryTargetType(StrEnum):
    FILE = "file"
    COMMAND = "command"
    CONFIG_SCRIPT = "config_script"
    FRAMEWORK_OBJECT = "framework_object"
    UNKNOWN = "unknown"


class ImportSourceType(StrEnum):
    INTERNAL = "internal"
    STDLIB = "stdlib"
    THIRD_PARTY = "third_party"
    UNKNOWN = "unknown"


class ModuleKind(StrEnum):
    DIRECTORY = "directory"
    PACKAGE = "package"
    FILE = "file"


class LayerType(StrEnum):
    ENTRY = "entry"
    ROUTE_OR_CONTROLLER = "route_or_controller"
    BUSINESS_LOGIC = "business_logic"
    DATA_ACCESS = "data_access"
    UTILITY_OR_CONFIG = "utility_or_config"
    UNKNOWN = "unknown"


class MainPathRole(StrEnum):
    MAIN_PATH = "main_path"
    SUPPORTING = "supporting"
    UNKNOWN = "unknown"


class FlowKind(StrEnum):
    NO_RELIABLE_FLOW = "no_reliable_flow"
    ENTRY_NEIGHBORHOOD = "entry_neighborhood"
    MODULE_LEVEL_PATH = "module_level_path"
    TEACHING_DATA_FLOW = "teaching_data_flow"


class ReadingTargetType(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    MODULE = "module"
    FLOW = "flow"
    UNKNOWN = "unknown"


class EvidenceType(StrEnum):
    FILE_PATH = "file_path"
    README_INSTRUCTION = "readme_instruction"
    CONFIG_ENTRY = "config_entry"
    DEPENDENCY_DECLARATION = "dependency_declaration"
    IMPORT_RELATION = "import_relation"
    SYMBOL = "symbol"
    DIRECTORY_STRUCTURE = "directory_structure"
    NAMING_CONVENTION = "naming_convention"


class UnknownTopic(StrEnum):
    PROJECT_TYPE = "project_type"
    ENTRY = "entry"
    DEPENDENCY = "dependency"
    MODULE_ROLE = "module_role"
    LAYER = "layer"
    FLOW = "flow"
    OUTPUT_TARGET = "output_target"
    SECURITY_SKIPPED = "security_skipped"
    OTHER = "other"


class WarningType(StrEnum):
    AST_PARSE_FAILED = "ast_parse_failed"
    FILE_UNREADABLE = "file_unreadable"
    LARGE_REPO_LIMITED = "large_repo_limited"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SENSITIVE_FILE_SKIPPED = "sensitive_file_skipped"


class LearningGoal(StrEnum):
    OVERVIEW = "overview"
    STRUCTURE = "structure"
    ENTRY = "entry"
    FLOW = "flow"
    MODULE = "module"
    DEPENDENCY = "dependency"
    LAYER = "layer"
    SUMMARY = "summary"


class TeachingStage(StrEnum):
    NOT_STARTED = "not_started"
    INITIAL_REPORT = "initial_report"
    STRUCTURE_OVERVIEW = "structure_overview"
    ENTRY_EXPLAINED = "entry_explained"
    FLOW_EXPLAINED = "flow_explained"
    LAYER_EXPLAINED = "layer_explained"
    DEPENDENCY_EXPLAINED = "dependency_explained"
    MODULE_DEEP_DIVE = "module_deep_dive"
    SUMMARY = "summary"


class DepthLevel(StrEnum):
    SHALLOW = "shallow"
    DEFAULT = "default"
    DEEP = "deep"


class TeachingPlanStepStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    CANCELLED = "cancelled"


class StudentCoverageLevel(StrEnum):
    UNSEEN = "unseen"
    INTRODUCED = "introduced"
    PARTIALLY_GRASPED = "partially_grasped"
    NEEDS_REINFORCEMENT = "needs_reinforcement"
    TEMPORARILY_STABLE = "temporarily_stable"


class TeachingDecisionAction(StrEnum):
    PROCEED_WITH_PLAN = "proceed_with_plan"
    ADAPT_TO_USER_GOAL = "adapt_to_user_goal"
    REINFORCE_STUDENT_GAP = "reinforce_student_gap"
    SUMMARIZE_PROGRESS = "summarize_progress"
    ANSWER_LOCAL_QUESTION = "answer_local_question"


class TeachingDebugEventType(StrEnum):
    TEACHING_STATE_INITIALIZED = "teaching_state_initialized"
    TEACHER_TURN_STARTED = "teacher_turn_started"
    TEACHING_PLAN_SELECTED = "teaching_plan_selected"
    TEACHING_DECISION_BUILT = "teaching_decision_built"
    TEACHING_PLAN_UPDATED = "teaching_plan_updated"
    STUDENT_STATE_UPDATED = "student_state_updated"
    WORKING_LOG_UPDATED = "working_log_updated"
    NEXT_TRANSITION_SELECTED = "next_transition_selected"


class MessageRole(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class MessageType(StrEnum):
    INITIAL_REPORT = "initial_report"
    USER_QUESTION = "user_question"
    AGENT_ANSWER = "agent_answer"
    GOAL_SWITCH_CONFIRMATION = "goal_switch_confirmation"
    STAGE_SUMMARY = "stage_summary"
    ERROR = "error"


class PromptScenario(StrEnum):
    INITIAL_REPORT = "initial_report"
    FOLLOW_UP = "follow_up"
    GOAL_SWITCH = "goal_switch"
    DEPTH_ADJUSTMENT = "depth_adjustment"
    STAGE_SUMMARY = "stage_summary"


class MessageSection(StrEnum):
    FOCUS = "focus"
    DIRECT_EXPLANATION = "direct_explanation"
    RELATION_TO_OVERALL = "relation_to_overall"
    EVIDENCE = "evidence"
    UNCERTAINTY = "uncertainty"
    NEXT_STEPS = "next_steps"


class TopicRefType(StrEnum):
    OVERVIEW = "overview"
    ENTRY_CANDIDATE = "entry_candidate"
    IMPORT_CLASSIFICATION = "import_classification"
    MODULE_SUMMARY = "module_summary"
    LAYER_ASSIGNMENT = "layer_assignment"
    FLOW_SUMMARY = "flow_summary"
    READING_STEP = "reading_step"
    UNKNOWN_ITEM = "unknown_item"
    EVIDENCE = "evidence"


class RuntimeEventType(StrEnum):
    STATUS_CHANGED = "status_changed"
    ANALYSIS_PROGRESS = "analysis_progress"
    DEGRADATION_NOTICE = "degradation_notice"
    ANSWER_STREAM_START = "answer_stream_start"
    ANSWER_STREAM_DELTA = "answer_stream_delta"
    ANSWER_STREAM_END = "answer_stream_end"
    MESSAGE_COMPLETED = "message_completed"
    ERROR = "error"


class ProgressStepKey(StrEnum):
    REPO_ACCESS = "repo_access"
    FILE_TREE_SCAN = "file_tree_scan"
    ENTRY_AND_MODULE_ANALYSIS = "entry_and_module_analysis"
    DEPENDENCY_ANALYSIS = "dependency_analysis"
    SKELETON_ASSEMBLY = "skeleton_assembly"
    INITIAL_REPORT_GENERATION = "initial_report_generation"


class ProgressStepState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class DegradationType(StrEnum):
    LARGE_REPO = "large_repo"
    NON_PYTHON_REPO = "non_python_repo"
    ENTRY_NOT_FOUND = "entry_not_found"
    FLOW_NOT_RELIABLE = "flow_not_reliable"
    LAYER_NOT_RELIABLE = "layer_not_reliable"
    ANALYSIS_TIMEOUT = "analysis_timeout"


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    LOCAL_PATH_NOT_FOUND = "local_path_not_found"
    LOCAL_PATH_NOT_DIRECTORY = "local_path_not_directory"
    LOCAL_PATH_NOT_READABLE = "local_path_not_readable"
    GITHUB_URL_INVALID = "github_url_invalid"
    GITHUB_REPO_INACCESSIBLE = "github_repo_inaccessible"
    GIT_CLONE_TIMEOUT = "git_clone_timeout"
    GIT_CLONE_FAILED = "git_clone_failed"
    PATH_ESCAPE_DETECTED = "path_escape_detected"
    ANALYSIS_TIMEOUT = "analysis_timeout"
    ANALYSIS_FAILED = "analysis_failed"
    LLM_API_FAILED = "llm_api_failed"
    LLM_API_TIMEOUT = "llm_api_timeout"
    INVALID_STATE = "invalid_state"
