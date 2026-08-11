# Web 平台适配

本目录抽象 Browser 诊断运行时与 Electron Desktop 适配器的差异，统一提供受控复制、运行时状态和宿主能力。它不能暴露任意 Electron 或系统命令。

主要入口为 `browser-adapter.ts`、`electron-adapter.ts`、`runtime.ts` 和 `types.ts`；修改 Bridge 契约时同步 Electron shared/preload 测试。
