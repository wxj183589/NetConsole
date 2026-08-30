# 全局数据根

## 安装器选择与机器级指针

Windows 的 electron-builder NSIS 向导先选择程序安装位置，再显示“选择 NetConsole 数据存放位置”页面。该页面说明数据库、MR/MESH 原始日志、采集文件、报告和备份会持续增长，默认只接受非系统本地固定磁盘；它检查目录可写、可重命名、SQLite 写锁、至少 10 GB 可用空间，并推荐 100 GB 以上。

安装器先规范化路径并在零写入状态下识别目录状态：不存在、空目录、合法旧数据根以及含普通文件的目录都允许继续，普通文件会原样保留。只有 NetConsole 必需路径 `config/`、`sites/`、`runtime/`、`agents/`、`migrations/`、`staging/` 或 `config/storage-manifest.json` 已被错误类型文件/符号链接占用，才按真实路径冲突停止。随后执行可写与重命名探测；探测成功后不得再按“目录非空”拒绝。探测只在候选根内部创建带唯一后缀的 `.netconsole-install-probe-*.tmp`，写入固定短内容、刷新并关闭句柄后，在同一目录重命名为 `.tmp.renamed`，回读内容并删除本轮探测文件。探测不使用安装器 `%TEMP%`、不跨卷移动、不重命名数据根、也不读取或覆盖现有数据库和采集文件。失败提示记录具体步骤和 Win32 错误码，并区分目录创建/写入、权限、占用、文件系统重命名能力、回读和清理；已有数据根中的历史探测残留不得导致新探测名称冲突。

安装器在发布机器级指针前调用打包 Backend 完成候选根校验，并在空根中原子创建完整目录结构和 `config/storage-manifest.json`；已有 manifest 只做兼容性校验，损坏、根不一致或版本不兼容时安装失败且原文件不被覆盖。校验和初始化全部成功后，唯一持久化路径指针才写入 `HKLM\Software\NetConsole\DataRoot`。manifest 记录 `format_version`、`data_root`、`created_at`、`last_opened_at`、`installation_id`、schema 和迁移兼容字段。运行时优先使用显式 `NETCONSOLE_DATA_ROOT`，否则读取该机器级指针；未配置时停止启动，绝不回退 LocalAppData、用户目录、安装目录、仓库或 C 盘。

空目录直接初始化为新数据根；已有 manifest 或 `config/` + `sites/` 的合法根会原样复用；含无冲突普通文件的目录在保留原文件的同时创建 NetConsole 必需结构。安装器不会自动拼接 `NetConsoleData` 子目录，也不会删除、改名或覆盖用户已有文件。枚举会输出实际条目并跳过 `.`、`..` 和旧 v1.4.3 固定名称探测残留，便于诊断 Windows 空目录或历史探测状态。升级/修复默认继续使用已登记根；选择不同根时，打包后的 Backend 在更新注册表前执行 sibling staging、SQLite 校验和原子发布，旧根保持不删除。普通卸载保留数据根及其机器级指针。

`app_root` 是程序和只读资源位置，`data_root` 是唯一的业务数据位置，`site_root` 是 `<data_root>/sites/<site_id>`。路径事实源是 `src/netconsole/core/paths.py`，运行时不得从当前工作目录、源码目录、安装目录、用户目录、LocalAppData 或系统 Temp 推导数据根。

当前机器的开发、Electron 开发、Python Backend、打包验证和正式安装包均使用：

```text
D:\NetConsoleData
```

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

优先级为：显式 `NETCONSOLE_DATA_ROOT`、安装器写入的 `HKLM\Software\NetConsole\DataRoot`。Electron bootstrap 只保存局点/界面上下文，不是数据根事实源；未配置机器级根时直接失败。候选根必须是绝对路径、可写、非系统本地固定盘、不在 AppData/Temp/仓库/安装目录内；不满足时直接失败，绝不新建 C 盘、用户目录或源码目录的回退数据。

自动化测试必须以 `RuntimeMode.TEST` 显式设置 `NETCONSOLE_DATA_ROOT=D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>`。未设置、直接使用测试根、或位于该根以外都会失败；测试结束仅清理自己的 `run-id`。源码开发默认仍使用正式根，只有开发者明确传入该测试根时才会进入隔离测试模式。

Electron 在 `app.whenReady()` 前将 `userData`、`sessionData`、`cache`、`logs`、`crashDumps` 与 `temp` 全部重定向到 `runtime/`。同一根的主 Backend 使用 `runtime/locks/netconsole-backend.lock` 排他运行；锁记录 PID、启动时间、版本、可执行文件和数据根。仍存活的持锁进程不会被删除锁文件，陈旧锁由文件锁机制安全回收。

`config/storage-manifest.json` 记录 `format_version`、`data_root`、`installation_id`、创建/最近打开时间、schema 版本、最低应用版本、最近打开版本和最近迁移。遇到更高 schema、根不一致或版本不兼容时 Backend 停止启动；不可逆迁移必须先生成完整备份，并在开发版获得明确确认后才能执行。普通查询、界面调整和只读分析不会触发迁移。

旧数据迁移使用 `scripts/maintenance/migrate_unified_data_root.py`：复制过程使用 staging、SHA-256 和 SQLite `quick_check`/`integrity_check`，同路径异内容保留到 `migrations/conflicts/`，原目录在核验完成前绝不删除。迁移报告与已中断 staging 的回收记录都保存在 `migrations/`。
