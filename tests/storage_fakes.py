from __future__ import annotations

import json
from collections import deque
from typing import Any


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> FakeResult:
        return self

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)


class FakeConnection:
    def __init__(self, results: list[FakeResult] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._results = deque(results or [])

    def execute(self, statement: Any, parameters: Any = None) -> FakeResult:
        self.calls.append((str(statement), parameters))
        return self._results.popleft() if self._results else FakeResult()


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}
        self.lists: dict[str, list[str]] = {}

    def set(
        self,
        name: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> bool:
        if nx and name in self.values:
            return False
        self.values[name] = value
        self.expirations[name] = ex
        return True

    def get(self, name: str) -> bytes | None:
        value = self.values.get(name)
        return value.encode("utf-8") if value is not None else None

    def delete(self, name: str) -> int:
        existed = name in self.values
        self.values.pop(name, None)
        self.expirations.pop(name, None)
        return int(existed)

    def ttl(self, name: str) -> int:
        return self.expirations.get(name, -2)

    def rpush(self, name: str, value: str) -> int:
        values = self.lists.setdefault(name, [])
        values.append(value)
        return len(values)

    def lrange(self, name: str, start: int, end: int) -> list[bytes]:
        values = self.lists.get(name, [])
        stop = len(values) if end == -1 else end + 1
        return [value.encode("utf-8") for value in values[start:stop]]

    def expire(self, name: str, seconds: int) -> bool:
        if name not in self.values and name not in self.lists:
            return False
        self.expirations[name] = seconds
        return True

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> int:
        del script
        if numkeys != 1 or len(keys_and_args) != 4:
            raise ValueError("FakeRedis only supports run-state transitions")
        key, expected_payload, new_payload, ttl = keys_and_args
        current = self.values.get(key)
        if current is None:
            return -1
        expected = json.loads(expected_payload)
        if json.loads(current)["status"] not in expected:
            return 0
        self.values[key] = new_payload
        self.expirations[key] = int(ttl)
        return 1
