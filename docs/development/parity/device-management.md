# 设备管理 Qt → Electron 对等规格

## 当前结论

设备管理已形成真实的 `Vue → FastAPI → DeviceManagementWebService → Repository/Job/Export/Desktop Adapter` 纵向链路。本分支完成第一批写入与导入安全收口，但统一任务窗口的取消、Artifact 授权和重启恢复改动仍由 `codex/electron-task-center-window@fe2c54e8` 单写，尚未进入本分支，因此当前状态为 `PARTIAL / BLOCKED_ON_TASK_WINDOW`，不是 `COMPLETE`。

普通浏览器不再是正式产品入口。本页仍可在源码开发服务器中联调真实 API（包括受控写操作），但不形成独立页面、业务分支、发布包或验收链；外部终端、原生文件选择和受管下载只以 Electron Desktop 为正式行为基准。

## Qt 事实来源

| 范围 | 类/文件 | 事实 |
| --- | --- | --- |
| 主页面 | `DeviceManagementPage`，`src/netconsole/ui/pages/device_management_page.py` | 筛选、动作条、表格、分页、CRUD、分组、连接测试、采集、导入导出、终端。 |
| 表格 | `DeviceTable`，`src/netconsole/ui/widgets/device_table.py` | 当前页勾选、表头全选、反选、双击详情、右键菜单和复制动作。 |
| 新增/编辑 | `DeviceDialog`，`src/netconsole/ui/dialogs/device_dialog.py` | 基础、SSH/Telnet、双跳板、SNMP v2c/v3 等完整字段。 |
| 详情 | `DeviceDetailDialog`，`src/netconsole/ui/dialogs/device_detail_dialog.py` | 概览、接口、光模块、LLDP、轨旁 AP 业务、详情刷新、光模块刷新和历史。 |
| 分组 | `DeviceGroupDialog` | 新建、重命名、删除、批量设置分组。 |
| 终端 | `ExternalTerminalSettingsDialog`、`services/external_terminal.py` | SecureCRT/Xshell/PuTTY 配置、单台/批量启动、可选传递密码。 |
| 批量任务 | `BatchConnectionTestWorker`、`BatchCollectWorker` 及进度 Dialog | 并发、进度、部分成功、失败和取消。 |
| 导入导出 | `DeviceImportExportService`、Export Process、`OmniPeekExportDialog` | CSV 导入/导出/模板、SecureCRT 会话、OmniPeek 预览选择及 `.nam`。 |

Qt 截图必须由人工在同一测试数据和窗口尺寸下采集。当前执行环境不能把自动启动探针当作人工截图证据，因此本文不伪造截图；截图和逐项差异记录列入末尾验收清单。

## 页面结构和操作对照

### 筛选、表格与选择

- 筛选：关键词、厂商、设备类型、分组；Electron 额外提供连接状态、排序字段和升降序，不改变 Qt 语义。
- Qt 表格列：选择、名称、分组、系统名、站点、主地址、备用地址、协议、更新时间。
- Electron 保留上述列并显示厂商/类型和最近连接状态；额外列不能替代 Qt 列。
- 选择行为：表头全选当前页、逐行多选、清空、反选；翻页后按当前页数据重新同步。
- 行为：双击/详情入口、编辑、删除；右键包含详情、复制设备、外部终端、编辑、删除、复制当前单元格/名称/主地址/备用地址/系统名/站点/整行/设备信息。

### 页面动作

| Qt 动作 | Electron 入口 | 真实行为 |
| --- | --- | --- |
| 新增设备 | `新建设备` | 写入现有设备数据库；返回不含凭据。 |
| 编辑设备 | 行按钮、右键、详情 | 真实校验并保存；秘密字段支持保持、替换、显式清除三态，保存后同步刷新列表和详情，响应不回显秘密。 |
| 复制设备 | 顶部或右键 | 从现有记录复制并生成新设备 UUID。 |
| 单个/批量删除 | 行按钮、顶部按钮、右键 | 二次确认后由服务端签发短时确认 token，再执行真实删除。 |
| 分组管理/设置分组 | `分组管理`、`设置分组` | 复用现有 Device Group Repository；显示部分失败。 |
| 测试连接 | SSH/Telnet/SNMP | 进入 Job Center，调用正式连接/探测服务；支持轮询、恢复和取消。 |
| 批量测试连接 | `批量测试连接` | 每台设备、每个启用协议建立任务；提交前完成目标与协议校验。 |
| 批量更新详情 | `批量更新详情` | 调用正式 H3C 详情采集，保存事实、接口、光模块和 LLDP。 |
| 诊断下载 | `诊断下载` | 调用正式 DiagnosticDownloadService，任务化执行并返回受控 Artifact。 |
| 详情/历史 | 详情 Drawer 和五个 Tab | 读取现有 DeviceFactRepository；接口/光模块/LLDP 支持真实历史分页。 |
| 刷新详情/光模块 | 详情内按钮 | 分别调用正式详情采集和 `refresh_h3c_device_optical`。 |
| 外部终端 | 顶部配置、详情、右键 | 仅 Electron Desktop；服务端从设备 ID 和白名单配置构造参数，本机 Adapter 以 `shell=False` 启动。 |
| CSV 导入 | `CSV 导入` | 上传到受控 staging，预览错误行与已有主地址重复行；确认时显式选择拒绝、跳过或仍新增，随后执行 SHA-256 校验、确认 token、备份、单事务导入和审计。 |
| CSV 导出 | `不含凭据` 或明确的 `含凭据` | Export Process 生成实际文件；含凭据需要额外警告确认。 |
| 模板导出 | 导出菜单 | Export Process 生成实际模板 CSV。 |
| SecureCRT | 导出菜单 | 可选上传 Qt 同类 `.ini` 模板；Export Process 生成会话树并压缩为受控 ZIP，再由 Electron 选择保存位置。 |
| OmniPeek | 预览 Dialog | 后台收集预览，选择/排除/异常强制确认后由 Export Process 生成 `.nam`。 |

## Qt 有效入口逐项矩阵

| Qt 事实入口 | Electron 实际闭环 | 当前判定 |
| --- | --- | --- |
| 关键词、厂商、类型、分组筛选；刷新 | 同字段查询真实 Repository；提供 loading/error/success/empty 状态 | 已实现，待人工对照 |
| `DeviceTable` 固定列顺序 | 选择、名称、分组、系统名、站点、主地址、备用地址、登录协议、更新时间保持同序；附加状态/操作列位于其后 | 已实现，待人工对照 |
| 当前页表头全选、逐行多选、清空、反选 | Element Plus 选择列和显式清空/反选；翻页后重置选择 | 已实现，待人工对照 |
| 设备列表分页 | Repository 计数、排序和服务端分页；20/50/100/200 页大小 | 已实现，待人工对照 |
| 双击详情、详情按钮 | 双击行、行按钮和右键菜单均读取真实详情 DTO | 已实现，待人工对照 |
| 右键详情、复制、外部终端、编辑、删除 | 对应真实入口齐全；复制当前单元格/名称/主备地址/系统名/站点/整行/设备信息使用系统剪贴板 | 已实现，待人工对照 |
| 新增、编辑、复制 | 真实 Repository 写入；表单校验失败返回 422 并显示错误，成功刷新列表/详情；复制生成新 UUID | 已实现，待人工对照 |
| 秘密字段编辑 | 保持/替换/显式清除三态；DTO 严格白名单；API/日志/任务不回显 | 已实现，待人工对照 |
| `DeviceDialog` 测试连接 | Electron 对已保存设备提供 SSH/Telnet/SNMP 真实任务；尚未支持使用未保存表单及秘密测试 | 缺口，需一次性秘密注入契约 |
| 单删、批删及取消 | 二次确认后签发绑定设备集合的短期一次性 token；取消不写库 | 已实现，待人工对照 |
| 分组新增、重命名、删除、批量设置/清空 | 真实 Device Group Repository；删除后设备回到未分组 | 已实现，待人工对照 |
| 单台/批量连接测试 | 正式 SSH/Telnet/SNMP worker、持久 Task、超时/失败/取消；真实设备待验收 | `REAL_DEVICE_PENDING` 前置未满足 |
| 批量更新详情 | 正式 H3C 采集并持久化事实、接口、光模块、LLDP；部分失败进入 Task | `REAL_DEVICE_PENDING` 前置未满足 |
| 详情概览、接口、光模块、LLDP、轨旁 AP 业务 | 五个真实数据 Tab；空数据和加载/失败状态齐全 | 已实现，待人工对照 |
| 接口/光模块/LLDP 历史分页 | 真实历史 API，支持页码和 20/50/100/200 页大小 | 已实现，待人工对照 |
| 刷新详情、刷新光模块、AC Web | 正式后台任务；HTTPS URL 只通过 Electron 白名单外链动作 | 已实现，真实设备待验收 |
| 诊断下载 | 正式诊断服务、持久 Task、受控 ZIP Artifact、取消/失败清理 | 已实现，真实设备待验收 |
| CSV 导入 | 受控上传、预览错误/重复行、拒绝/跳过/仍新增、确认/取消、备份、单事务、审计和重启清理 | 已实现，待人工对照 |
| CSV（含/不含凭据）与模板导出 | 独立 Export Process 生成真实 CSV Artifact；敏感导出二次确认 | 已实现，待人工对照 |
| SecureCRT 会话导出 | 内置或受控 `.ini` 模板生成真实 ZIP Artifact；敏感模板成功/失败均清理 | 已实现，待人工对照 |
| OmniPeek 预览/选择/强制异常项/导出 | 后台真实预览与 `.nam` Artifact；异常项需显式强制 | 已实现，待人工对照 |
| SecureCRT/Xshell/PuTTY 配置和单/批量启动 | 严格终端类型、设备 ID、可执行文件名白名单；`shell=False`；超过 20 台需一次性 token | 已实现，真实本机软件待验收 |
| 进度、停止、失败和重启恢复 | 后端 Task/导入审计持久；设备页仅保留当前会话轮询，不再自建浏览器任务存储 | `BLOCKED_ON_TASK_WINDOW` |

Qt 的窗口置顶、窗口几何和 Qt 专属子窗口生命周期属于外壳行为，不复制为第二套 Vue 业务状态；Electron 对应能力由正式桌面壳统一承担。采集日志的持久查看、统一停止和 Artifact 一次性授权也归统一任务窗口，设备页不再复制一套。

## 字段和凭据规则

新增/编辑覆盖 Qt `DeviceDialog` 的有效字段：名称、系统名、站点、厂商、类型、分组、主/备地址、备注；SSH/Telnet 开关、端口、用户名、密码；两级跳板机的主机、端口、用户名、密码；SNMP 开关、端口、v2c 读写团体字、v3 用户名/安全级别/认证与加密协议及密码、Context、超时和重试。MAC、位置和 HTTPS 端口只按现有数据库/详情事实显示，不冒充 Qt 编辑字段。

安全边界：

- 详情 DTO 不返回密码、团体字和 SNMPv3 密钥，只返回 `*_secret_configured` 布尔状态。
- 编辑时空 secret 表示保留旧值；输入新值表示替换；只有 `clear_secret_fields` 白名单可显式清除，替换与清除同一字段会被拒绝。
- API、任务消息、审计和终端返回不记录凭据或完整命令参数。
- 普通 CSV 默认不含凭据；只有明确选择“含凭据”并二次确认时才导出。
- Renderer 不能传任意可执行文件、命令或输出路径；终端路径必须由 Electron 原生选择器取得，并由后端验证为存在的 `SecureCRT.exe`、`Xshell.exe` 或 `putty.exe`。

## 永久调用链

```text
DeviceManagementView.vue
  → deviceManagement.ts
  → device_management_router.py
  → DeviceManagementWebService
  ├─ DeviceRepository / DeviceGroupRepository / DeviceFactRepository
  ├─ TaskApplicationService / LocalProcessAdapter / Job Center handlers
  ├─ Export Process
  └─ DesktopActionService → LocalDesktopAdapter
```

FastAPI Router 只负责 DTO、Feature Gate、Service 调用和错误映射；Vue 不操作数据库、不拼设备命令；Electron main/preload 不实现设备业务。

## API 对照

| 能力 | API |
| --- | --- |
| 列表/详情/历史 | `GET /api/device-management/devices`、`GET /devices/{uuid}`、`GET /devices/{uuid}/history` |
| CRUD/复制/删除 | `POST /devices`、`PUT /devices/{uuid}`、`POST /devices/{uuid}/duplicate`、`POST /devices/delete-confirmation`、`POST /devices/batch-delete` |
| 分组 | `GET/POST /groups`、`PATCH/DELETE /groups/{id}`、`POST /groups/assign` |
| 连接/采集/诊断 | `POST /devices/{uuid}/connection-tests`、`POST /devices/batch-connection-tests`、`POST /devices/batch-refresh-details`、`POST /devices/{uuid}/refresh-optical`、`POST /diagnostic-download` |
| 导入 | `POST /imports/preview`、`POST /imports/confirm` |
| 导出 | `POST /exports/csv`、`/template`、`/securecrt`、`/securecrt-with-template`、`/omnipeek-preview`、`/omnipeek`；`GET /exports/{task}` 和受控下载 |
| 任务 | `GET /tasks/{task}`、`POST /tasks/{task}/cancel` |
| 外部终端 | `GET/PUT /external-terminal/settings`、`POST /external-terminal/confirmation`、`POST /external-terminal/launch`、`POST /devices/{uuid}/external-terminal` |

设备 HTTPS 管理页由详情 DTO 返回无凭据 URL，再通过 Electron `openExternalUrl` 白名单桥交给系统浏览器；该桥拒绝 HTTP、含用户名/密码的 URL 和 Renderer 任意导航。

批量打开超过 20 台设备的外部终端必须先取得与局点、设备集合和终端类型绑定的一次性确认 token。SecureCRT 用户模板是敏感暂存文件：成功任务必须完成严格清理，否则任务失败；服务重启时再次回收残留模板。

## Feature Registry

页面和动作继续由以下 Feature 控制：`web.device_management`、`web.device_connection_test`、`web.device_management_write`、`web.device_management_collect`、`web.device_management_import`、`web.device_management_export`、`web.device_management_desktop`。

这些功能在客户包中可见并默认启用；`web.device_management_desktop` 的具体按钮还必须满足 Electron host 检查。Feature Gate 不再用来掩盖 Qt 已有能力。

## 自动化证据

- `tests/test_device_management_web_api.py`：真实临时 SQLite、CRUD、筛选排序分页、分组、删除 token、凭据边界、连接/采集/光模块/诊断任务、导入预览确认、CSV/SecureCRT/OmniPeek Artifact、终端白名单和任务隔离。
- `tests/test_desktop_action_service.py`：动态登记终端动作、审计字段和命令解释器拒绝。
- `tests/test_web_architecture.py`：Desktop 使用非 Qt `LocalDesktopAdapter`，Server 不具备本机动作。
- `apps/web/src/views/devices/DeviceManagementView.test.ts`：页面状态、筛选、详情 Tab、选择、真实 CRUD、凭据三态、当前会话任务轮询、受控下载、终端和 OmniPeek 预览入口。
- `apps/web/src/navigation/registry.test.ts`、`tests/test_web_parity_foundation.py`：导航归属和迁移状态枚举。

自动测试使用真实临时数据库、真实 FastAPI/Application Service 和可控连接/桌面适配器；不把生产设备凭据或正式 `.local/data` 带入测试。

## 人工 Qt/Electron 对照清单

人工验收必须在相同局点数据库副本上分别启动 Qt 和 Electron，并逐项记录截图、成功/失败行为和数据库变化：

1. 筛选、排序、分页、当前页全选、清空和反选。
2. 新增、编辑、秘密保持/替换/清除、复制、单删、批量删除及取消确认。
3. 分组新增、重命名、删除、未分组和批量设置。
4. 右键菜单与全部复制动作。
5. SSH、Telnet、SNMP 单测和批量测试的成功、超时、取消及恢复。
6. 批量详情采集、光模块刷新、部分失败、取消和重开页面恢复。
7. 五个详情 Tab、历史分页及无数据/错误状态。
8. CSV 导入预览、错误文件、重复拒绝/跳过/仍新增、取消、确认、持久化和重启后数据。
9. CSV 不含/含凭据、模板、SecureCRT ZIP、OmniPeek 预览选择和 `.nam` 内容。
10. SecureCRT/Xshell/PuTTY 配置、选择取消、单台/批量启动及超过 20 台确认。
11. Electron 退出后 Python/任务/临时文件清理；Qt 仍可独立启动和回退。
12. 日志、API 响应、任务消息和导出默认路径中无意外凭据泄露。

## 未完成验收

- 统一任务窗口：`BLOCKED_ON_TASK_WINDOW`。本分支已删除设备页面 `sessionStorage` 任务系统；待集成 `codex/electron-task-center-window@fe2c54e8` 后，设备任务必须消费统一任务列表、取消和 Artifact 一次性授权契约，冲突解决时保留本分支的页面存储删除结果。
- Qt `DeviceDialog` 的“测试连接”可使用尚未保存的表单和凭据；当前 Electron 只对已持久化设备提供 SSH/Telnet/SNMP 真实任务测试。若不新增持久化秘密副本，需要共享任务执行层提供不落 Task 参数/日志的一次性秘密注入契约；在此之前不得标记完整对等。
- 人工 Qt/Electron 对照：`NOT_STARTED`，不能由自动化代替。
- 真实设备：SSH/Telnet/SNMP、H3C 详情、光模块和诊断下载待现场设备验证。
- SecureCRT/Xshell/PuTTY：需要用户本机实际安装路径与交互验证。
- 截图：待人工验收时存入版本化文档资产目录，再在本文登记；临时剪贴板路径不得写入仓库。

共享依赖与表单测试缺口补齐并完成人工软件流程后，若只剩现场设备，状态才可升级为 `REAL_DEVICE_PENDING`；所有必需现场项通过后才能升级为 `COMPLETE`。
