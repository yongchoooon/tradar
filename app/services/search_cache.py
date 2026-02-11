"""In-memory cache for recent search results used by simulation."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from uuid import uuid4

from app.schemas.search import SearchResponse, SearchResult
from app.schemas.simulation import SimulationSelection


@dataclass
class SearchCacheEntry:
    created_at: float
    selections: Dict[Tuple[str, str], SimulationSelection]


class SearchCache:
    def __init__(self) -> None:
        self._ttl_seconds = int(os.getenv("SIMULATION_SEARCH_CACHE_TTL_SECONDS", "1800"))
        self._max_entries = int(os.getenv("SIMULATION_SEARCH_CACHE_MAX_ENTRIES", "1500"))
        self._entries: Dict[str, SearchCacheEntry] = {}

    def store(self, response: SearchResponse) -> str:
        self._prune()
        search_id = uuid4().hex
        selections = self._build_selection_map(response)
        self._entries[search_id] = SearchCacheEntry(
            created_at=time.time(),
            selections=selections,
        )
        return search_id

    def get(self, search_id: str) -> Optional[SearchCacheEntry]:
        entry = self._entries.get(search_id)
        if not entry:
            return None
        if time.time() - entry.created_at > self._ttl_seconds:
            self._entries.pop(search_id, None)
            return None
        return entry

    def _prune(self) -> None:
        if not self._entries:
            return
        now = time.time()
        expired = [key for key, entry in self._entries.items() if now - entry.created_at > self._ttl_seconds]
        for key in expired:
            self._entries.pop(key, None)
        if len(self._entries) <= self._max_entries:
            return
        sorted_items = sorted(self._entries.items(), key=lambda item: item[1].created_at)
        for key, _ in sorted_items[: max(0, len(sorted_items) - self._max_entries)]:
            self._entries.pop(key, None)

    def _build_selection_map(self, response: SearchResponse) -> Dict[Tuple[str, str], SimulationSelection]:
        selections: Dict[Tuple[str, str], SimulationSelection] = {}
        for variant, items in (
            ("image", list(response.image_top or []) + list(response.image_misc or [])),
            ("text", list(response.text_top or []) + list(response.text_misc or [])),
        ):
            for item in items:
                key = (item.app_no, variant)
                if key in selections:
                    continue
                selections[key] = self._selection_from_result(item, variant)
        return selections

    @staticmethod
    def _selection_from_result(item: SearchResult, variant: str) -> SimulationSelection:
        return SimulationSelection(
            application_number=item.app_no,
            title=item.title,
            variant=variant,
            image_sim=item.image_sim,
            text_sim=item.text_sim,
            status=item.status,
            class_codes=list(item.class_codes or []),
            image_path=item.image_path,
            thumb_url=item.thumb_url,
            goods_services=item.goods_services,
        )


search_cache = SearchCache()
