# 全局数据根

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

优先级为：显式 `NETCONSOLE_DATA_ROOT`、Electron 已持久化 bootstrap、Windows 默认 `D:\NetConsoleData`。候选根必须是绝对路径、可写、非系统盘、不在 AppData/Temp/仓库/安装目录内；不满足时直接失败，绝不新建 C 盘、用户目录或源码目录的回退数据。

自动化测试必须以 `RuntimeMode.TEST` 显式设置 `NETCONSOLE_DATA_ROOT=D:\NetConsoleTestData\<run-id>`。未设置、直接使用测试根、或位于该根以外都会失败；测试结束仅清理自己的 `run-id`。源码开发默认仍使用正式根，只有开发者明确传入该测试根时才会进入隔离测试模式。

Electron 在 `app.whenReady()` 前将 `userData`、`sessionData`、`cache`、`logs`、`crashDumps` 与 `temp` 全部重定向到 `runtime/`。同一根的主 Backend 使用 `runtime/locks/netconsole-backend.lock` 排他运行；锁记录 PID、启动时间、版本、可执行文件和数据根。仍存活的持锁进程不会被删除锁文件，陈旧锁由文件锁机制安全回收。

`config/storage-manifest.json` 记录 schema 版本、最低应用版本、最近打开版本和最近迁移。遇到更高 schema 或版本不兼容时 Backend 停止启动；不可逆迁移必须先生成完整备份，并在开发版获得明确确认后才能执行。普通查询、界面调整和只读分析不会触发迁移。

旧数据迁移使用 `scripts/maintenance/migrate_unified_data_root.py`：复制过程使用 staging、SHA-256 和 SQLite `quick_check`/`integrity_check`，同路径异内容保留到 `migrations/conflicts/`，原目录在核验完成前绝不删除。迁移报告与已中断 staging 的回收记录都保存在 `migrations/`。
