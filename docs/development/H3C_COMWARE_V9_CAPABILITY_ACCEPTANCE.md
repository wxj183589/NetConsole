# H3C Comware V9 Capability 真实设备验收

日期：2026-09-13

## 目标设备

- 站点：`hzl10 / 杭州地铁10号线`
- 设备：`251-无线控制器-主`
- 地址：`10.92.250.251`
- 型号：`WX3540X`
- 厂商/平台：`H3C / Comware`

## 版本事实

真实 SSH 只读探测 `display version` 成功，解析为：

- software version：`9.1.081`
- software release：`R1615P01`
- major：`V9`
- role：`wireless_controller`
- capability：`h3c_comware_v9_wireless_controller`

版本探测在 AC、FIT-AP 和设备详情命令计划之前执行；探测失败或 major 不确定时不默认 V7。

## 真实只读采集

- AC：17 个命令全部成功，AC 摘要更新成功。
- FIT-AP 资源：870 条更新成功。
- FIT-AP verbose：870 条详情更新成功，失败 0。
- BSSID：572 条解析成功。
- LLDP：572 条 AC 侧记录解析成功；设备详情 LLDP 邻居 12 条更新成功。
- 连接记录：587 条更新成功。
- 设备详情：12 个命令全部成功；接口 63、光模块 20、LLDP 邻居 12。

## API / GUI 边界

使用真实采集后的数据执行只读 API 查询：

- `/api/ac-management/summary`：HTTP 200，AP 总数 870。
- `/api/ac-management/aps`：HTTP 200，总数 870。
- `/api/device-management/devices/{device_uuid}`：HTTP 200，返回 fact、interfaces、optical_modules、lldp_neighbors 等详情结构。

GUI 前端构建和 Electron 宿主门禁均通过；本次未执行需要设备写权限的 GUI 动作。

## 自动化门禁

- 定向 H3C/AC/设备详情回归：PASS
- Python full：`4858 passed, 2 skipped`
- Renderer：`1300 passed`，typecheck/build PASS
- Electron：`298 passed`，typecheck/build PASS
- Architecture：`12/12 passed`

## 安全边界

- `PRODUCTION_MANUAL_MUTATION=NO`
- `DEVICE_CONFIG_MUTATION=NO`
- 未执行 SFTP enable、AP console enable、配置保存或手工 SQL。
- Production rollback/storage registry baseline failure 为 `OUT_OF_SCOPE`，本功能不修改、不吸收。

## 状态

`READY_FOR_RELEASE`

## FINAL REAL ACCEPTANCE (2026-09-13)

本节绑定当前主线 `cdd9eb53e3dbb398739879c18bb25c737ced34d1`，正式安装包构建标识为
`v1.5.7+cdd9eb53`。本轮未修改产品代码；仅通过正式 NetConsole 流程完成只读设备采集、GUI 查看/刷新和正常重启，并保留证据：
`diagnostic/h3c-hangzhou10-real-device-20260913-final/`。

| 项目 | 结果 |
| --- | --- |
| CODE_SHA | `cdd9eb53e3dbb398739879c18bb25c737ced34d1` |
| SITE | `hzl10 / 杭州地铁10号线` |
| DEVICE / DEVICE_IP | `251-无线控制器-主 / 10.92.250.251` |
| MODEL | `WX3540X` |
| SOFTWARE_VERSION / SOFTWARE_RELEASE | `9.1.081 / R1615P01` |
| REAL_DETECTED_MAJOR | `V9` |
| CAPABILITY | `h3c_comware_v9_wireless_controller` |
| SSH / VERSION_BOOTSTRAP | `PASS / PASS` |
| AC_COLLECTION | `PASS`；最新正式运行 `20f87bc7-dde4-473c-a2d1-57012f235580` 成功 |
| AC_COMMANDS_TOTAL / AC_COMMANDS_FAILED_UNEXPECTED | `9 / 0`（最新运行的只读 AC/FIT-AP 命令） |
| DEVICE_DETAIL | `PASS`；12 个正式命令成功 |
| INTERFACE_COUNT / OPTICAL_COUNT | `63 / 20` |
| FIT_AP / FIT_AP_COUNT | `PASS / 870` |
| LLDP_COUNT | `587` 条本次 AC 资源记录；当前 LLDP read model 为 627 行 |
| BSSID_COUNT | `1174` 条非空 radio BSSID（587 个在线 AP、每 AP 2 个 radio） |
| CONNECTION_RECORD_COUNT | `587` 条当前运行记录 |
| AP_IDENTITY | `PASS`；10 条抽样无混用分隔符，见 `AP_IDENTITY_SAMPLE.json` |
| SQLITE_ROW_COMPATIBILITY / DICT_COMPATIBILITY | `PASS / PASS` |
| DEVICE_VENDOR / DEVICE_PLATFORM_FACTS / SOFTWARE_RELEASE_DTO | `H3C / PASS / PASS` |
| HTTP_API | `PASS`；正式 GUI 会话和只读契约返回 2xx；无会话探测 401 为预期保护 |
| GUI_AC_MANAGEMENT / GUI_AC_DETAIL | `PASS / PASS` |
| GUI_FIT_AP / GUI_DEVICE_DETAIL / GUI_REFRESH | `PASS / PASS / PASS` |
| RESTART_PERSISTENCE | `PASS`；软件重启后 backend、renderer、tray 均恢复 `hzl10` |
| UNEXPECTED_BACKEND_ERRORS | `0`；启动早期空白 renderer/tray refresh 诊断在 backend ready 后恢复，非产品错误 |
| V7_REGRESSION | `PASS`；现有 V7/V9 H3C 自动化包含在定向回归中 |
| PRODUCTION_MANUAL_MUTATION / DEVICE_CONFIG_MUTATION | `NO / NO` |
| CODE_CHANGED | `NO` |
| REAL_DEVICE_ACCEPTANCE | `PASS` |
| CODE_STATUS | `READY_FOR_RELEASE` |

补充：Device Detail collector 成功日志报告 LLDP 12 条；重启后正式 GUI/Query Service 读取当前快照为 13 条。该差异来自当前快照与 collector 汇总口径，不产生错误或 500，已在证据中保留。Production rollback/storage registry、Task Lifecycle 及相关维护门禁仍为 `OUT_OF_SCOPE`，本功能未修改。

### 本次只读命令矩阵

AC/FIT-AP 最新正式运行的 9 个命令全部 `PASS`：

`screen-length disable`、`display wlan ap all`、`display wlan ap all address`、`display wlan ap all radio`、`display wlan ap all radio verbose filter bbssid`、`display wlan ap all connection-record`、`display wlan ap all radio type`、`display wlan ap unauthenticated`、`display wlan ap all lldp`。

Device Detail 正式运行的 12 个命令全部 `PASS`；包括版本 bootstrap、系统名称、设备信息、设备厂商信息、启动文件、接口、光模块、LLDP 列表及 LLDP 详情。全程未执行配置模式、save/write、undo、reset、reboot、shutdown、SFTP enable 或手工 SQL。
