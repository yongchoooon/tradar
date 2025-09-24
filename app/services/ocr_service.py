"""Simplified OCR that interprets bytes as UTF-8 text."""

from __future__ import annotations


class OCRService:
    def extract(self, image: bytes) -> str:
        return image.decode("utf-8", errors="ignore").strip()
