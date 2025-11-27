"""Client utilities for KIPRIS intermediate document APIs."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import httpx


def _extract_text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _ensure_list(value: Optional[List[str]]) -> List[str]:
    return value if isinstance(value, list) else []


class KiprisClient:
    """Minimal XML client for fetching opinion/rejection details."""

    def __init__(self, *, access_key: Optional[str] = None, timeout: float = 15.0) -> None:
        self.access_key = access_key or os.getenv("KIPRIS_ACCESS_KEY")
        if not self.access_key:
            raise RuntimeError("KIPRIS_ACCESS_KEY 환경 변수가 필요합니다.")
        self.base_op = os.getenv(
            "KIPRIS_OP_BASE",
            "http://plus.kipris.or.kr/openapi/rest/IntermediateDocumentOPService",
        )
        self.base_re = os.getenv(
            "KIPRIS_RE_BASE",
            "http://plus.kipris.or.kr/openapi/rest/IntermediateDocumentREService",
        )
        self._client = httpx.Client(timeout=timeout)

    def fetch_documents(self, application_number: str) -> Dict[str, object]:
        return {
            "office_action": self._fetch_office_action(application_number),
            "rejection": self._fetch_rejection_decision(application_number),
        }

    def _fetch_office_action(self, app_no: str) -> Dict[str, object]:
        return {
            "reasons": self._fetch_reject_details(self.base_op, "rejectDecisionInfo", app_no),
            "addition": self._fetch_addition(self.base_op, "additionRejectInfo", app_no),
            "result": self._fetch_simple_field(self.base_op, "examinationResultInfo", app_no, "examinationResult"),
            "images": self._fetch_images(self.base_op, "imageInfo", app_no),
            "last_transfer": self._fetch_last_transfer(self.base_op, app_no),
        }

    def _fetch_rejection_decision(self, app_no: str) -> Dict[str, object]:
        return {
            "reasons": self._fetch_reject_details(self.base_re, "rejectDecisionInfo", app_no),
            "addition": self._fetch_addition(self.base_re, "additionRejectInfo", app_no),
            "result": self._fetch_simple_field(self.base_re, "examinationResultInfo", app_no, "examinationResult"),
            "images": self._fetch_images(self.base_re, "imageInfo", app_no),
            "last_transfer": self._fetch_last_transfer(self.base_re, app_no),
        }

    def _fetch_last_transfer(self, base: str, app_no: str) -> Optional[str]:
        root = self._request(base, "lastTransferDateInfo", app_no)
        if root is None:
            return None
        entry = root.find(".//lastTransferDateInfo")
        return _extract_text(entry) or None

    def _fetch_reject_details(self, base: str, endpoint: str, app_no: str) -> List[str]:
        root = self._request(base, endpoint, app_no)
        if root is None:
            return []
        reasons: List[str] = []
        for info in root.findall(".//rejectDecisionInfo"):
            parts: List[str] = []
            for tag in ("lawContent", "rejectionContentTitle", "rejectionContentDetail", "guidanceTitle", "guidanceContent"):
                text = _extract_text(info.find(tag))
                if text:
                    parts.append(text)
            if parts:
                reasons.append("\n".join(parts))
        return reasons

    def _fetch_addition(self, base: str, endpoint: str, app_no: str) -> List[str]:
        root = self._request(base, endpoint, app_no)
        if root is None:
            return []
        results: List[str] = []
        for info in root.findall(".//additionRejectInfo"):
            text = _extract_text(info.find("additionRejectionContent"))
            if text:
                results.append(text)
        return results

    def _fetch_images(self, base: str, endpoint: str, app_no: str) -> List[str]:
        root = self._request(base, endpoint, app_no)
        if root is None:
            return []
        images: List[str] = []
        for info in root.findall(".//imageInfo"):
            file_name = _extract_text(info.find("fileName"))
            file_path = _extract_text(info.find("filePath"))
            target = file_path or file_name
            if target:
                images.append(target)
        return images

    def _fetch_simple_field(self, base: str, endpoint: str, app_no: str, field: str) -> Optional[str]:
        root = self._request(base, endpoint, app_no)
        if root is None:
            return None
        entry = root.find(f".//{field}")
        return _extract_text(entry) or None

    def _request(self, base: str, endpoint: str, app_no: str) -> Optional[ET.Element]:
        url = f"{base.rstrip('/')}/{endpoint}"
        params = {"applicationNumber": app_no, "accessKey": self.access_key}
        try:
            resp = self._client.get(url, params=params)
            if resp.status_code != 200 or not resp.text:
                return None
            return ET.fromstring(resp.text)
        except (httpx.HTTPError, ET.ParseError):
            return None


def format_document_context(bundle: Dict[str, object]) -> str:
    sections: List[str] = []
    reasons = _ensure_list(bundle.get("reasons"))
    addition = _ensure_list(bundle.get("addition"))
    images = _ensure_list(bundle.get("images"))
    if reasons:
        sections.append("주요 거절사유:\n" + "\n".join(reasons))
    if addition:
        sections.append("추가 거절사유:\n" + "\n".join(addition))
    if bundle.get("result"):
        sections.append(f"심사결과: {bundle['result']}")
    if bundle.get("last_transfer"):
        sections.append(f"최종 변동일자: {bundle['last_transfer']}")
    if images:
        sections.append("이미지 참고: " + ", ".join(images[:3]))
    return "\n\n".join(sections)
