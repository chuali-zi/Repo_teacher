from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path, PurePosixPath

from backend.contracts.domain import (
    ConfidenceLevel,
    DeepResearchRunState,
    EntryCandidate,
    EntryRole,
    EntrySection,
    EntryTargetType,
    InitialReportAnswer,
    InitialReportContent,
    KeyDirectoryItem,
    LanguageTypeSection,
    OverviewSection,
    ReadingStep,
    RecommendedStep,
    ResearchNote,
    ResearchPacket,
    RepositoryContext,
    SynthesisNote,
    Suggestion,
    UnknownItem,
)
from backend.contracts.enums import DerivedStatus, LearningGoal, MainPathRole, MessageType, ReadingTargetType, UnknownTopic
from backend.deep_research.source_selection import select_relevant_source_files
from backend.m5_session.common import new_id, utc_now
from backend.security.safety import resolve_repo_relative_path

ENTRY_FILENAMES = ("main.py", "app.py", "__main__.py", "manage.py")


def build_research_run_state(
    repository: RepositoryContext,
    file_tree,
) -> DeepResearchRunState:
    relevant_files = select_relevant_source_files(file_tree)
    total_files = sum(1 for item in relevant_files if item.selected)
    skipped_files = sum(1 for item in relevant_files if not item.selected)
    return DeepResearchRunState(
        state_id=new_id("dr"),
        phase="research_planning",
        total_files=total_files,
        completed_files=0,
        skipped_files=skipped_files,
        coverage_ratio=0.0 if total_files == 0 else 0.0,
        relevant_files=relevant_files,
        generated_at=utc_now(),
    )


def build_research_packets(
    repository: RepositoryContext,
    run_state: DeepResearchRunState,
) -> list[ResearchPacket]:
    packets: list[ResearchPacket] = []
    for item in run_state.relevant_files:
        if not item.selected:
            continue
        packets.append(_build_packet(repository, item))
    return packets


def build_group_notes(packets: list[ResearchPacket]) -> list[ResearchNote]:
    grouped: dict[str, list[ResearchPacket]] = defaultdict(list)
    for packet in packets:
        grouped[packet.group_key].append(packet)

    notes: list[ResearchNote] = []
    for group_key, group_packets in sorted(grouped.items()):
        covered_files = [packet.relative_path for packet in group_packets]
        key_symbols = _dedupe_text(
            symbol
            for packet in group_packets
            for symbol in packet.symbol_names
        )[:8]
        imports = _dedupe_text(
            import_name
            for packet in group_packets
            for import_name in packet.import_names
        )[:8]
        candidate_flows = _candidate_flows_for_packets(group_packets)
        next_hops = _dedupe_text(
            import_name.split(".")[0]
            for import_name in imports
            if import_name and not import_name.startswith("typing")
        )[:5]
        notes.append(
            ResearchNote(
                note_id=new_id("note"),
                subject_key=group_key,
                title=f"{group_key} module group",
                covered_files=covered_files,
                responsibility_summary=_group_summary(group_key, group_packets),
                key_symbols=key_symbols,
                import_relations=imports,
                candidate_flows=candidate_flows,
                evidence_refs=covered_files[:8],
                unknowns=[] if key_symbols or imports else ["Limited symbol evidence in this group."],
                next_hops=next_hops,
                confidence=(
                    ConfidenceLevel.HIGH
                    if any(packet.symbol_names for packet in group_packets)
                    else ConfidenceLevel.MEDIUM
                ),
            )
        )
    return notes


def build_synthesis_notes(
    repository: RepositoryContext,
    file_tree,
    run_state: DeepResearchRunState,
    group_notes: list[ResearchNote],
    packets: list[ResearchPacket],
) -> list[SynthesisNote]:
    selected_files = [item.relative_path for item in run_state.relevant_files if item.selected]
    skipped_files = [item for item in run_state.relevant_files if not item.selected]
    entry_paths = [path for path in selected_files if PurePosixPath(path).name in ENTRY_FILENAMES]
    imports = _dedupe_text(
        import_name
        for packet in packets
        for import_name in packet.import_names
    )
    top_symbols = _dedupe_text(
        symbol
        for packet in packets
        for symbol in packet.symbol_names
    )[:10]
    group_titles = [note.title for note in group_notes]
    notes = [
        SynthesisNote(
            section_key="repository_verdict",
            title="Repository Verdict",
            summary=_repository_verdict(repository, file_tree, selected_files, group_notes),
            bullet_points=[
                f"Primary language: {file_tree.primary_language}.",
                f"Relevant files selected for the first deep pass: {len(selected_files)}.",
                f"Module groups covered: {', '.join(group_titles) if group_titles else '(root only)'}",
            ],
            covered_files=selected_files[:8],
            evidence_refs=selected_files[:8],
            confidence=ConfidenceLevel.MEDIUM,
        ),
        SynthesisNote(
            section_key="reading_framework",
            title="Reading Framework",
            summary="Start from the repo-level document or config, then verify the likely runtime entry files, and only after that drill into grouped source modules.",
            bullet_points=_reading_framework_points(selected_files),
            covered_files=selected_files[:6],
            evidence_refs=selected_files[:6],
            confidence=ConfidenceLevel.HIGH,
        ),
        SynthesisNote(
            section_key="module_map",
            title="Directory and Module Map",
            summary="The source tree clusters into a small set of module groups that can be read in isolation before you stitch them into a full execution story.",
            bullet_points=[
                f"{note.title}: {note.responsibility_summary}" for note in group_notes[:6]
            ] or ["The repo is shallow, so most logic sits at the root level."],
            covered_files=[path for note in group_notes for path in note.covered_files][:10],
            evidence_refs=[path for note in group_notes for path in note.covered_files][:10],
            confidence=ConfidenceLevel.MEDIUM,
        ),
        SynthesisNote(
            section_key="entry_and_startup",
            title="Entry and Startup Path",
            summary=_entry_summary(entry_paths),
            bullet_points=[
                f"Entry candidate: {path}" for path in entry_paths
            ] or ["No conventional Python entry filename was selected; start from README or root config."],
            covered_files=entry_paths[:5],
            evidence_refs=entry_paths[:5],
            unknowns=[] if entry_paths else ["The startup path remains heuristic."],
            confidence=ConfidenceLevel.MEDIUM if entry_paths else ConfidenceLevel.LOW,
        ),
        SynthesisNote(
            section_key="core_flows",
            title="Core Flows",
            summary="The likely flow candidates come from imports and conventional entry filenames rather than runtime execution traces, so treat them as source-grounded hypotheses.",
            bullet_points=_candidate_flows_for_packets(packets)[:8] or ["No reliable flow candidate was formed from the current sources."],
            covered_files=selected_files[:8],
            evidence_refs=selected_files[:8],
            confidence=ConfidenceLevel.LOW if not imports else ConfidenceLevel.MEDIUM,
        ),
        SynthesisNote(
            section_key="key_abstractions",
            title="Key Abstractions and State",
            summary="Top-level functions, classes, and module names show the abstractions worth learning before chasing implementation details.",
            bullet_points=[f"Key symbol: {symbol}" for symbol in top_symbols] or ["No top-level Python symbol stood out in the selected excerpts."],
            covered_files=selected_files[:8],
            evidence_refs=selected_files[:8],
            confidence=ConfidenceLevel.MEDIUM,
        ),
        SynthesisNote(
            section_key="dependencies_and_config",
            title="Dependencies and Config",
            summary="Imports and root config files suggest the external surfaces and runtime assumptions you should verify next.",
            bullet_points=[f"Observed import: {name}" for name in imports[:8]] + [
                f"Config/doc file: {path}" for path in selected_files if _is_config_or_doc(path)
            ][:4],
            covered_files=[path for path in selected_files if _is_config_or_doc(path)][:8],
            evidence_refs=[path for path in selected_files if _is_config_or_doc(path)][:8],
            confidence=ConfidenceLevel.MEDIUM,
        ),
        SynthesisNote(
            section_key="file_coverage_appendix",
            title="File Coverage Appendix",
            summary="This appendix records which files were included in the deep first pass and which ones were intentionally skipped.",
            bullet_points=[
                f"Selected: {item.relative_path} ({item.source_kind})" for item in run_state.relevant_files if item.selected
            ] + [
                f"Skipped: {item.relative_path} ({item.skip_reason})" for item in skipped_files
            ],
            covered_files=selected_files,
            evidence_refs=selected_files[:10],
            confidence=ConfidenceLevel.HIGH,
        ),
        SynthesisNote(
            section_key="open_questions",
            title="Open Questions",
            summary="Anything not verified directly from the selected source set stays open and should be treated as a follow-up investigation target.",
            bullet_points=_open_questions(entry_paths, imports),
            covered_files=[],
            evidence_refs=[],
            unknowns=_open_questions(entry_paths, imports),
            confidence=ConfidenceLevel.LOW,
        ),
    ]
    return notes


def render_final_report(
    repository: RepositoryContext,
    file_tree,
    run_state: DeepResearchRunState,
    synthesis_notes: list[SynthesisNote],
    group_notes: list[ResearchNote],
) -> str:
    lines = [
        f"# Deep Research Report: {repository.display_name}",
        "",
        "This report is built from repository files only. Any runtime behavior claim is presented as a source-grounded hypothesis unless it was directly visible in the files.",
        "",
    ]
    for note in synthesis_notes:
        lines.append(f"## {note.title}")
        lines.append("")
        lines.append(f"Confidence: {note.confidence}")
        lines.append("")
        lines.append(note.summary)
        lines.append("")
        if note.bullet_points:
            for bullet in note.bullet_points:
                lines.append(f"- {bullet}")
            lines.append("")
        if note.covered_files:
            lines.append("Evidence files:")
            for path in note.covered_files[:12]:
                lines.append(f"- `{path}`")
            lines.append("")

    if group_notes:
        lines.append("## Group Notes")
        lines.append("")
        for note in group_notes:
            lines.append(f"### {note.title}")
            lines.append("")
            lines.append(note.responsibility_summary)
            lines.append("")
            if note.key_symbols:
                lines.append(f"- Key symbols: {', '.join(note.key_symbols)}")
            if note.import_relations:
                lines.append(f"- Imports: {', '.join(note.import_relations[:8])}")
            if note.next_hops:
                lines.append(f"- Next hops: {', '.join(note.next_hops)}")
            if note.covered_files:
                lines.append(f"- Covered files: {', '.join(note.covered_files)}")
            lines.append("")

    lines.append("## Research Coverage")
    lines.append("")
    lines.append(
        f"Completed files: {run_state.completed_files}/{run_state.total_files} "
        f"({run_state.coverage_ratio:.0%})."
    )
    if run_state.skipped_files:
        lines.append(f"Skipped files tracked in the first pass: {run_state.skipped_files}.")
    lines.append("")
    return "\n".join(lines).strip()


def build_initial_report_answer_from_research(
    repository: RepositoryContext,
    file_tree,
    run_state: DeepResearchRunState,
    group_notes: list[ResearchNote],
    synthesis_notes: list[SynthesisNote],
) -> InitialReportAnswer:
    suggestions = [
        Suggestion(
            suggestion_id=new_id("sug"),
            text="Walk me through the startup path next.",
            target_goal=LearningGoal.ENTRY,
        ),
        Suggestion(
            suggestion_id=new_id("sug"),
            text="Open the main module group in detail.",
            target_goal=LearningGoal.MODULE,
        ),
        Suggestion(
            suggestion_id=new_id("sug"),
            text="Summarize the likely control flow from entry to implementation.",
            target_goal=LearningGoal.FLOW,
        ),
    ]
    initial_report_content = InitialReportContent(
        overview=OverviewSection(
            summary=_repository_verdict(repository, file_tree, [item.relative_path for item in run_state.relevant_files if item.selected], group_notes),
            confidence=ConfidenceLevel.MEDIUM,
            evidence_refs=[item.relative_path for item in run_state.relevant_files if item.selected][:5],
        ),
        focus_points=[
            {
                "focus_id": new_id("focus"),
                "topic": LearningGoal.STRUCTURE,
                "title": "Map the repo before chasing details",
                "reason": "The deep pass covers grouped source files, config, and docs.",
                "related_refs": [],
            },
            {
                "focus_id": new_id("focus"),
                "topic": LearningGoal.ENTRY,
                "title": "Verify the startup path",
                "reason": "Conventional entry files were identified heuristically and need confirmation.",
                "related_refs": [],
            },
            {
                "focus_id": new_id("focus"),
                "topic": LearningGoal.MODULE,
                "title": "Read grouped modules instead of isolated files",
                "reason": "The report clusters files by module group to keep the reading path coherent.",
                "related_refs": [],
            },
        ],
        repo_mapping=[
            {
                "concept": LearningGoal.STRUCTURE,
                "mapped_paths": [note.subject_key for note in group_notes[:4] if note.subject_key != "(root)"],
                "mapped_module_ids": [],
                "explanation": "Module groups were built from the selected source files.",
                "confidence": ConfidenceLevel.MEDIUM,
                "evidence_refs": [path for note in group_notes for path in note.covered_files][:6],
            },
            {
                "concept": LearningGoal.ENTRY,
                "mapped_paths": _entry_paths(run_state),
                "mapped_module_ids": [],
                "explanation": "Entry candidates come from conventional Python start-file names.",
                "confidence": ConfidenceLevel.MEDIUM if _entry_paths(run_state) else ConfidenceLevel.LOW,
                "evidence_refs": _entry_paths(run_state),
            },
        ],
        language_and_type=LanguageTypeSection(
            primary_language=file_tree.primary_language,
            project_types=[],
            degradation_notice=None,
        ),
        key_directories=_key_directories(run_state),
        entry_section=EntrySection(
            status=DerivedStatus.HEURISTIC if _entry_paths(run_state) else DerivedStatus.UNKNOWN,
            entries=[
                EntryCandidate(
                    entry_id=new_id("entry"),
                    target_type=EntryTargetType.FILE,
                    target_value=path,
                    reason="Conventional Python entry filename.",
                    confidence=ConfidenceLevel.MEDIUM,
                    rank=index + 1,
                    entry_role=EntryRole.UNCERTAIN,
                    evidence_refs=[path],
                )
                for index, path in enumerate(_entry_paths(run_state))
            ],
            fallback_advice=(
                None
                if _entry_paths(run_state)
                else "Start from README.md or root config, then verify the runtime handoff manually."
            ),
            unknown_items=[],
        ),
        recommended_first_step=RecommendedStep(
            target=_recommended_first_target(run_state),
            reason="Start with a repo-level map before diving into implementation details.",
            learning_gain="You build the vocabulary needed to read the deeper report sections.",
            evidence_refs=[_recommended_first_target(run_state)],
        ),
        reading_path_preview=[
            ReadingStep(
                step_no=index + 1,
                target=path,
                target_type=ReadingTargetType.FILE,
                reason=reason,
                learning_gain=gain,
                evidence_refs=[path],
            )
            for index, (path, reason, gain) in enumerate(_reading_path(run_state))
        ],
        unknown_section=_unknown_items(run_state),
        suggested_next_questions=suggestions,
    )
    return InitialReportAnswer(
        answer_id=new_id("msg_agent_init"),
        message_type=MessageType.INITIAL_REPORT,
        raw_text=render_final_report(repository, file_tree, run_state, synthesis_notes, group_notes),
        initial_report_content=initial_report_content,
        suggestions=suggestions,
        used_evidence_refs=[item.relative_path for item in run_state.relevant_files if item.selected][:10],
        warnings=[],
    )


def _build_packet(repository: RepositoryContext, item) -> ResearchPacket:
    source_text = _read_source_text(repository, item.relative_path)
    symbol_names, import_names = _extract_python_outline(item.relative_path, source_text)
    return ResearchPacket(
        packet_id=new_id("pkt"),
        relative_path=item.relative_path,
        source_kind=item.source_kind,
        group_key=item.group_key,
        excerpt=_excerpt(source_text),
        symbol_names=symbol_names,
        import_names=import_names,
        path_tags=_path_tags(item.relative_path),
        file_summary=_file_summary(item.relative_path, symbol_names, import_names),
    )


def _read_source_text(repository: RepositoryContext, relative_path: str) -> str:
    repo_root = Path(repository.root_path).expanduser().resolve(strict=True)
    path = resolve_repo_relative_path(repo_root, relative_path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _extract_python_outline(relative_path: str, source_text: str) -> tuple[list[str], list[str]]:
    if not relative_path.endswith(".py"):
        return [], []
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return [], []
    symbol_names: list[str] = []
    import_names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbol_names.append(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                import_names.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            import_names.append(module or "." * node.level)
    return symbol_names, _dedupe_text(import_names)


def _excerpt(source_text: str, max_lines: int = 80) -> str:
    return "\n".join(source_text.splitlines()[:max_lines]).strip()


def _file_summary(relative_path: str, symbol_names: list[str], import_names: list[str]) -> str:
    if symbol_names:
        return f"{relative_path} defines {', '.join(symbol_names[:4])}."
    if import_names:
        return f"{relative_path} imports {', '.join(import_names[:4])}."
    return f"{relative_path} contributes source or repository context for the first deep pass."


def _path_tags(relative_path: str) -> list[str]:
    tags: list[str] = []
    name = PurePosixPath(relative_path).name
    if name in ENTRY_FILENAMES:
        tags.append("entry_candidate")
    if relative_path.startswith("docs/") or name.startswith("README"):
        tags.append("repo_doc")
    if name.endswith(".toml") or name in {"requirements.txt", "setup.py"}:
        tags.append("config")
    return tags


def _group_summary(group_key: str, packets: list[ResearchPacket]) -> str:
    packet_count = len(packets)
    source_descriptions = [packet.file_summary for packet in packets[:3] if packet.file_summary]
    summary = f"The {group_key} group covers {packet_count} selected file(s)."
    if source_descriptions:
        summary += " " + " ".join(source_descriptions)
    return summary


def _candidate_flows_for_packets(packets: list[ResearchPacket]) -> list[str]:
    flow_points: list[str] = []
    for packet in packets:
        name = PurePosixPath(packet.relative_path).name
        if name in ENTRY_FILENAMES:
            flow_points.append(
                f"{packet.relative_path} looks like a start file and imports {', '.join(packet.import_names[:3]) or 'local setup code'}."
            )
        elif packet.import_names:
            flow_points.append(
                f"{packet.relative_path} connects to {', '.join(packet.import_names[:3])}."
            )
    return _dedupe_text(flow_points)


def _repository_verdict(repository: RepositoryContext, file_tree, selected_files: list[str], group_notes: list[ResearchNote]) -> str:
    group_count = len(group_notes) or 1
    return (
        f"{repository.display_name} reads like a {file_tree.primary_language} repository with "
        f"{len(selected_files)} relevant file(s) in the deep first pass across {group_count} module group(s). "
        "The report is optimized to establish a source-backed mental model before any line-by-line walkthrough."
    )


def _reading_framework_points(selected_files: list[str]) -> list[str]:
    points: list[str] = []
    if "README.md" in selected_files:
        points.append("Read README.md to anchor vocabulary and startup expectations.")
    if "pyproject.toml" in selected_files:
        points.append("Scan pyproject.toml to confirm packaging and script entry hints.")
    for path in selected_files:
        if PurePosixPath(path).name in ENTRY_FILENAMES:
            points.append(f"Verify {path} as a likely entry candidate.")
    if not points and selected_files:
        points.append(f"Start with {selected_files[0]} because it sits closest to the repo root.")
    return points[:5]


def _entry_summary(entry_paths: list[str]) -> str:
    if entry_paths:
        return (
            "The deep pass found conventional Python start-file names. They are still heuristic entries, "
            "but they are the best starting points for a source-first walkthrough."
        )
    return "No conventional Python start file stood out strongly, so the startup path remains an open question."


def _open_questions(entry_paths: list[str], imports: list[str]) -> list[str]:
    questions: list[str] = []
    if not entry_paths:
        questions.append("Which file or command actually launches the product runtime?")
    if not imports:
        questions.append("Which imports connect the root files to the main implementation path?")
    questions.append("Which modules own the state transitions that matter most at runtime?")
    return questions


def _is_config_or_doc(relative_path: str) -> bool:
    name = PurePosixPath(relative_path).name
    return (
        name in {"README.md", "pyproject.toml", "requirements.txt", "setup.py"}
        or relative_path.startswith("docs/")
    )


def _recommended_first_target(run_state: DeepResearchRunState) -> str:
    selected = [item.relative_path for item in run_state.relevant_files if item.selected]
    for target in ("README.md", "pyproject.toml"):
        if target in selected:
            return target
    return selected[0] if selected else "(no readable file selected)"


def _reading_path(run_state: DeepResearchRunState) -> list[tuple[str, str, str]]:
    selected = [item.relative_path for item in run_state.relevant_files if item.selected]
    ordered: list[str] = []
    for target in ("README.md", "pyproject.toml"):
        if target in selected:
            ordered.append(target)
    ordered.extend(path for path in _entry_paths(run_state) if path not in ordered)
    ordered.extend(path for path in selected if path not in ordered)
    triples: list[tuple[str, str, str]] = []
    for path in ordered[:3]:
        if path == "README.md":
            triples.append((path, "Anchor the repo vocabulary first.", "You understand the repo surface."))
        elif path == "pyproject.toml":
            triples.append((path, "Confirm scripts and packaging clues.", "You see how the repo advertises itself."))
        elif PurePosixPath(path).name in ENTRY_FILENAMES:
            triples.append((path, "Verify the likely startup handoff.", "You see where execution may begin."))
        else:
            triples.append((path, "Inspect one representative implementation file.", "You connect the map to real code."))
    return triples


def _key_directories(run_state: DeepResearchRunState) -> list[KeyDirectoryItem]:
    groups = sorted(
        {
            item.group_key
            for item in run_state.relevant_files
            if item.selected and item.group_key != "(root)"
        }
    )
    return [
        KeyDirectoryItem(
            path=group,
            role="Selected source group for the deep first pass.",
            main_path_role=MainPathRole.MAIN_PATH,
            confidence=ConfidenceLevel.MEDIUM,
            evidence_refs=[
                item.relative_path
                for item in run_state.relevant_files
                if item.selected and item.group_key == group
            ][:5],
        )
        for group in groups[:6]
    ]


def _unknown_items(run_state: DeepResearchRunState) -> list[UnknownItem]:
    items: list[UnknownItem] = []
    if not _entry_paths(run_state):
        items.append(
            UnknownItem(
                unknown_id=new_id("unk"),
                topic=UnknownTopic.ENTRY,
                description="A reliable startup entry was not confirmed from the selected files.",
                related_paths=[],
                reason="No conventional entry filename provided decisive evidence.",
                user_visible=True,
            )
        )
    return items


def _entry_paths(run_state: DeepResearchRunState) -> list[str]:
    return [
        item.relative_path
        for item in run_state.relevant_files
        if item.selected and PurePosixPath(item.relative_path).name in ENTRY_FILENAMES
    ]


def _dedupe_text(values) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        deduped.append(cleaned)
        seen.add(cleaned)
    return deduped
