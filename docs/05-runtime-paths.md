# Runtime Paths

`src/netconsole/core/paths.py` 的 `PathResolver` 是运行路径事实来源。源码、资源和版本化配置仍由仓库定位，但所有运行数据与源码目录解耦。

本机开发和正式运行共用：

```text
D:\NetConsoleData
├─ config/
├─ sites/
├─ runtime/
│  ├─ electron/
│  ├─ logs/
│  ├─ cache/
│  └─ temp/
├─ agents/
├─ migrations/
└─ staging/
```

`PathResolver.app_root` 与 `data_root` 已解耦：传入源码或安装根不会把运行数据写回同一目录。测试必须设置 `RuntimeMode.TEST` 和 `NETCONSOLE_DATA_ROOT=D:\NetConsoleTestData\<run-id>`；未显式设置时直接失败。打包程序与 `pnpm dev` 都使用同一持久根，不依赖当前工作目录、LocalAppData 或用户目录。

仓库 `.local/{data,runtime}` 和根 `data/` 是历史迁移源，不再是活动目录。迁移使用 `scripts/maintenance/migrate_unified_data_root.py` 的 staging、SHA-256、SQLite 校验和冲突保留；来源在核验前不得删除。

源码和工具路径：

- `src/netconsole/`：可安装的 Python 包；
- `apps/agent/`、`apps/desktop_electron/`、`apps/desktop_renderer/`：独立应用；
- `config/`：版本化配置模板；
- `resources/`：版本化静态资源；
- `scripts/build/`、`scripts/dev/`、`scripts/maintenance/`：工程脚本；
- `dist/`：构建输出，必须被忽略；
- `tests/`：测试和脱敏样本。

路径构造必须通过 `PathResolver`、资源 helper 或脚本自身定位的项目根完成，禁止用 `Path.cwd()` 推导源码、资源、配置、数据库或运行数据路径。
