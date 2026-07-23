# Electron-only 重构任务板

当前 E10B 基线：`main@ee7381ea`；本地已完成侧栏临时修复、导航历史字段迁移、MESH 元数据分层和命令文档稳定路径提交，未推送。

## 当前阶段

- `E10B` 正在并行实施，六个单写者任务分别负责架构 Guard、设备详情后端、设备详情前端、统一主题、Online MR Parser/SQLite 边界和目录 README 门禁。
- 已完成本地提交：`3958cd14`、`b45098b7`、`8897dfc`、`cf27d6d`；最终集成前不推送。
- 当前共享工作树存在各 Worker 的未提交代码是预期状态；每个 Worker 禁止 Git 提交，由指挥中心复核后精确暂存。
- 设备详情、主题和 E10B 自动化不等于 Electron 人工视觉或真实设备验收，后两项继续保持待验收。

- `E0`：建立 Qt 运行时、页面、测试、依赖、构建和混合业务覆盖地图。
- `E1`：在迁移必要业务断言后彻底移除 Qt；`E1` 完成前不修改数据根或启动性能。
- 三个只读审计已完成并归档：Qt 依赖地图、旧数据分类、启动/打包链；报告保留供 E1-E6 实施复核。
- `data/` 与 `.local/` 在完成分类、staging、哈希/SQLite 校验和 manifest 前禁止删除。
- 两个历史 stash 保留，不 restore、不 drop、不混入本任务。
- 开发态保留 Codex/浏览器/Playwright 可观察入口，但 Vite/FastAPI 默认仅绑定 `127.0.0.1`，继续使用短期令牌；生产包不含 Vite、开发状态接口或鉴权绕过。
- PyCharm/源码启动门已完成：`7319697` 使无参数 `main.py` 使用项目本地 Electron 运行时进入唯一开发编排链，不依赖全局 `pnpm`，真实冒烟退出后无 5173、Electron、Vite 或受管 Python 残留。
- 永久层 Qt 图像依赖已收口：`7d9f382d` 将热力图 Job/Export 迁到 Pillow，`7e3b0b3` 同步架构与 E1 归档；`src/netconsole/ui/` 之外已无直接 PySide6/qfluentwidgets 导入。
- SNMP Center、通用 MIB/OID 平台和无线勘测活动代码已由 `cbf8e358` 删除；设备管理仅保留 SNMP v1/v2c。
- Qt 最终残留、开发/API 安全边界、统一网络设备命令平台三个只读审计均已完成、采纳并归档；当前没有后台任务占用额度。
- 开发/API 审计的生产安全 P0 已由 `ec59b5b` 落地：生产 Backend 不注册 OpenAPI 文档路由，生产 BrowserWindow 关闭 DevTools，任务窗口统一开发态判定。
- 下一实施波次按独立提交处理 Python 依赖分层/干净无 Qt 构建/许可证 SBOM、命令平台首个只读 Operation Profile，以及 `dev:codex` 与 E2E 契约。
- Python 依赖/发布合规任务 `019f7468-67ba-7653-9e9a-8b6c70a2a8c5` 与命令 Profile 任务 `019f7469-2641-71c0-b543-2b1df69e7fa6` 均已实体化运行。第二项首次读取短暂失败后延迟实体化，主线程检测到文件变化即停止同域写入并恢复单写者。

## 阶段门

1. E0 必须完成 Qt 依赖地图并区分纯 UI、Adapter、混合业务覆盖。
2. E1 删除 Qt 前必须迁移仍有价值的业务断言；不得用删除测试掩盖回归。
3. E2 完成唯一 Electron Desktop 启动、构建和发布链后，形成独立本地 Qt 移除提交。
4. Qt 移除本地基线提交完成后，才进入 data/.local 路径修复、迁移与性能优化。
5. 数据迁移默认 dry-run；分类、冲突、哈希/SQLite 校验和 manifest 未核对前不得 apply。
6. Electron-only 安装包必须在无系统 Python、无 Qt 环境完成 packaged smoke。
7. 最终全量非 Qt Python、Vue、Electron、Ruff、compileall、pip check 和 diff 门通过后才允许推送。
8. E3 本地基线完成后，先正式删除 SNMP Center 与无线勘测活动代码，再建设统一网络设备命令平台和 API 产品契约；各工作流保持独立提交。
9. “Qt 已移除”必须同时满足源码、测试、依赖、虚拟环境、构建产物和许可证零 Qt；仅删除源码不算完成。
10. E1 完成前审计全部 Python/Node/构建依赖；E2 使用干净、无 Qt Python 环境构建 Backend，并扫描安装包中的 PySide6、Shiboken、Qt DLL/plugins、QFluentWidgets 残留。
11. Qt 依赖清理后重新生成实际随包 Python、Electron/Node 与工具许可证清单；Electron/Chromium notice 必须保留，Qt WebEngine notice 必须移除，未知许可证阻塞发布。
12. 从 E1 起，每阶段更新受影响目录 README；目录结构稳定后在 E8 建立全仓 README 补齐和 `check_directory_readmes.py`，E9 将其纳入最终门。
13. 阶段代码不复制到 `legacy/old/backup`；Git 历史作为代码归档，`docs/archive/migrations/` 只保存已完成事实、迁移清单和验证摘要。
14. 阶段收尾必须精确提交、检查未跟踪数据/构建产物/stash；业务数据未经 manifest、哈希与 SQLite 校验不得删除，现有 stash 未经用户确认不得 apply/drop/pop。
15. E10 独立于零 Qt 扫描：必须使用 Git 历史为每个删除的 Qt 文件分类 `PURE_UI / BUSINESS_MOVED / ADAPTER_REPLACED / DEAD_CODE / FEATURE_REMOVED`，并给出新位置、测试和删除依据。
16. E10 必须检查 Vue、Electron Main/Preload、FastAPI Router、Application Service、Service、Parser、Repository 和 Command Profile 的实际依赖边界；P0/P1 架构问题清零前不得发布。
17. 最终生产设备命令必须由稳定 Operation ID 和版本化 Command Profile 定义；E10 对现存硬编码只做证据驱动分类，命令平台正式建立前不得用宽泛例外掩盖。
18. E10 产出迁移矩阵、有限期架构例外和 `ARCHITECTURE_COMPLIANCE_REPORT.md`；例外必须精确到文件、理由、测试、责任域和到期时间。

## 后续正式工作流

以下任务已确认，当前阶段不得提前实施：

1. **废弃模块删除**：正式删除 SNMP Center 与无线勘测的活动代码、Qt/Web/Electron 入口、测试、依赖、资源和构建接线；保留数据迁移与用户数据安全边界，网络工具无线扫描不属于无线勘测。
2. **统一网络设备命令平台**：以稳定 Operation ID、厂商、设备角色、平台和版本 Profile 统一命令选择、Parser 和 DTO；AC 与车载 MR 仅支持 H3C，交换机当前以 H3C 为主并为 Huawei/ZTE 留出经真实样本验证后的扩展结构；禁止任意命令 API。
3. **正式 API 产品契约**：区分 Desktop Internal、Product、Development 与 Agent API，建立版本、Pydantic DTO、错误码、分页、幂等、Artifact、鉴权、OpenAPI/WebSocket 文档、契约测试和 TypeScript Client；生产 Electron 默认关闭 Swagger UI、仅绑定 loopback 且保持短期令牌认证。

阶段依赖固定为：

```text
E0/E1 去 Qt
    ↓
E2 Electron-only 构建链
    ↓
E3 本地基线提交
    ↓
正式删除 SNMP Center / 无线勘测
    ↓
统一网络设备命令平台
    ↓
正式 API 产品契约
    ↓
E4-E9 数据、性能、数据库、代码、文档与全量验证
    ↓
E10 架构一致性审计与遗留业务逻辑回收
```

## 任务

| 状态 | 任务 | Thread |
| --- | --- | --- |
| COMPLETED / ARCHIVED | Qt 依赖与业务抽离地图 | `019f71d2-14d1-71b2-b957-ad75b90a6cf3` |
| COMPLETED / ARCHIVED | data/.local 分类与迁移设计 | `019f71d2-b427-79a1-976f-51fd18045e07` |
| COMPLETED / ARCHIVED | 启动性能与 Electron-only 打包链 | `019f71d2-cdad-7d41-a482-ccdefd3430bc` |
| COMPLETED | E0 Qt 依赖、入口和混合业务覆盖地图 | 指挥中心 |
| COMPLETED | PyCharm 无参数 `main.py` 启动 Electron | `7319697` |
| COMPLETED | 永久层 Qt 图像依赖清零与阶段归档 | `7d9f382d`、`7e3b0b3` |
| IN_PROGRESS | E1 移除 Qt 运行时、页面、测试和依赖 | 指挥中心 |
| PENDING | E2 Electron-only 构建、启动和发布链 | 指挥中心 |
| PENDING | E2 Python 依赖分层、干净无 Qt venv 与锁定机制 | 指挥中心 |
| PENDING | E2 Electron-only 许可证、SBOM 与安装包 Qt 残留 Guard | 指挥中心 |
| PENDING | E2 本机 `dev:codex`、浏览器 Playwright 与 Electron E2E 契约 | 指挥中心 |
| PENDING | E3 Qt 移除定向验证与本地提交 | 指挥中心 |
| PENDING | E4 数据根、旧数据迁移和测试垃圾清理 | Qt 移除提交之后 |
| PENDING | E5 启动时间线与延迟初始化 | Qt 移除提交之后 |
| PENDING | E6 数据库证据驱动优化 | 性能证据之后 |
| PENDING | E7 代码边界清理 | 前述阶段之后 |
| PENDING | E8 文档统一 | 最终行为稳定之后 |
| PENDING | E8 全仓目录 README、阶段归档与安全清理规范 | 最终目录稳定之后 |
| PENDING | E9 全量非 Qt 验证与后续提交 | 最终组合 |
| PENDING | E9 目录 README、许可证、SBOM、无 Qt 安装包强制门 | 最终组合 |
| PENDING | E10 架构一致性审计与遗留业务逻辑回收 | E9 通过之后、最终发布之前 |
| COMPLETED | 正式删除 SNMP Center、通用 MIB/OID 平台与无线勘测；设备管理仅保留 v1/v2c | `cbf8e358` |
| COMPLETED / ARCHIVED | Qt 依赖、打包和许可证最终残留审计 | `019f7450-95cc-7c61-99d8-c69b0b4ea9c5` |
| COMPLETED / ARCHIVED | 本机开发链与正式 API 安全边界审计 | `019f7451-6407-7d32-b839-05f91c2aa7f8` |
| COMPLETED / ARCHIVED | 统一网络设备命令平台审计 | `019f7451-7cac-7482-9bf4-da765ddc3e9a` |
| PENDING | 统一网络设备命令平台实施 | 审计收口之后 |
| PENDING | 正式 API 产品契约与契约测试 | 命令平台稳定之后 |
| COMPLETED / ARCHIVED | Python依赖分层、无Qt发布Guard与许可证SBOM基础 | `019f7468-67ba-7653-9e9a-8b6c70a2a8c5` |
| COMPLETED / ARCHIVED | `device.inventory.collect`版本化命令Profile | `019f7469-2641-71c0-b543-2b1df69e7fa6` |
| RUNNING | E10B Electron-only 架构 Guard | `019f75f9-c4c0-7ba2-b0ac-87c62ea065f2` |
| RUNNING | 设备详情 Python 契约与查询边界 | `019f75fc-2c7d-7a93-866a-7fed9880e16f` |
| RUNNING | 设备快速详情抽屉与完整详情页 | `019f75fc-4724-7fc3-8e0f-6a1bf50dd6ef` |
| COMPLETED / ARCHIVED | Vue/Electron 全局统一主题（`a91085b`） | `019f75fd-e915-76e0-87ad-141a9f3b7faf` |
| RUNNING | Online MR diagnosis Parser/SQLite 边界整改 | `019f7606-63ba-7db1-b783-56e55a0a8141` |
| RUNNING | 维护目录 README 覆盖门禁 | `019f7608-6147-7bb3-b06b-4ca571c6756e` |
| COMPLETED / ARCHIVED | 轨旁光衰采集 SQLite 边界整改（`777ed481`） | `019f760c-565a-7453-8b0a-bb884b3f28e0` |
