from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from services.translation.services.results.page_io import save_pages


class TranslationFlushState:
    def __init__(
        self,
        *,
        page_payloads: dict[int, list[dict]],
        translation_paths: dict[int, Path],
        flush_interval: int,
        total_batches: int,
        progress_callback: Callable[[int, int, set[int], str], None] | None = None,
        flush_callback: Callable[[set[int]], None] | None = None,
    ) -> None:
        self.page_payloads = page_payloads
        self.translation_paths = translation_paths
        self.flush_interval = max(1, flush_interval)
        self.total_batches = total_batches
        self.progress_callback = progress_callback
        self.flush_callback = flush_callback
        self.dirty_pages: set[int] = set()
        self._last_progress_emit_at = 0.0
        self._last_progress_emit_completed = 0
        self._last_flush_completed = 0

    def mark_dirty(self, pages: set[int]) -> None:
        self.dirty_pages.update(pages)

    def record_progress(self, completed: int, touched_pages: set[int], *, substage: str = "translation_batches") -> None:
        if self.progress_callback is not None:
            now = time.perf_counter()
            if (
                completed < self.total_batches
                and completed - self._last_progress_emit_completed < 20
                and now - self._last_progress_emit_at < 1.0
            ):
                return
            self._last_progress_emit_at = now
            self._last_progress_emit_completed = completed
            self.progress_callback(completed, self.total_batches, touched_pages, substage)

    def flush_if_due(self, completed: int, *, label: str) -> None:
        if completed < self.total_batches and completed - self._last_flush_completed < self.flush_interval:
            return
        self.flush(label=label)
        self._last_flush_completed = completed

    def flush(self, *, label: str) -> None:
        if not self.dirty_pages:
            return
        save_started = time.perf_counter()
        flushed_pages = set(self.dirty_pages)
        page_count = len(flushed_pages)
        save_pages(self.page_payloads, self.translation_paths, flushed_pages)
        print(
            f"book: {label} pages={page_count} in {time.perf_counter() - save_started:.2f}s",
            flush=True,
        )
        if self.flush_callback is not None:
            self.flush_callback(flushed_pages)
        self.dirty_pages.clear()

    def final_flush(self) -> None:
        self.flush(label="final flush")


__all__ = ["TranslationFlushState"]
