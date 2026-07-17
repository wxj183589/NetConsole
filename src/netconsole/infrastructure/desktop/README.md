# Desktop Action 基础设施

## 用途

本目录实现 `netconsole.application.desktop` 定义的桌面动作 Port，用于受控路径打开、登记外部程序启动和无桌面宿主时的稳定拒绝结果。

## 当前实现

- `local_adapter.py`：Python Backend 执行经 Application Service 校验后的 Windows 本机动作，不提供选择器、任意路径、任意命令或任意参数入口。
- `unavailable_adapter.py`：Browser/Server 或缺少桌面宿主时返回稳定拒绝结果。

原 `qt_adapter.py` 没有生产调用者，Electron Main/Preload 已具备正式白名单 Native Bridge，因此在 Electron-only E1 阶段删除。文件选择器、Artifact capability、打开/定位、通知和 Electron IPC 以 `apps/desktop_electron` 及其测试为事实源。

## 边界

本目录只实现 Application Port，不决定业务权限、设备能力、凭据或命令。外部程序必须由 `DesktopActionResolver` 登记并复验可执行文件、参数和受控根；禁止 shell 字符串、命令解释器、Renderer 路径或未知程序启动。

## 数据与安全

不得持久化短期 Token、密码或绝对路径授权。Electron 下载路径 capability 只存在于 Main 进程内存，不由本目录解析。

## 测试

Python 契约与安全拒绝见 `tests/test_desktop_action_service.py`；Electron Main/Preload/IPC 见 `apps/desktop_electron/tests`。

## 相关文档

- [Desktop Native Bridge](../../../../docs/DESKTOP_NATIVE_BRIDGE.md)
- [架构一致性审计](../../../../docs/ARCHITECTURE_COMPLIANCE.md)
