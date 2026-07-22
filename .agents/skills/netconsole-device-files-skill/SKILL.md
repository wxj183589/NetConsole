---
name: netconsole-device-files-skill
description: "NetConsole 设备文件下载、只读 SFTP、SSH/SFTP 能力区分、主机密钥确认、受控启用 SFTP、下载队列恢复、.part 清理、WinSCP 或文件管理首屏性能任务时使用。普通设备 SSH、配置采集或 MESH 离线分析不使用本 Skill。"
---

# 目标

维护只读设备文件浏览和可恢复下载，区分 SSH 与 SFTP 能力，并把设备配置动作限制在一次受控确认链路。

# 输入与路径

确认设备角色/版本、连接阶段、主机密钥状态、原始下载意图和队列场景。先读 `docs/device-files/`、`apps/web/src/views/file-management/README.md`、File Router/DTO、`file_management_service.py`、`file_transfer_service.py`、`task_repository.py` 与 `tests/test_file_management_service.py`。

# 工作流

1. 分阶段加载能力、页面、本地目录、设备、最近 20 条队列和远程目录；活动下载优先。
2. SSH 认证成功不等于 SFTP 可用。只有 SFTP 子系统明确拒绝且命中精确 `device.sftp.enable` Profile 时，才签发一次性受控确认。
3. 主机密钥确认必须保留原连接意图，包括启用 SFTP 后重新连接、读取根目录和继续下载。
4. 页面不提供长期自动配置开关；不接受任意命令、工具路径、输出路径、上传、删除、重命名或覆盖配置。
5. 下载使用 `tasks.db` SQL 组合过滤和批量事件读取；不要恢复 N+1。
6. `status/local/downloads` 不清理磁盘。宿主后台只处理超过 24 小时、最多 1000 个 `.part`，不碰正式文件、raw 或报告。

# 验收与命令

运行 `.venv/Scripts/python.exe -m pytest -q tests/test_file_management_service.py tests/test_file_management_page.py`，在 `apps/web` 运行 FileManagement 定向 Vitest；涉及桌面动作再运行 Electron 对应契约测试。最后执行 `git diff --check`。

# 常见失败与报告

常见失败：把端口可达当 SFTP 成功、确认后丢失下载意图、重复启用、请求线程递归删 `.part`、终态历史挤掉活动任务、WinSCP/日志泄露密码。报告连接阶段、Profile/确认、队列/清理边界、修改文件、数据库/磁盘影响、测试和真实设备限制；同步 `docs/device-files/`、Job Center、README 与 CHANGELOG。
