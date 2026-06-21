from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True)
class HoverContent:
    text: str


class HoverContentCache:
    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max(1, max_entries)
        self._items: OrderedDict[tuple[str, int, str, str], HoverContent] = OrderedDict()

    def get(self, key: tuple[str, int, str, str]) -> HoverContent | None:
        value = self._items.get(key)
        if value is None:
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: tuple[str, int, str, str], value: HoverContent) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)
