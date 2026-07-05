from __future__ import annotations

from netconsole.models.mib_models import DictionarySetRecord
from netconsole.repositories.global_mib_repository import GlobalMibRepository


class MibDictionaryService:
    def __init__(self, repository: GlobalMibRepository) -> None:
        self.repository = repository

    def list_dictionary_sets(self) -> list[dict[str, object]]:
        return self.repository.list_dictionary_sets()

    def create_dictionary_set(self, name: str, *, vendor: str = "", device_type: str = "", description: str = "") -> int:
        return self.repository.ensure_dictionary_set(
            DictionarySetRecord(name=name, vendor=vendor, device_type=device_type, description=description, is_builtin=0, enabled_by_default=0)
        )

    def add_module(self, dictionary_set_id: int, module_id: int, priority: int = 100) -> None:
        self.repository.add_dictionary_module(dictionary_set_id, module_id, priority)

