"""Bounded in-memory trace store with optional JSONL persistence."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from .models import AgentTrace


class TraceStore:
    def __init__(self, capacity: int = 200, log_path: Path | None = None) -> None:
        self._items: OrderedDict[str, AgentTrace] = OrderedDict()
        self._capacity = capacity
        self._log_path = log_path

    def put(self, trace: AgentTrace) -> None:
        self._items[trace.trace_id] = trace
        self._items.move_to_end(trace.trace_id)
        while len(self._items) > self._capacity:
            self._items.popitem(last=False)

    def finish(self, trace: AgentTrace) -> None:
        self.put(trace)
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(trace.model_dump_json() + "\n")

    def get(self, trace_id: str) -> AgentTrace | None:
        return self._items.get(trace_id)

    def recent(self, limit: int = 50) -> list[AgentTrace]:
        return list(reversed(self._items.values()))[:limit]
