"""旧导入路径兼容层；新代码使用 external_tool_service。"""

from netconsole.core.paths import PathResolver
from netconsole.services.external_tool_service import ExternalToolLaunchResult, launch_ipop


def launch_ipop_as_admin(paths: PathResolver | None = None) -> ExternalToolLaunchResult:
    return launch_ipop(paths)
