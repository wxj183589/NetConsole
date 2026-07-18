# NetConsole 永久架构与后续演进

## 已确定且不得回退的基线

- Electron Main/Preload + Vue Renderer 是唯一正式桌面界面。
- FastAPI/Python Core 是永久业务层，Repository、Parser、Job Center、Export Process 和 Agent 不迁入 Node 或 Vue。
- Browser 只用于本机开发、诊断和 API 联调。
- Qt/PySide6/QFluentWidgets 不得重新进入源码、依赖、测试环境或发布包。
- SNMP Center、通用 MIB/OID 平台和无线勘测不再迁移；设备管理只保留 SNMP v1/v2c。

这组目标已经成为当前架构，不再是“未来 Qt 替换方案”。历史阶段见[Qt → Electron 归档](archive/migrations/qt-to-electron/README.md)，当前事实见[当前架构](ARCHITECTURE.md)和[最终迁移矩阵](architecture/MIGRATION_MATRIX.md)。

## 后续演进顺序

1. 以生产代码和真实设备行为补齐 `PARTIAL/IMPLEMENTED_UNVERIFIED/REAL_DEVICE_PENDING` 模块，不恢复旧桌面入口。
2. 继续把 `legacy_tasks.py` 中仍有生产调用的领域实现下沉到明确 Service/handler。
3. 扩展版本化网络设备 Command Profile；未经 fixture/真实设备证据的厂商和版本必须失败关闭。
4. 完成 Electron 托盘、签名、升级和安装包发布门，不扩大 Native Bridge 白名单。
5. 运行完整架构 Guard、全量 Python/Vue/Electron/Agent 测试和真实制品 smoke。
6. 人工桌面与真实设备验收通过后，才提升对应功能状态。

## 完成标准

- Vue、Electron 和 Router 不承载核心业务算法或直接设备/数据库访问。
- Application Service 不反向依赖 UI/HTTP/IPC。
- Repository 独占活动数据库访问；数据路径全部通过 PathResolver/领域路径服务。
- 生产命令进入版本化 Command Profile 或有明确、限期的迁移记录。
- 每个已删除 Qt 路径在最终迁移矩阵中具有分类、新位置、测试和删除依据。
- P0/P1 架构问题清零；延期 P2 具有责任域、原因、边界和复验条件。
