from __future__ import annotations

from backend.contracts.domain import AnalysisBundle, UnknownItem


def aggregate_user_visible_unknowns(analysis: AnalysisBundle) -> list[UnknownItem]:
    aggregated: list[UnknownItem] = []
    seen_ids: set[str] = set()

    def include(items: list[UnknownItem]) -> None:
        for item in items:
            if not item.user_visible or item.unknown_id in seen_ids:
                continue
            aggregated.append(item)
            seen_ids.add(item.unknown_id)

    include(analysis.unknown_items)
    for entry in analysis.entry_candidates:
        include(entry.unknown_items)

    return aggregated
