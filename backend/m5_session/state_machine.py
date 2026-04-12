from backend.contracts.enums import ClientView, ConversationSubStatus, SessionStatus

ALLOWED_STATUS_TRANSITIONS: set[tuple[SessionStatus, SessionStatus]] = {
    (SessionStatus.IDLE, SessionStatus.ACCESSING),
    (SessionStatus.ACCESSING, SessionStatus.ANALYZING),
    (SessionStatus.ANALYZING, SessionStatus.CHATTING),
    (SessionStatus.ACCESSING, SessionStatus.ACCESS_ERROR),
    (SessionStatus.ANALYZING, SessionStatus.ANALYSIS_ERROR),
    (SessionStatus.ACCESS_ERROR, SessionStatus.ACCESSING),
    (SessionStatus.ANALYSIS_ERROR, SessionStatus.ACCESSING),
    (SessionStatus.CHATTING, SessionStatus.IDLE),
    (SessionStatus.ACCESS_ERROR, SessionStatus.IDLE),
    (SessionStatus.ANALYSIS_ERROR, SessionStatus.IDLE),
}


def view_for_status(status: SessionStatus, sub_status: ConversationSubStatus | None) -> ClientView:
    if status in {SessionStatus.IDLE, SessionStatus.ACCESS_ERROR, SessionStatus.ANALYSIS_ERROR}:
        return ClientView.INPUT
    if status in {SessionStatus.ACCESSING, SessionStatus.ANALYZING}:
        return ClientView.ANALYSIS
    if status == SessionStatus.CHATTING:
        return ClientView.CHAT
    raise ValueError(f"Unsupported session status: {status}")


def assert_sub_status_allowed(
    status: SessionStatus,
    sub_status: ConversationSubStatus | None,
) -> None:
    if status == SessionStatus.CHATTING:
        if sub_status not in {
            ConversationSubStatus.WAITING_USER,
            ConversationSubStatus.AGENT_THINKING,
            ConversationSubStatus.AGENT_STREAMING,
        }:
            raise ValueError("chatting requires a valid ConversationSubStatus")
        return
    if sub_status is not None:
        raise ValueError("ConversationSubStatus is only valid when status=chatting")


def assert_transition_allowed(current: SessionStatus, target: SessionStatus) -> None:
    if current == target:
        return
    if (current, target) not in ALLOWED_STATUS_TRANSITIONS:
        raise ValueError(f"Invalid session transition: {current} -> {target}")
