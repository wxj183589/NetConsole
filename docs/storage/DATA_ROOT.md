# 全局数据根

## 安装器选择与机器级指针

Windows 的 electron-builder NSIS 向导先选择程序安装位置，再显示“选择 NetConsole 数据存放位置”页面。该页面说明数据库、MR/MESH 原始日志、采集文件、报告和备份会持续增长，默认优先推荐非系统本地固定磁盘；C 盘和其他具有有效读写权限的本地路径始终合法。它检查目录可写、可重命名、SQLite 写锁、文件系统兼容性和可用空间，并推荐 100 GB 以上。

安装器先规范化路径并在零写入状态下识别目录状态：不存在、空目录、合法旧数据根以及含普通文件的目录都允许继续，普通文件会原样保留。只有 NetConsole 必需路径 `config/`、`sites/`、`runtime/`、`agents/`、`migrations/`、`staging/` 或 `config/storage-manifest.json` 已被错误类型文件/符号链接占用，才按真实路径冲突停止。随后执行可写与重命名探测；探测成功后不得再按“目录非空”拒绝。探测只在候选根内部创建带唯一后缀的 `.netconsole-install-probe-*.tmp`，写入固定短内容、刷新并关闭句柄后，在同一目录重命名为 `.tmp.renamed`，回读内容并删除本轮探测文件。探测不使用安装器 `%TEMP%`、不跨卷移动、不重命名数据根、也不读取或覆盖现有数据库和采集文件。失败提示记录具体步骤和 Win32 错误码，并区分目录创建/写入、权限、占用、文件系统重命名能力、回读和清理；已有数据根中的历史探测残留不得导致新探测名称冲突。

安装器在发布机器级指针前调用打包 Backend 完成候选根校验，并在真正空根中原子创建完整目录结构、`config/storage-manifest.json`、一个已登记但不含示例设备的空局点及 `application.json`；该首启初始化幂等且失败会回滚已创建的局点/配置。已有 manifest 只做兼容性校验，损坏、根不一致或版本不兼容时安装失败且原文件不被覆盖。校验和初始化全部成功后，唯一持久化路径指针才写入机器级注册表。manifest 记录 `format_version`、`data_root`、`created_at`、`last_opened_at`、`installation_id`、schema 和迁移兼容字段。运行时优先使用显式 `NETCONSOLE_DATA_ROOT`，否则读取该机器级指针；便携版使用程序目录旁的 `portable-data-root.json` 和程序目录下的 `data` 默认根；未配置时停止启动，不会静默切换到其他空根。首次初始化优先选择可用的非系统固定磁盘，若不存在则推荐 C 盘下的 `C:\ProgramData\NetConsole\Data`，不会因为位于 C 盘而拒绝。

空目录直接初始化为新数据根；已有 manifest 或 `config/` + `sites/` 的合法根会原样复用；含无冲突普通文件的目录在保留原文件的同时创建 NetConsole 必需结构。安装器不会自动拼接 `NetConsoleData` 子目录，也不会删除、改名或覆盖用户已有文件。枚举会输出实际条目并跳过 `.`、`..` 和旧 v1.4.3 固定名称探测残留，便于诊断 Windows 空目录或历史探测状态。升级/修复默认继续使用已登记根；选择不同根时，打包后的 Backend 在更新注册表前执行 sibling staging、SQLite 校验和原子发布，旧根保持不删除。普通卸载保留数据根及其机器级指针。

`app_root` 是程序和只读资源位置，`data_root` 是唯一的业务数据位置，`site_root` 是 `<data_root>/sites/<site_id>`。路径事实源是 `src/netconsole/core/paths.py`，运行时不得从当前工作目录、源码目录、安装目录或系统 Temp 推导数据根；用户明确选择的 C 盘或其他本地路径可以作为数据根。

正式安装包和安装态使用机器级正式数据根；源码/Electron 的真实开发验收使用独立的长期开发数据 Authority：

```text
PRODUCTION_DATA = D:\NetConsoleData
DEV_REAL_DATA = D:\NetConsoleData-dev
```

`D:\NetConsoleData-dev` 不是 fixture、备份或临时复制品。不得把它全量复制到仓库 `.local`、diagnostic、acceptance、validation、test-data、worktree 或 tmp。自动化测试使用单独的 `<repository-parent>\test-data\NetConsole\<run-id>`，不得读取上述两个真实数据根。

根目录布局固定为：

```text
D:\NetConsoleData
├─ config/                 # 应用配置、局点 Registry、storage-manifest.json
├─ sites/                  # 每个局点的数据库、raw、解析结果和业务文件
├─ runtime/
│  ├─ electron/            # userData、session、cache、crash dumps
│  ├─ logs/                # Backend/Electron 日志
│  ├─ temp/                # 受控临时运行文件
│  └─ locks/               # netconsole-backend.lock
├─ agents/                 # 独立 Agent 配置、任务、日志和采集包
├─ migrations/             # 迁移报告、备份和冲突保留材料
└─ staging/                # 可恢复的受控迁移暂存
```

优先级为：显式 `NETCONSOLE_DATA_ROOT`、便携版程序目录旁的配置文件、安装器写入的机器级 DataRoot 指针。Electron bootstrap 只保存局点/界面上下文，不是数据根事实源。候选根必须是绝对路径、可写、可被 SQLite 访问且不在 Temp、仓库或程序安装目录内；系统盘、用户自定义 C 盘目录和非系统盘均可用。网络盘、可移动盘和临时介质会显示稳定性风险提示，只有磁盘不可访问、权限不足、文件系统不兼容或空间不足时才阻止继续。便携版默认的程序目录下 `data` 是唯一例外，并由便携标记明确选择。

## 磁盘选择策略

- 默认优先 `D:\NetConsoleData` 或其他可用的非系统固定磁盘；不存在可用非系统盘时推荐 `C:\ProgramData\NetConsole\Data`。
- C 盘始终是合法的数据根位置。界面提示“建议将 NetConsole 业务数据存放在非系统盘，以降低系统重装或系统盘空间不足造成的数据风险。继续使用 C 盘不会影响软件正常运行。”，但不阻止继续。
- 目录验证显示当前路径、所在磁盘、磁盘类型、总空间、剩余空间、推荐位置和风险提示，并执行读写、同目录重命名、SQLite 写锁及文件系统兼容性检查。
- 空间不足只提示并允许用户改选其他位置；程序升级、卸载、Portable 目录删除和迁移失败都不得清空历史数据或静默切换到空白 DataRoot。

自动化测试必须以 `RuntimeMode.TEST` 显式设置 `NETCONSOLE_DATA_ROOT=<repository-parent>/test-data/NetConsole/<run-id>`。未设置、直接使用测试根、或位于该根以外都会失败；测试结束仅清理自己的 `run-id`。源码真实开发验收由调用方显式选择 `D:\NetConsoleData-dev`，不得用测试根替代长期开发 Authority。

Electron 在 `app.whenReady()` 前将 `userData`、`sessionData`、`cache`、`logs`、`crashDumps` 与 `temp` 全部重定向到 `runtime/`。同一根的主 Backend 使用 `runtime/locks/netconsole-backend.lock` 排他运行；锁记录 PID、启动时间、版本、可执行文件和数据根。仍存活的持锁进程不会被删除锁文件，陈旧锁由文件锁机制安全回收。

## 免安装版数据根

免安装包通过程序实际目录下的 `portable.mode` 标记进入便携模式，路径不依赖当前工作目录：

- 默认模式使用 `<免安装程序目录>\data`。首次启动只创建必要目录、统一 Schema 的空数据库和无示例设备的 `default` 局点，不创建 Demo 局点、设备或模拟数据。
- 自定义模式在程序目录旁保存 `portable-data-root.json`，其中只记录用户明确选择的绝对路径。后续启动优先恢复该路径；配置损坏、目录不可用或无权限时直接报错，不创建替代数据库，也不静默迁移旧数据。
- 修改数据根不会覆盖、删除或自动合并旧根。旧根保持原样，只有用户明确执行迁移操作时才进入既有迁移流程。
- 便携版程序文件夹可以整体移动；未设置自定义根时，随文件夹移动的 `data` 仍是唯一默认根。安装版和免安装版使用同一 `config/`、`sites/`、`runtime/` 布局及 Schema。
- 便携目录不可写时提示用户选择其他合法目录；取消选择即退出。C 盘是合法选择，但安装器和界面优先提示非系统盘。
- 同一数据根由 Backend 的 `runtime/locks/netconsole-backend.lock` 排他保护，禁止不同程序实例并行写入。

普通 Production 桌面启动以 `config/site_registry.json`、`config/application.json`（兼容 legacy `config/app.json`）和已存在的 `sites/<目录>/db/devices.db` 为事实源，不使用 Production 维护命令的静态 Allowlist。缺少 bootstrap 时，单一有效 Registry 记录可受控恢复；多个局点没有唯一引用、Registry 损坏、路径越界/Reparse Point、数据库缺失或损坏时 fail-closed，并返回 `ACTIVE_SITE_*` 诊断码。维护命令的 Allowlist、能力令牌和目标校验仍只约束高风险 Production 维护操作。

`config/storage-manifest.json` 记录 `format_version`、`data_root`、`installation_id`、创建/最近打开时间、schema 版本、最低应用版本、最近打开版本和最近迁移。遇到更高 schema、根不一致或版本不兼容时 Backend 停止启动；不可逆迁移必须先生成完整备份，并在开发版获得明确确认后才能执行。普通查询、界面调整和只读分析不会触发迁移。

旧数据迁移使用 `scripts/maintenance/migrate_unified_data_root.py`：复制过程使用 staging、SHA-256 和 SQLite `quick_check`/`integrity_check`，同路径异内容保留到 `migrations/conflicts/`，原目录在核验完成前绝不删除。迁移报告与已中断 staging 的回收记录都保存在 `migrations/`。
