from __future__ import annotations

from netconsole.repositories.global_mib_repository import GlobalMibRepository


class MibIndexService:
    def __init__(self, repository: GlobalMibRepository) -> None:
        self.repository = repository

    def search_objects(self, keyword: str = "", module_name: str = "", limit: int = 1000, source_filter: str = "", dictionary_ids: list[int] | None = None, module_id: int | None = None) -> list[dict[str, object]]:
        return self.repository.list_objects(keyword, module_name, limit, source_filter=source_filter, dictionary_ids=dictionary_ids, module_id=module_id)

    def object_query_method(self, item: dict[str, object]) -> tuple[str, str]:
        oid = str(item.get("oid") or "")
        syntax = str(item.get("syntax") or "")
        if not oid:
            return "", ""
        if int(item.get("is_trap") or 0) or int(item.get("is_notification") or 0):
            return "", "这是 Trap / Notification 定义，不支持 Get。可以加入 Trap 解析规则。"
        if int(item.get("is_scalar") or 0):
            return "Get", oid if oid.endswith(".0") else f"{oid}.0"
        if int(item.get("is_table") or 0) or "SEQUENCE OF" in syntax:
            return "BulkWalk", oid
        if int(item.get("is_table_entry") or 0):
            return "Walk", oid
        if int(item.get("is_column") or 0):
            return "BulkWalk", oid
        return "GetNext", oid
