from __future__ import annotations


def print_rule(char: str = "-", width: int = 72) -> None:
    print(char * width)


def print_error(label: str, message: str, detail: str | None = None) -> None:
    print(f"\nX [{label}] {message}")
    if detail:
        for line in detail.strip().splitlines():
            print(f"  | {line}")


def suggestion_text(item: object) -> str:
    if hasattr(item, "text"):
        return str(getattr(item, "text"))
    if isinstance(item, dict):
        return str(item.get("text", ""))
    return str(item)


def print_suggestions(suggestions: list[object]) -> None:
    if not suggestions:
        return
    print("可继续追问：")
    for index, item in enumerate(suggestions, start=1):
        print(f"  {index}. {suggestion_text(item)}")


def print_teaching_debug_events(events: list[object]) -> None:
    if not events:
        print("暂无教学调试事件")
        return
    print(f"最近 {len(events)} 条教学调试事件：")
    for event in events:
        timestamp = event.occurred_at.strftime("%H:%M:%S") if event.occurred_at else "?"
        print(f"[{timestamp}] {event.event_type}: {event.summary}")
        for key, value in (event.details or {}).items():
            value_text = str(value)
            if len(value_text) > 100:
                value_text = value_text[:97] + "..."
            print(f"  {key}: {value_text}")
