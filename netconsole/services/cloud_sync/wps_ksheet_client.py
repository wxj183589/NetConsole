from __future__ import annotations

from dataclasses import dataclass
import json
import threading
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from netconsole.models.cloud_sync_models import (
    WpsApiResult,
    WpsKSheetDocument,
    WpsKSheetSheet,
    WpsReadonlyMember,
    WpsShareLink,
)
from netconsole.services.cloud_sync.wps_auth import WpsAuthContext


class WpsApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class WpsEndpointSet:
    base_url: str = "https://developer.kdocs.cn/api/v1/openapi"

    def create_file(self) -> str:
        return f"{self.base_url}/personal/files"

    def sheets_info(self, file_token: str) -> str:
        return f"{self.base_url}/ksheet/{quote(file_token)}/sheets"

    def add_sheet(self, file_token: str) -> str:
        return f"{self.base_url}/ksheet/{quote(file_token)}/sheets"

    def cells(self, file_token: str, sheet_id: str | int) -> str:
        return f"{self.base_url}/ksheet/{quote(file_token)}/sheets/{quote(str(sheet_id))}/cells"

    def member_permission(self, file_token: str, user_id: str) -> str:
        return f"{self.base_url}/personal/files/{quote(file_token)}/links/members/{quote(user_id)}"

    def shares(self, file_token: str) -> str:
        return f"{self.base_url}/personal/files/{quote(file_token)}/links"


class WpsKSheetClient:
    def __init__(
        self,
        auth: WpsAuthContext,
        *,
        endpoints: WpsEndpointSet | None = None,
        timeout: float = 25.0,
        opener=None,
    ) -> None:
        self.auth = auth
        self.endpoints = endpoints or WpsEndpointSet()
        self.timeout = timeout
        self._opener = opener

    def test_connection(self) -> WpsApiResult:
        self.auth.require_token()
        return WpsApiResult(True, "WPS access_token 已配置")

    def create_ksheet(self, name: str, folder_token: str | None = None) -> WpsKSheetDocument:
        filename = name if name.lower().endswith(".ksheet") else f"{name}.ksheet"
        payload: dict[str, object] = {"filename": filename}
        if folder_token:
            payload["parent_id"] = folder_token
        data = self._request("POST", self.endpoints.create_file(), payload)
        token = _first_text(data, "file_token", "token", "id")
        url = _first_text(data, "url", "web_url", "link")
        if not token:
            raise WpsApiError("WPS创建在线表格成功但未返回 file_token")
        return WpsKSheetDocument(file_token=token, name=name, url=url or self.get_document_url(token))

    def get_sheets(self, file_token: str) -> list[WpsKSheetSheet]:
        data = self._request("GET", self.endpoints.sheets_info(file_token))
        raw_sheets = data.get("sheets") or data.get("sheets_info") or data.get("data") or []
        if isinstance(raw_sheets, dict):
            raw_sheets = raw_sheets.get("sheets_info") or raw_sheets.get("sheets") or raw_sheets.get("items") or []
        result: list[WpsKSheetSheet] = []
        for item in raw_sheets if isinstance(raw_sheets, list) else []:
            if not isinstance(item, dict):
                continue
            sheet_id = item.get("sheet_id") or item.get("id") or item.get("sheetId") or item.get("sheet_idx")
            name = item.get("sheet_name") or item.get("name") or item.get("title")
            if sheet_id is not None and name:
                result.append(WpsKSheetSheet(sheet_id=sheet_id, name=str(name)))
        return result

    def ensure_sheet(self, file_token: str, sheet_name: str, headers: list[str] | None = None) -> WpsKSheetSheet:
        sheets = self.get_sheets(file_token)
        for sheet in sheets:
            if sheet.name == sheet_name:
                return sheet
        field_names = headers or ["数据"]
        data = self._request(
            "POST",
            self.endpoints.add_sheet(file_token),
            {
                "name": sheet_name,
                "views": [{"name": "默认视图", "type": "Grid"}],
                "fields": [{"name": name, "type": "Text"} for name in field_names],
            },
        )
        sheet_id = _first_text(data, "sheet_id", "id", "sheetId")
        name = _first_text(data, "name", "title") or sheet_name
        if not sheet_id:
            sheets = self.get_sheets(file_token)
            for sheet in sheets:
                if sheet.name == sheet_name:
                    return sheet
            raise WpsApiError(f"WPS创建sheet失败：{sheet_name}")
        return WpsKSheetSheet(sheet_id=sheet_id, name=name)

    def clear_sheet_data(self, file_token: str, sheet_id: str | int) -> None:
        self._request(
            "POST",
            self.endpoints.cells(file_token, sheet_id),
            {"ranges": [{"op_type": "formula", "row_from": 0, "row_to": 49999, "col_from": 0, "col_to": 701, "formula": ""}]},
        )

    def write_table(
        self,
        file_token: str,
        sheet_id: str | int,
        headers: list[str],
        rows: list[list[object]],
        *,
        batch_size: int = 500,
        cancel_event: threading.Event | None = None,
    ) -> None:
        all_rows = [headers] + rows
        max_columns = max((len(row) for row in all_rows), default=len(headers))
        rows_per_batch = max(1, min(batch_size, 1800 // max(max_columns, 1)))
        for start in range(0, len(all_rows), rows_per_batch):
            if cancel_event is not None and cancel_event.is_set():
                raise WpsApiError("WPS在线表格同步已取消")
            batch = all_rows[start : start + rows_per_batch]
            ranges = []
            for row_offset, row in enumerate(batch):
                for col_index, value in enumerate(row):
                    ranges.append(
                        {
                            "op_type": "formula",
                            "row_from": start + row_offset,
                            "row_to": start + row_offset,
                            "col_from": col_index,
                            "col_to": col_index,
                            "formula": "" if value is None else str(value),
                        }
                    )
            self._request("POST", self.endpoints.cells(file_token, sheet_id), {"ranges": ranges})

    def apply_basic_format(self, file_token: str, sheet_id: str | int, columns: list[dict]) -> None:
        return None

    def set_readonly_members(self, file_token: str, members: list[WpsReadonlyMember]) -> WpsApiResult:
        for member in members:
            if not member.account.strip():
                continue
            payload = {"permission": "read"}
            self._request("PUT", self.endpoints.member_permission(file_token, member.account.strip()), payload)
        return WpsApiResult(True, "只读成员权限已更新")

    def create_readonly_link(self, file_token: str) -> WpsShareLink:
        data = self._request("POST", self.endpoints.shares(file_token), {"permission": "read"})
        url = _first_text(data, "url", "link", "share_url")
        if not url:
            raise WpsApiError("WPS创建只读链接成功但未返回链接")
        return WpsShareLink(url=url)

    def get_document_url(self, file_token: str) -> str:
        return f"https://kdocs.cn/l/{file_token}"

    def _request(self, method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode({'access_token': self.auth.require_token()})}"
        body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if method not in {"GET", "DELETE"} else None
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        attempts = 0
        while True:
            attempts += 1
            try:
                request = Request(url, data=body, method=method, headers=headers)
                if self._opener is not None:
                    response = self._opener(request, timeout=self.timeout)
                else:
                    response = urlopen(request, timeout=self.timeout)
                with response:
                    raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
            except HTTPError as exc:
                message = _safe_error_message(exc)
                if exc.code in {401, 403}:
                    raise WpsApiError("WPS认证失败或权限不足，请重新授权", exc.code) from exc
                if exc.code == 429 and attempts < 4:
                    sleep(0.5 * (2 ** (attempts - 1)))
                    continue
                if 500 <= exc.code < 600 and attempts < 3:
                    sleep(0.5 * attempts)
                    continue
                raise WpsApiError(message, exc.code) from exc
            except URLError as exc:
                if attempts < 3:
                    sleep(0.5 * attempts)
                    continue
                raise WpsApiError(f"WPS网络请求失败：{exc.reason}") from exc


def _safe_error_message(exc: HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw)
        message = data.get("message") or data.get("error") or raw
    except Exception:
        message = str(exc)
    return f"WPS接口请求失败({exc.code})：{message}"


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    candidates: list[Any] = [payload]
    for parent in ("data", "file", "document", "result"):
        nested = payload.get(parent)
        if isinstance(nested, dict):
            candidates.append(nested)
    for item in candidates:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _column_name(index: int) -> str:
    index = max(int(index), 1)
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result
