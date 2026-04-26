# RepoParsePipeline：编排 resolve → clone → scan → overview → slice 五阶段，每步可选 sink 推 ParseLogLine / AgentStatus / RepoConnectedData，最终返回 RepoParseResult。
from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Awaitable, Callable, Literal, Protocol, TypeVar
from uuid import uuid4

from ..contracts import (
    AgentMetrics,
    AgentPetState,
    AgentPhase,
    AgentStatus,
    ChatMode,
    GithubRepositoryRef,
    LogLevel,
    ParseLogLine,
    ParseStage,
    RepoConnectedData,
    RepoSource,
    RepositoryStatus,
    RepositorySummary,
    TeachingCodeSnippet,
)
from ..contracts import ErrorCode
from .errors import RepoModuleError, repo_api_error
from .git_cloner import CloneResult, GitCloner
from .github_resolver import GithubResolver
from .overview_builder import OverviewBuilder, RepoOverview
from .teaching_slice_picker import TeachingSlicePicker
from .tree_scanner import TreeScanResult, TreeScanner


T = TypeVar("T")
MaybeAwaitable = T | Awaitable[T]
PetMood = Literal["idle", "think", "act", "scan", "teach", "research", "error"]
StatusSink = Callable[[AgentStatus], MaybeAwaitable[None]]
LogSink = Callable[[ParseLogLine], MaybeAwaitable[None]]
ConnectedSink = Callable[[RepoConnectedData], MaybeAwaitable[None]]


class GithubResolverProtocol(Protocol):
    def resolve_ref(
        self,
        input_value: str,
        *,
        branch: str | None = None,
        verify: bool = True,
    ) -> GithubRepositoryRef:
        ...


class GitClonerProtocol(Protocol):
    def clone(
        self,
        ref: GithubRepositoryRef,
        *,
        branch: str | None = None,
        destination_root: Path | None = None,
    ) -> CloneResult:
        ...


@dataclass(frozen=True)
class RepoParseResult:
    session_id: str
    repository: RepositorySummary
    repo_root: Path
    overview: RepoOverview
    scan: TreeScanResult
    current_code: TeachingCodeSnippet | None
    initial_message: str
    parse_log: tuple[ParseLogLine, ...]


class RepoParsePipeline:
    def __init__(
        self,
        *,
        resolver: GithubResolverProtocol | None = None,
        cloner: GitClonerProtocol | None = None,
        scanner: TreeScanner | None = None,
        overview_builder: OverviewBuilder | None = None,
        slice_picker: TeachingSlicePicker | None = None,
        repo_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._resolver = resolver or GithubResolver()
        self._cloner = cloner or GitCloner()
        self._scanner = scanner or TreeScanner()
        self._overview_builder = overview_builder or OverviewBuilder()
        self._slice_picker = slice_picker or TeachingSlicePicker()
        self._repo_id_factory = repo_id_factory or _new_repo_id

    async def run(
        self,
        *,
        session_id: str,
        input_value: str,
        branch: str | None = None,
        mode: ChatMode = ChatMode.CHAT,
        clone_parent: Path | None = None,
        status_sink: StatusSink | None = None,
        log_sink: LogSink | None = None,
        connected_sink: ConnectedSink | None = None,
    ) -> RepoParseResult:
        del mode
        parse_log: list[ParseLogLine] = []
        try:
            await self._stage(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                parse_stage=ParseStage.VALIDATING_URL,
                phase=AgentPhase.RESOLVING_GITHUB,
                text="正在校验 GitHub 仓库地址",
                progress=0.05,
            )
            ref = self._resolver.resolve_ref(input_value, branch=branch, verify=True)

            await self._stage(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                parse_stage=ParseStage.RESOLVING_METADATA,
                phase=AgentPhase.RESOLVING_GITHUB,
                text=f"已识别仓库 {ref.owner}/{ref.repo}",
                progress=0.18,
            )
            clone = self._cloner.clone(ref, branch=branch, destination_root=clone_parent)
            ref = ref.model_copy(
                update={
                    "resolved_branch": clone.branch or ref.resolved_branch,
                    "commit_sha": clone.commit_sha,
                }
            )

            await self._stage(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                parse_stage=ParseStage.CLONING,
                phase=AgentPhase.CLONING_REPO,
                text="仓库已 clone 到本地只读工作区",
                progress=0.35,
            )
            scan = self._scanner.scan(clone.repo_root)

            await self._stage(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                parse_stage=ParseStage.SCANNING_TREE,
                phase=AgentPhase.SCANNING_TREE,
                text=f"文件树扫描完成，纳入 {scan.file_count} 个安全文件",
                progress=0.6,
            )
            overview = self._overview_builder.build(scan)

            await self._stage(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                parse_stage=ParseStage.BUILDING_OVERVIEW,
                phase=AgentPhase.BUILDING_OVERVIEW,
                text="仓库概览已生成",
                progress=0.78,
            )
            current_code = self._slice_picker.pick(overview, scan)

            await self._stage(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                parse_stage=ParseStage.SELECTING_TEACHING_SLICE,
                phase=AgentPhase.SELECTING_TEACHING_SLICE,
                text="已选择首个教学片段" if current_code else "未找到可安全展示的首个教学片段",
                progress=0.9,
            )

            repository = RepositorySummary(
                repo_id=self._repo_id_factory(),
                display_name=f"{ref.owner}/{ref.repo}",
                source=RepoSource.GITHUB_URL,
                github=ref,
                primary_language=scan.primary_language,
                file_count=scan.file_count,
                status=RepositoryStatus.READY,
            )
            initial_message = _initial_message(repository, current_code)
            connected = RepoConnectedData(
                repository=repository,
                initial_message=initial_message,
                current_code=current_code,
            )

            await self._stage(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                parse_stage=ParseStage.COMPLETED,
                phase=AgentPhase.IDLE,
                text="仓库接入完成",
                progress=1.0,
                state=AgentPetState.IDLE,
                pet_mood="idle",
            )
            await _call_sink(connected_sink, connected)

            return RepoParseResult(
                session_id=session_id,
                repository=repository,
                repo_root=clone.repo_root,
                overview=overview,
                scan=scan,
                current_code=current_code,
                initial_message=initial_message,
                parse_log=tuple(parse_log),
            )
        except RepoModuleError as exc:
            await self._emit_failure(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                text=exc.error.message,
                internal_detail=exc.error.internal_detail,
            )
            raise
        except Exception as exc:
            error = RepoModuleError(
                repo_api_error(
                    error_code=ErrorCode.REPO_SCAN_FAILED,
                    message="仓库接入失败，请稍后重试",
                    retryable=True,
                    internal_detail=str(exc),
                )
            )
            await self._emit_failure(
                session_id=session_id,
                status_sink=status_sink,
                log_sink=log_sink,
                parse_log=parse_log,
                text=error.error.message,
                internal_detail=error.error.internal_detail,
            )
            raise error from exc

    async def _stage(
        self,
        *,
        session_id: str,
        status_sink: StatusSink | None,
        log_sink: LogSink | None,
        parse_log: list[ParseLogLine],
        parse_stage: ParseStage,
        phase: AgentPhase,
        text: str,
        progress: float,
        state: AgentPetState = AgentPetState.SCANNING,
        pet_mood: PetMood = "scan",
    ) -> None:
        status = _status(
            session_id=session_id,
            state=state,
            phase=phase,
            label=text,
            pet_mood=pet_mood,
            pet_message=text,
        )
        await _call_sink(status_sink, status)
        log = ParseLogLine(
            line_id=f"log_{uuid4().hex[:12]}",
            stage=parse_stage,
            level=LogLevel.INFO,
            text=text,
            progress=progress,
        )
        parse_log.append(log)
        await _call_sink(log_sink, log)

    async def _emit_failure(
        self,
        *,
        session_id: str,
        status_sink: StatusSink | None,
        log_sink: LogSink | None,
        parse_log: list[ParseLogLine],
        text: str,
        internal_detail: str | None,
    ) -> None:
        status = _status(
            session_id=session_id,
            state=AgentPetState.ERROR,
            phase=AgentPhase.FAILED,
            label="仓库接入失败",
            pet_mood="error",
            pet_message=text,
        )
        await _call_sink(status_sink, status)
        log = ParseLogLine(
            line_id=f"log_{uuid4().hex[:12]}",
            stage=ParseStage.COMPLETED,
            level=LogLevel.ERROR,
            text=text,
            path=internal_detail,
            progress=None,
        )
        parse_log.append(log)
        await _call_sink(log_sink, log)


async def parse_repository(
    *,
    session_id: str,
    input_value: str,
    branch: str | None = None,
    clone_parent: Path | None = None,
    status_sink: StatusSink | None = None,
    log_sink: LogSink | None = None,
    connected_sink: ConnectedSink | None = None,
) -> RepoParseResult:
    return await RepoParsePipeline().run(
        session_id=session_id,
        input_value=input_value,
        branch=branch,
        clone_parent=clone_parent,
        status_sink=status_sink,
        log_sink=log_sink,
        connected_sink=connected_sink,
    )


async def _call_sink(
    sink: Callable[[T], MaybeAwaitable[None]] | None,
    value: T,
) -> None:
    if sink is None:
        return
    result = sink(value)
    if inspect.isawaitable(result):
        await result


def _status(
    *,
    session_id: str,
    state: AgentPetState,
    phase: AgentPhase,
    label: str,
    pet_mood: PetMood,
    pet_message: str,
) -> AgentStatus:
    return AgentStatus(
        session_id=session_id,
        state=state,
        phase=phase,
        label=label,
        pet_mood=pet_mood,
        pet_message=pet_message,
        current_action=None,
        current_target=None,
        metrics=AgentMetrics(),
        updated_at=datetime.now(UTC),
    )


def _initial_message(
    repository: RepositorySummary,
    current_code: TeachingCodeSnippet | None,
) -> str:
    if current_code is not None and hasattr(current_code, "path"):
        return f"仓库 {repository.display_name} 已连接。我们可以先从 {current_code.path} 开始。"
    return f"仓库 {repository.display_name} 已连接，但没有找到适合直接展示的安全代码片段。"


def _new_repo_id() -> str:
    return f"repo_{uuid4().hex[:12]}"
