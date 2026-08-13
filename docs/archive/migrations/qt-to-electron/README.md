# Qt → Electron 历史归档

## 定位

Qt/Web 双轨与 Qt → Electron 对等迁移已经结束。本目录只记录历史事实，不构成活动架构、依赖、启动入口或待恢复产品计划。当前事实来源依次为生产代码、测试、[冻结迁移矩阵](MIGRATION_MATRIX.md)、[当前架构](../../../ARCHITECTURE.md)和 Feature Registry。

固定决策是：唯一正式 GUI 为 Electron Desktop，Vue/Vite 只承担唯一 Renderer 的开发与构建，Renderer 通过 REST/WebSocket 使用永久 Python Backend；Agent、Syslog、Ground、Remote MR 和设备采集不是 standalone Browser 产品。迁移没有改变业务 DataRoot、数据库 schema 或领域数据契约，也不保留旧 Qt/Browser Feature alias 作为回退入口。

## 冻结证据

- `2d0bdbd5`：删除 `src/netconsole/ui/` 的受跟踪 Qt 页面、对话框、Worker、控件和资源。
- `59fb5908`：删除旧 Qt Shell、探测和兼容启动入口。
- `eb3660fc`、`3be31b13`：移除 Qt 运行依赖并建立无 Qt Backend 发布链。
- `cb33be2c`：删除 Qt 环境测试，保留永久业务层覆盖。

旧文档原文继续由 Git 历史保留。例如：

```powershell
git show 2d0bdbd5^:docs/02-architecture.md
git show 2d0bdbd5^:docs/WEB_MIGRATION_PLAN.md
git show 2d0bdbd5^:docs/development/qt-electron-parity-matrix.md
```

旧兼容指针已经删除。历史内容通过上述 Git 命令读取；当前文档不得重新引用这些路径。

## 固定结论

- Electron Main/Preload + Vue 是唯一正式桌面界面；FastAPI/Python Core 是永久业务层。
- Browser 模式只用于本机开发、诊断和 API 联调。
- Qt/PySide6/QFluentWidgets 不得重新进入源码、依赖、测试环境或发布包。
- SNMP Center、通用 MIB/OID 平台和无线勘测属于批准删除项；设备管理只保留 SNMP v1/v2c 基础识别，网络工具无线扫描是独立能力。
- 自动测试不等于 Electron 人工或真实设备验收；未完成项继续在最终矩阵中标记。
