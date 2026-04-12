from __future__ import annotations

from backend.contracts.domain import EvidenceRef


class EvidenceCollector:
    def __init__(self) -> None:
        self._items: dict[str, EvidenceRef] = {}

    def add(self, evidence: EvidenceRef) -> str:
        self._items[evidence.evidence_id] = evidence
        return evidence.evidence_id

    def extend(self, evidence_items: list[EvidenceRef]) -> list[str]:
        return [self.add(item) for item in evidence_items]

    def list(self) -> list[EvidenceRef]:
        return list(self._items.values())
