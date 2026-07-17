# 文件管理 Qt → Electron 对等规格

## 事实来源与边界

- Qt 页面：`src/netconsole/ui/pages/file_management_page.py`
- SFTP、下载校验与 `.part`：`src/netconsole/services/file_transfer_service.py`
- MESH 归档/导入：`src/netconsole/services/mesh_storage_service.py`、`src/netconsole/services/mesh_import_service.py`
- 永久用例：`src/netconsole/services/file_management_service.py`
- API/DTO：`src/netconsole/backend/api/file_management_router.py`、`src/netconsole/models/api/file_management.py`
- Electron Renderer：`apps/web/src/views/file-management/FileManagementView.vue`
- 自动证据：`tests/test_file_management_service.py`、`tests/test_file_transfer_service.py`、`apps/web/src/views/file-management/*test.ts`

永久调用链为 `Electron → Vue → FastAPI → FileManagementApplicationService → Repository/FileTransferService`。设备侧仍是只读文件管理；Qt 明确拒绝的上传、删除、重命名和远程建目录没有迁移。设备文件下载结果使用 `fd1_*`，不登记或伪装成 Artifact。

## Qt 入口与 Electron 闭环

| Qt 有效入口/行为 | Electron 入口 | Service/API 与持久状态 | 当前判定 |
| --- | --- | --- | --- |
| 分组、设备/IP/站点/类型搜索与设备选择 | 顶部搜索、分组和设备选择 | `/devices` 从设备主库读取分组、类型和地址；Vue 组合筛选 | `IMPLEMENTED_UNVERIFIED` |
| 选择设备后进入该设备默认下载目录 | 设备变化自动刷新左栏 | `device_file_download_dir(site, safe_device_name)`，目录只返回 `fl1_*`；上级仍可回到 Qt 同等的局点下载根 | `IMPLEMENTED_UNVERIFIED` |
| 本地目录进入、返回、刷新、500 条分页 | 左栏双击目录、返回、根目录、刷新、分页 | `/local/entries`；根边界固定为局点下载根；拒绝 symlink、`.part` 和越界引用 | `IMPLEMENTED_UNVERIFIED` |
| 本地新建目录 | 左栏“新建目录” | `/local/directories`；`web.file_management_local_write`；使用 Windows 安全目录名 | `IMPLEMENTED_UNVERIFIED` |
| 本地打开文件/当前目录 | 双击文件；“打开当前目录” | 文件通过受控 HTTP/Bridge 保存后打开；原目录使用 60 秒、一次性 `fda1_*`，由 Electron main 调固定回环端点消费 | `IMPLEMENTED_UNVERIFIED` |
| SFTP 连接/断开；必要时启用 H3C SFTP | “连接 SFTP”“断开”；显式写入确认复选框和确认框 | `/connections`；默认只读连接，只有 `allow_sftp_setup=true` 才允许 Qt 同等配置命令 | `REAL_DEVICE_PENDING` |
| 主机密钥和跳板连接 | 连接动作 | Electron 路径强制 system `known_hosts` + RejectPolicy；跳板与目标分别校验，目标经 tunnel socket 仍按原主机名查 key | `REAL_DEVICE_PENDING` |
| 远程根目录、上级、刷新、目录进入、500 条分页 | 右栏根目录/上级/刷新/双击目录/分页 | 会话内随机 `fe1_*`；服务端保存路径并限制 remote root；断开后引用失效 | `REAL_DEVICE_PENDING` |
| 文件双击选择、全选、清空、Mesh 日志快捷选择 | 右栏双击文件、全选文件、清除选择、Mesh 日志 | Vue 只提交当前会话 entry id，不提交远程路径 | `IMPLEMENTED_UNVERIFIED` |
| 多选下载批次、重复活动任务跳过、单任务串行队列 | “下载选中”与队列表 | `/downloads/batch`；同设备/远程路径活动任务去重；模块调度器一次只派发一个 File Job | `IMPLEMENTED_UNVERIFIED` |
| 进度、已下载字节、平均速度、成功/失败/取消 | 下载队列表 | 读取 TaskSnapshot 的 progress/current/total/time；无 Renderer 临时成功状态 | `IMPLEMENTED_UNVERIFIED` |
| 取消排队或运行任务 | 每行“取消” | 排队任务直接写 TaskApplicationService cancelled 事件；运行任务走 LocalProcessAdapter 协作取消/强停 | `IMPLEMENTED_UNVERIFIED` |
| 失败/取消重试 | 每行“重试” | 恢复描述用 Windows DPAPI 封装后写现有 `tasks.db` 事件；不建第二套任务库 | `IMPLEMENTED_UNVERIFIED` |
| 清理完成/失败记录 | “清理完成”“清理失败” | 只追加模块隐藏事件，不删除 Task/日志/结果；不把 cancelled 混入失败清理 | `IMPLEMENTED_UNVERIFIED` |
| 重启恢复、遗留 `.part` 清理 | 页面启动自动恢复 | TaskRepository 为唯一事实源；旧活动进程由 TaskApplicationService 对账；只清理下载根和 MESH 根内 `.part` | `IMPLEMENTED_UNVERIFIED` |

下载队列线程由 FastAPI lifespan 显式启动和关闭，Service 构造阶段不创建后台线程；退出时先等待队列完全停止，再关闭共用的 `LocalProcessAdapter`，避免分派中的任务与 Worker 宿主关闭竞态，也避免测试或临时 Service 实例遗留 SQLite 访问。
| 普通设备按当前左栏目录下载 | 选择左栏目录后批量下载 | 目标在 `file_downloads_root` 内，冲突自动改名并在排队期预留 | `IMPLEMENTED_UNVERIFIED` |
| 车载 MR 的 Mesh 日志命名、MR raw 目标及自动导入 | Mesh 日志快捷选择和队列结果 | `meshlog.log`/历史文件沿用 Qt 命名；目标为 MR raw；同一 File Job 调用 MeshImportService 并交付导入/重复/失败状态 | 自动契约已测；真实日志 `REAL_DEVICE_PENDING` |
| 下载结果打开、打开所在目录 | 队列“保存”“打开”“所在目录” | 通过受控下载桥交付并使用本轮 capability；原后端结果目录也可用一次性 `fda1_*` 打开 | `IMPLEMENTED_UNVERIFIED` |
| WinSCP | 顶部 WinSCP（独立 Feature） | 60 秒、一次性、强类型动作经 Electron main 固定端点执行；不提供任意程序或参数；Electron 启动参数不含密码，由 WinSCP 安全提示登录 | `IMPLEMENTED_UNVERIFIED / MANUAL_DESKTOP_PENDING` |

## Feature Registry

- `web.file_management`：页面。
- `web.file_management_download`：下载与结果交付。
- `web.file_management_local_write`：本地新建目录。
- `web.file_management_remote`：设备 SFTP 浏览/下载，保持 `DEVELOPMENT`，源码 profile 默认开放，真实设备验收前状态仍为未验证。
- `web.file_management_desktop_actions`：原目录/WinSCP 一次性动作，保持 `DEVELOPMENT`，源码 profile 默认开放；Server/Browser 模式执行时仍被拒绝。
- `file.mesh_log_download`、`file.mesh_auto_import`、`file.external_winscp`：保留 Qt Feature 事实源；自动导入开关由组合根传入永久 Service。

## Native Bridge 与验收边界

Native Bridge 已增加 `executeFileDesktopAction(action_ref)`：main 只接受 `fda1_*`，只调用固定回环端点，Python Service 原子消费后仅可打开受控根内目录或启动固定 WinSCP。Bridge 不接受 Renderer 路径、程序、argv、URL、host、username 或 password；WinSCP Electron 启动参数不含密码，日志只记录动作结果代码。

以下验收仍未执行，因此页面状态保持 `IMPLEMENTED_UNVERIFIED`，Qt 不可隐藏：

1. 真实 H3C/HH3C 设备 known_hosts 首次登记、key 不匹配、直连/跳板、SFTP 已启用/未启用流程。
2. 大文件进度、速度、取消、网络中断、设备重启、远端文件仍在写入、磁盘满和 Electron 重启恢复。
3. 真实 MR 活动/历史 meshlog 命名、raw 目录、自动导入、重复导入和解析失败。
4. 原本地目录、结果目录、保存副本和 WinSCP 的 Electron 人工验收。
