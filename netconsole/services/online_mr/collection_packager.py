from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Callable

from netconsole.services.online_mr.collection_paths import OnlineMrCollectionPaths


class OnlineMrCollectionPackager:
    def package(
        self,
        session_dir: Path,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        paths = OnlineMrCollectionPaths.from_session_dir(session_dir)
        paths.package_path.parent.mkdir(parents=True, exist_ok=True)
        paths.package_tmp_path.unlink(missing_ok=True)
        try:
            with zipfile.ZipFile(paths.package_tmp_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for source in sorted(paths.session_dir.rglob("*")):
                    if should_cancel is not None and should_cancel():
                        raise InterruptedError("在线 MR 会话打包已取消")
                    if not source.is_file() or source in {paths.package_path, paths.package_tmp_path}:
                        continue
                    archive.write(source, source.relative_to(paths.session_dir))
            os.replace(paths.package_tmp_path, paths.package_path)
            return paths.package_path
        except Exception:
            paths.package_tmp_path.unlink(missing_ok=True)
            raise
