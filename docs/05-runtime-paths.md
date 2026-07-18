# Runtime Paths

`src/netconsole/core/paths.py` 中的 `PathResolver` 是运行路径事实来源。开发态源码、资源和配置定位以仓库根目录为基准，但运行数据不写回源码目录。

Windows 源码开发态默认布局：

```text
%LOCALAPPDATA%/NetConsole/Development/
├─ data/       # SQLite、局点数据、原始采集和正式业务文件
├─ runtime/    # Job、Export、缓存、运行配置和应用日志
│  ├─ logs/
│  └─ cache/
└─ tmp/        # 手工临时样本
```

`PathResolver.app_root` 与 `data_root` 已解耦：传入源码/安装根不会再隐式把运行数据写到同一目录。测试必须通过临时 `NETCONSOLE_DATA_ROOT` 或显式 `PathResolver(app_root=..., data_root=...)` 隔离；打包程序使用 `%LOCALAPPDATA%\NetConsole\`，不依赖当前工作目录。

仓库 `.local/{data,runtime}` 和根 `data/` 是历史数据源，不再是活动运行目录。迁移先运行 `scripts/maintenance/migrate_legacy_runtime_data.py` dry-run，再在确认 manifest 后使用 `--apply --skip-conflicts`；脚本不覆盖目标，SQLite 使用 Backup API 并执行完整性检查。明确测试残留可用 `scripts/maintenance/clean_test_artifacts.py` 先预览再清理。

源码和工具路径：

- `src/netconsole/`：可安装的 Python 包；
- `apps/agent/`、`apps/desktop_electron/`、`apps/web/`：独立应用；
- `config/`：版本化配置模板；
- `resources/`：版本化静态资源；
- `scripts/build/`、`scripts/dev/`、`scripts/maintenance/`：工程脚本；
- `dist/`：构建输出，必须被忽略；
- `tests/`：测试和脱敏样本。

路径构造必须通过 `PathResolver`、资源 helper 或脚本自身定位的项目根完成，禁止用 `Path.cwd()` 推导源码、资源、配置、数据库或运行数据路径。
