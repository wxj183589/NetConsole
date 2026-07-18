# Electron 共享契约

本目录定义 Main、Preload 与 Web 共同使用的 Bridge DTO、输入校验和类型边界。它不访问文件、数据库、设备或 Electron 运行时对象。

主要入口为 `bridge.ts` 与 `validation.ts`；变更必须同步 IPC、Preload 和 Web 适配器测试，并保持错误信息与白名单语义一致。
