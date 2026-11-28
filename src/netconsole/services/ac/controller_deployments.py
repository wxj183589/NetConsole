from __future__ import annotations

from collections.abc import Callable

from pydantic import ValidationError

from netconsole.core.atomic_file import atomic_write_bytes, locked_file
from netconsole.core.paths import PathResolver
from netconsole.models.api.ac_management import AcDeploymentsDTO
from netconsole.services.site_manager import SiteManager


class DeploymentConflict(ValueError):
    pass


class DeploymentCorrupt(ValueError):
    pass


class ControllerDeployments:
    def __init__(self, paths: PathResolver, site: str):
        self.site = SiteManager(paths).validate_site_name(site)
        root = paths.site_dir(self.site).resolve()
        self.path = paths.site_files_dir(self.site) / "wireless" / "controller-deployments.v1.json"
        for candidate in (self.path, self.path.with_name(f".{self.path.name}.lock")):
            if not candidate.resolve().is_relative_to(root):
                raise ValueError("无线部署文件越出局点目录")

    def read(self) -> AcDeploymentsDTO:
        try:
            document = AcDeploymentsDTO.model_validate_json(self.path.read_bytes())
        except FileNotFoundError:
            return AcDeploymentsDTO(site_id=self.site)
        except (OSError, ValidationError) as exc:
            raise DeploymentCorrupt("无线部署记录无法读取") from exc
        if document.site_id != self.site:
            raise DeploymentCorrupt("无线部署文件局点不符")
        try:
            self._validate_groups(document)
        except ValueError as exc:
            raise DeploymentCorrupt("无线部署记录不一致") from exc
        return document

    def save(self, update: AcDeploymentsDTO, controllers: set[str], current_site: Callable[[], str] | None = None) -> AcDeploymentsDTO:
        with locked_file(self.path):
            current = self.read()
            if update.site_id != self.site or update.revision != current.revision:
                raise DeploymentConflict("局点或无线部署版本已变化，请刷新")
            self._validate_groups(update, controllers)
            if current_site is not None and current_site() != self.site:
                raise DeploymentConflict("当前局点已切换")
            saved = update.model_copy(update={"revision": current.revision + 1})
            atomic_write_bytes(self.path, saved.model_dump_json().encode("utf-8"))
            return saved

    @staticmethod
    def _validate_groups(update: AcDeploymentsDTO, controllers: set[str] | None = None) -> None:
        names: set[str] = set()
        members: set[str] = set()
        for group in update.groups:
            name = group.name.strip().casefold()
            if not name or name in names:
                raise ValueError("请输入唯一的部署名称")
            names.add(name)
            if group.mode == "standalone" and len(group.members) != 1:
                raise ValueError("独立 AC 仅允许一个控制器")
            if group.mode == "one_plus_one" and len(group.members) != 2:
                raise ValueError("1+1 部署需要两个已登记控制器")
            for member in group.members:
                if not member.strip() or (controllers is not None and member not in controllers) or member in members:
                    raise ValueError("控制器不在当前局点或被重复登记")
                members.add(member)
