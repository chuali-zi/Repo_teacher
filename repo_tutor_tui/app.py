from __future__ import annotations

import asyncio
import traceback

from backend.contracts.domain import UserFacingErrorException
from backend.contracts.enums import RuntimeEventType, SessionStatus
from backend.m5_session.session_service import SessionService
from repo_tutor_tui.constants import BANNER, HELP_TEXT, QUIT_COMMANDS, STEP_ICONS, STEP_LABELS
from repo_tutor_tui.render import (
    print_error,
    print_rule,
    print_suggestions,
    print_teaching_debug_events,
)


class TuiApp:
    def __init__(self, service: SessionService | None = None) -> None:
        self.svc = service or SessionService()
        self.session_id: str | None = None

    def prompt(self, label: str) -> str:
        try:
            return input(label).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            raise SystemExit(0) from None

    async def run(self) -> None:
        print(BANNER)
        print("输入 `/help` 查看命令。")
        print_rule()
        while True:
            if self.session_id is None:
                await self.input_repo()
            else:
                await self.chat_loop()

    async def input_repo(self) -> None:
        print("请输入仓库绝对路径或公开 GitHub URL。")
        while self.session_id is None:
            raw = self.prompt("仓库> ")
            if not raw:
                continue
            if raw.startswith("/"):
                if self.handle_command(raw):
                    return
                continue

            validation = self.svc.validate_repo_input(raw)
            if not validation.is_valid:
                print_error(
                    "格式错误",
                    validation.message or "请输入本地仓库绝对路径或 GitHub 公开仓库 URL",
                    f"input_kind={validation.input_kind}",
                )
                continue

            try:
                data = self.svc.create_repo_session(raw)
            except UserFacingErrorException as exc:
                print_error(
                    str(exc.error.error_code),
                    exc.error.message,
                    exc.error.internal_detail,
                )
                continue
            except Exception as exc:
                print_error("创建会话失败", str(exc), traceback.format_exc())
                continue

            active = self.svc.store.active_session
            self.session_id = active.session_id if active else None
            if self.session_id is None:
                print_error("会话异常", "会话已创建，但 session_id 为空")
                continue

            print(f"\n✓ 输入有效: {validation.normalized_input}")
            print(f"仓库: {data.repository.display_name}")
            print(f"session_id: {self.session_id}")
            print_rule()
            print("分析开始...\n")
            await self.stream_initial_analysis()

    async def stream_initial_analysis(self) -> None:
        assert self.session_id is not None
        had_error = False
        printed_agent_prefix = False

        try:
            async for event in self.svc.run_initial_analysis(self.session_id):
                if event.event_type == RuntimeEventType.ANALYSIS_PROGRESS:
                    label = STEP_LABELS.get(str(event.step_key), str(event.step_key))
                    icon = STEP_ICONS.get(str(event.step_state), ".")
                    notice = event.user_notice or ""
                    print(f"{icon} {label}  {notice}")
                    continue

                if event.event_type == RuntimeEventType.DEGRADATION_NOTICE and event.degradation:
                    print(
                        f"\n! 降级提示: {event.degradation.user_notice} "
                        f"(类型: {event.degradation.type})"
                    )
                    if event.degradation.reason:
                        print(f"  原因: {event.degradation.reason}")
                    continue

                if event.event_type == RuntimeEventType.ANSWER_STREAM_START:
                    print("\n首轮教学报告")
                    print_rule("=")
                    print("Agent> ", end="", flush=True)
                    printed_agent_prefix = True
                    continue

                if event.event_type == RuntimeEventType.ANSWER_STREAM_DELTA:
                    chunk = event.message_chunk or ""
                    if chunk:
                        print(chunk, end="", flush=True)
                    continue

                if event.event_type == RuntimeEventType.ANSWER_STREAM_END:
                    if printed_agent_prefix:
                        print()
                    print_rule("=")
                    continue

                if event.event_type == RuntimeEventType.MESSAGE_COMPLETED:
                    print_suggestions(
                        (event.payload or {}).get("message", {}).get("suggestions", [])
                    )
                    continue

                if event.event_type == RuntimeEventType.ERROR:
                    had_error = True
                    err = event.error
                    if err is not None:
                        print_error(str(err.error_code), err.message, err.internal_detail)
                    else:
                        print_error("未知错误", "分析过程发生错误")
        except UserFacingErrorException as exc:
            had_error = True
            print_error(str(exc.error.error_code), exc.error.message, exc.error.internal_detail)
        except Exception as exc:
            had_error = True
            print_error("分析异常", str(exc), traceback.format_exc())

        if had_error:
            session = self.svc.store.active_session
            if session and session.status in {
                SessionStatus.ACCESS_ERROR,
                SessionStatus.ANALYSIS_ERROR,
            }:
                self.svc.clear_active_session()
                self.session_id = None
            print("\n分析失败，可输入新的仓库路径重试。")

    async def chat_loop(self) -> None:
        session = self.svc.store.active_session
        if session is None or session.status != SessionStatus.CHATTING:
            self.session_id = None
            return

        print("\n进入对话模式。输入内容后按 Enter 发送，输入 `/help` 查看命令。")
        print_rule()

        while self.session_id is not None:
            session = self.svc.store.active_session
            if session is None or session.status != SessionStatus.CHATTING:
                self.session_id = None
                return

            user_text = self.prompt("你> ")
            if not user_text:
                continue
            if user_text.startswith("/"):
                if self.handle_command(user_text):
                    return
                continue

            try:
                self.svc.accept_chat_message(self.session_id, user_text)
            except UserFacingErrorException as exc:
                print_error(
                    str(exc.error.error_code),
                    exc.error.message,
                    exc.error.internal_detail,
                )
                continue
            except Exception as exc:
                print_error("发送消息失败", str(exc), traceback.format_exc())
                continue

            await self.stream_chat_turn()

    async def stream_chat_turn(self) -> None:
        assert self.session_id is not None
        printed_agent_prefix = False

        try:
            async for event in self.svc.run_chat_turn(self.session_id):
                if event.event_type == RuntimeEventType.ANSWER_STREAM_START:
                    print("Agent> ", end="", flush=True)
                    printed_agent_prefix = True
                    continue

                if event.event_type == RuntimeEventType.ANSWER_STREAM_DELTA:
                    chunk = event.message_chunk or ""
                    if chunk:
                        print(chunk, end="", flush=True)
                    continue

                if event.event_type == RuntimeEventType.ANSWER_STREAM_END:
                    if printed_agent_prefix:
                        print()
                    print_rule()
                    continue

                if event.event_type == RuntimeEventType.MESSAGE_COMPLETED:
                    print_suggestions(
                        (event.payload or {}).get("message", {}).get("suggestions", [])
                    )
                    continue

                if event.event_type == RuntimeEventType.ERROR:
                    err = event.error
                    if err is not None:
                        print_error(str(err.error_code), err.message, err.internal_detail)
                    else:
                        print_error("回答失败", "Agent 回答过程发生错误")
        except UserFacingErrorException as exc:
            print_error(str(exc.error.error_code), exc.error.message, exc.error.internal_detail)
        except Exception as exc:
            print_error("对话异常", str(exc), traceback.format_exc())

    def handle_command(self, raw: str) -> bool:
        command = raw.strip().lower()
        if command in QUIT_COMMANDS:
            print("再见！")
            raise SystemExit(0)
        if command == "/help":
            print(HELP_TEXT)
            return False
        if command == "/new":
            self.reset_session()
            return True
        if command == "/status":
            self.print_status()
            return False
        if command == "/debug":
            self.print_debug()
            return False
        print(f"未知命令: {command}")
        return False

    def reset_session(self) -> None:
        if self.session_id is not None:
            try:
                self.svc.clear_session(self.session_id)
            except Exception:
                self.svc.clear_active_session()
        self.session_id = None
        print("\n✓ 当前会话已清理")
        print_rule()

    def print_status(self) -> None:
        session = self.svc.store.active_session
        if session is None:
            print("当前无活跃会话")
            return
        print(f"session_id : {session.session_id}")
        print(f"status     : {session.status}")
        print(f"sub_status : {session.conversation.sub_status}")
        print(f"learning   : {session.conversation.current_learning_goal}")
        print(f"depth      : {session.conversation.depth_level}")
        print(f"stage      : {session.conversation.current_stage}")
        if session.repository is not None:
            print(f"repo       : {session.repository.display_name}")
            print(f"language   : {session.repository.primary_language}")
            print(f"size       : {session.repository.repo_size_level}")
            print(f"files      : {session.repository.source_code_file_count}")
        print(f"messages   : {len(session.conversation.messages)}")
        print(f"explained  : {len(session.conversation.explained_items)}")

    def print_debug(self) -> None:
        session = self.svc.store.active_session
        if session is None:
            print("当前无活跃会话")
            return
        print_teaching_debug_events(session.conversation.teaching_debug_events[-5:])


def main() -> None:
    try:
        asyncio.run(TuiApp().run())
    except KeyboardInterrupt:
        print("\n再见！")
