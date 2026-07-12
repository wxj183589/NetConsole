# Runtime Paths

`src/netconsole/core/paths.py` 中的 `PathResolver` 是运行路径事实来源。开发态源码、资源和配置定位以仓库根目录为基准，但运行数据不写回源码目录。

开发态默认布局：

```text
.local/
├─ data/       # SQLite、局点数据、原始采集和正式业务文件
├─ runtime/    # Job、Export、缓存、运行配置和应用日志
│  ├─ logs/
│  └─ cache/
└─ tmp/        # 手工临时样本
```

当前实现中 `PathResolver.data_root` 为 `.local`，因此 `data/` 和 `runtime/` 是其下的持久/临时子目录；测试可以通过显式 `PathResolver(app_root=..., data_root=...)` 隔离。打包程序优先使用 `%LOCALAPPDATA%\NetConsole\`，不依赖当前工作目录。

源码和工具路径：

- `src/netconsole/`：可安装的 Python 包；
- `apps/agent/`、`apps/desktop/`、`apps/web/`：独立应用；
- `config/`：版本化配置模板；
- `resources/`：版本化静态资源；
- `scripts/build/`、`scripts/dev/`、`scripts/maintenance/`：工程脚本；
- `dist/`：构建输出，必须被忽略；
- `tests/`：测试和脱敏样本。

路径构造必须通过 `PathResolver`、资源 helper 或脚本自身定位的项目根完成，禁止用 `Path.cwd()` 推导源码、资源、配置、数据库或运行数据路径。
