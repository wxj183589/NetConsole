# Electron Preload

本目录是 Renderer 与 Electron Main 之间的最小安全桥接层，只暴露已登记、已校验的 Native Bridge 动作，不传递任意 Node 能力。

入口为 `index.ts` 与 `bridge.ts`；契约由 `src/shared` 和对应测试约束。修改后执行 Preload/IPC 测试，检查白名单和敏感数据不外泄。
