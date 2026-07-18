# Electron Main

## 用途

本目录承载 Electron 窗口、受管 Python Backend 生命周期、下载、单实例和安全 IPC。

## 边界

Main 不执行设备命令、数据库查询、Parser、报告或业务状态机；Renderer 只能调用白名单 IPC，不能传任意路径、程序或窗口参数。

## 主要入口

- `index.ts`：应用与窗口生命周期。
- `backend-manager.ts`：受管 Backend 启停和健康检查。
- `ipc.ts`、`security.ts`：白名单 IPC 和发信方校验。
- `config.ts`：开发/生产配置与加载期背景色镜像。

## 依赖关系

Main 依赖 `../shared/` 的强类型 DTO，与 Vue 仅通过 preload bridge 通信；Python Core 由受管进程提供 FastAPI，不导入 Node 业务实现。

## 数据与状态

临时会话令牌只存在于进程和受控临时通道，不写日志、URL、SQLite 或仓库。主题持久化属于 Python/FastAPI 系统设置。

## 测试

主题和安全边界由 `../../tests/config.test.ts`、`ipc.test.ts`、`preload.test.ts` 覆盖；修改 Main 后还需运行 Electron typecheck、测试和 main/preload 构建。

## 修改规则

BrowserWindow 使用安全浅色作为初始背景。Renderer 只可报告解析后的 `light`/`dark`；Main 拒绝 `auto`、强调色、任意颜色或附加窗口参数，并只更新发信窗口。Web 颜色事实源始终位于 `apps/web/src/theme/`。

## 生成与清理

构建输出位于被忽略的 `dist/`；关闭应用必须清理受管 Backend、下载和子窗口，不在本目录生成运行数据。

## 相关文档

- [Electron Desktop](../../../../docs/ELECTRON_DESKTOP.md)
- [Native Bridge](../../../../docs/DESKTOP_NATIVE_BRIDGE.md)
