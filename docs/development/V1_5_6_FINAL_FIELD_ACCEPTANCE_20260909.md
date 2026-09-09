# NetConsole v1.5.6 最终交付现场验收

验收日期：2026-09-09（Asia/Shanghai）

本报告承接 [主线收口验收报告](./V1_5_6_MAIN_CONSOLIDATION_ACCEPTANCE_20260909.md)，范围为 Windows GUI、Windows Server、升级/卸载、真实开发数据兼容和真实设备 E3。此阶段不重新合并分支、不步进版本、不移动 `v1.5.6` tag，也不以 GitHub Actions 状态作为验收门。

## 基线与完整性

| 项目 | 事实 |
| --- | --- |
| 本地 main | `6ce04fcc7b4ded972f4ee48f783aa0df28836287`，仅比产品树多验收文档 |
| v1.5.6 产品 commit | `ebcd35356a136bddd016de399b89bb2c49fac6ef` |
| `v1.5.6^{}` | `ebcd35356a136bddd016de399b89bb2c49fac6ef`，tag 未移动 |
| 版本身份 | `version.py=v1.5.6`、Electron=`1.5.6`、ProductName=`NetConsole v1.5.6 by wxj` |
| Full SHA256 | `4fb80b4591965a490549fad033bebb98b4772f1f055790688131f4d67f630e34` |
| Customer SHA256 | `94e5971e6f69b279c6031269f5d1f428e53ec67dc3893babb8a0bb7b1ffd5d3b` |
| package metadata | `ProductVersion=1.5.6`、`FileVersion=1.5.6.0`、`packaged_dirty=false`、`package_smoke=PASS`、`published=false` |
| PACKAGE_INTEGRITY | `PASS`；本轮重新计算 SHA256 并与两个 `.release.json`、`SHA256SUMS.txt` 一致 |

制品目录：`D:\study\NetConsole-Workspace\release\v1.5.6\build-0-ebcd3535`。

本机只读环境证据：当前用户 `ROG-MB9\18358`，`IS_ADMIN=False`；操作系统为 Windows 11 专业工作站版，build `26200`，不是 Windows Server 2012。现有 v1.5.5 Full/Customer 包位于 `release\v1.5.5\build-0-cbfffa29`，其清单和 SHA256 已复核，可作为后续升级输入，但本轮未启动安装器。

## A. Full Fresh Install

`FULL_FRESH_INSTALL = PENDING_ADMIN_ISOLATED_ENVIRONMENT`

没有执行 per-machine NSIS 安装。当前会话无管理员权限，且已有 `D:\Program Files\NetConsole` 的 v1.5.5 注册安装；为避免覆盖既有安装或改变 HKLM/DataRoot，本轮未发起 UAC、未写入注册表、未创建正式 DataRoot。包内 PyInstaller/NSIS/7-Zip/package smoke 已在产品树上通过，但不等同真实安装。

## B. Customer Fresh Install

`CUSTOMER_FRESH_INSTALL = PENDING_ADMIN_ISOLATED_ENVIRONMENT`

未覆盖 Full 环境，也未执行 Customer NSIS 安装。Customer 身份、feature profile 和 payload 已由 release manifest/package smoke 验证；真实安装仍需独立管理员隔离环境。

## C. GUI

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| `FULL_GUI` | `PENDING_NOT_INSTALLED` | 未执行真实 Full 安装和首次启动；package smoke PASS 不能替代 GUI |
| `CUSTOMER_GUI` | `PENDING_NOT_INSTALLED` | 未执行真实 Customer 安装和首次启动 |
| `EDITION_ISOLATION` | `PENDING_NOT_INSTALLED` | 未在两个独立 DataRoot/安装环境启动验证 |
| 空数据 empty state | `PASS_AUTOMATED_ONLY` | Main contract、Renderer/Electron 回归覆盖；非真实安装 GUI 结论 |

真实 GUI 入口、Backend 启动、Renderer 无白屏、模块导航、任务通知、Save As、External Terminal、SSH Relay、Feature Registry、Ground、现场诊断包和轨旁 AP 页面均等待安装后人工检查。

## D. Upgrade 1.5.5 to 1.5.6

`UPGRADE_1_5_5_TO_1_5_6 = PENDING_ADMIN_ISOLATED_ENVIRONMENT`

可信 v1.5.5 Full/Customer 制品和 manifest 存在，但没有在隔离环境安装 v1.5.5、建立 fixture、再运行 v1.5.6 安装器。数据库 migration、DataRoot、局点、设备、任务/History、Settings、Feature Profile、快捷方式和版本号均未被冒充为升级 PASS。

## E. Reinstall

`REINSTALL = PENDING_ADMIN_ISOLATED_ENVIRONMENT`

未执行已有独立 DataRoot 的重新安装；因此未对数据库、局点、设备、历史、凭据或设置做写入性验证。

## F. Uninstall

`UNINSTALL_APPLICATION = PENDING_ADMIN_ISOLATED_ENVIRONMENT`

未执行 Full 或 Customer 的正式卸载。

## G. User Data Preservation

`UNINSTALL_USER_DATA_PRESERVED = PENDING_ADMIN_ISOLATED_ENVIRONMENT`

本轮没有删除、重建、清空或 repair 任何用户 DataRoot；生产 `D:\NetConsoleData` 和开发真实数据均未触碰。由于没有执行卸载，不能把保留结果写成 PASS。

## H. Real Development Data Compatibility

`DEV_REAL_DATA_COMPATIBILITY = PENDING_EXPLICIT_CONTROLLED_SESSION`

本轮没有获得明确的真实开发数据受控启动授权，未读取或启动 `D:\NetConsoleData-dev`。后续若授权，只能先做只读/备份能力检查、SQLite quick_check 和 DataRoot authority 检查，再启动 v1.5.6；禁止自动 repair、migration hack、vacuum、清空或删除。

## I. Windows Server

当前主机不是 Windows Server，未发现可用 Server 2012/2012 R2 隔离环境；本阶段不伪造 Server 结论。

| 项目 | 状态 |
| --- | --- |
| `SERVER_2012_INSTALL` | `PENDING_NO_ENVIRONMENT` |
| `SERVER_2012_GUI` | `PENDING_NO_ENVIRONMENT` |
| `SERVER_2012_RESTART` | `PENDING_NO_ENVIRONMENT` |
| `SERVER_2012_UNINSTALL` | `PENDING_NO_ENVIRONMENT` |
| `V1_5_6_SERVER_ACCEPTANCE` | `PENDING` |

待具备准确 OS build 的 Server 2012/2012 R2 环境后，按 fresh install、启动、Backend lifecycle、Renderer、导航、重启和卸载顺序执行，并检查 WebView/Electron、VC runtime、权限、HKLM DataRoot、长路径、中文路径、防火墙与内置组件。

## J. Real Device E3

历史 E3 事实不变：`PHASE2D_E3_STATUS=FAIL`、`REAL_DEVICE_CONNECTION_ATTEMPTED=YES`、`FIRST_COMPARABLE_CYCLE=NOT_STARTED`、`PRODUCTION_ACTIVATION_EXECUTED=NO`、`PRODUCTION_CUTOVER_EXECUTED=NO`，根因类别为 `E3_HARNESS_BUG`。

本轮先使用项目正式 `.venv` 执行离线契约：

```text
.\.venv\Scripts\python.exe -m pytest tests/test_e3_ssh_connection_path.py -q
exit=0
3 passed in 0.15s
```

| 项目 | 状态 |
| --- | --- |
| `E3_TARGET` | `DEVICE-NB10-C7-01`（历史目标，需现场重新确认范围） |
| `E3_PREFLIGHT` | `PASS`（正式 runtime、共享连接路径和 mock-only contract） |
| `E3_REAL_CONNECTION_ALLOWED` | `NO`，缺少本轮新的维护窗口/现场网络批准 |
| `E3_CONNECTION` | `NOT RUN`（真实设备） |
| `E3_CYCLE_1` | `NOT RUN` |
| `E3_CYCLE_2` | `NOT RUN` |
| `E3_CYCLE_3` | `NOT RUN` |
| `E3_FINAL` | `PENDING_MAINTENANCE_WINDOW` |
| `DEVICE_CONFIG_CHANGED` | `NO` |
| `PRODUCTION_ACTIVATION` | `NOT RUN` |
| `V1_5_6_REAL_DEVICE_ACCEPTANCE` | `PENDING` |

获得新维护窗口后，只允许使用正式 credential resolver、target selection、prepared target、Netmiko 参数构造、`ConnectHandler` 和 Command Guard 执行 H3C/Comware 7/interface.discovery 只读三轮；首轮失败必须停止，不得暴力重试。

## K. Final Release State

| 项目 | 状态 |
| --- | --- |
| `PACKAGE_INTEGRITY` | `PASS` |
| `VERSION_IDENTITY` | `PASS` |
| `DATA_ROOT_SAFETY` | `PASS`；本轮未写入 Production/Development Real Data |
| `V1_5_6_SOFTWARE_ACCEPTANCE` | `PASS` |
| `V1_5_6_INSTALL_ACCEPTANCE` | `PENDING` |
| `V1_5_6_SERVER_ACCEPTANCE` | `PENDING` |
| `V1_5_6_REAL_DEVICE_ACCEPTANCE` | `PENDING` |
| `V1_5_6_FINAL_DELIVERY_ACCEPTANCE` | `PENDING` |

## Blockers And Defects

### Blockers

- 当前会话 `IS_ADMIN=False`，没有管理员隔离 Windows 环境，无法安全执行 per-machine Full/Customer 安装、GUI、升级、重装和卸载。
- 当前主机为 Windows 11 Workstation，没有 Windows Server 2012/2012 R2 验收环境。
- 没有本轮新的真实设备维护窗口、现场网络和目标范围确认，不能连接 `DEVICE-NB10-C7-01` 执行 E3。
- 没有明确的 `D:\NetConsoleData-dev` 受控启动授权，因此真实开发数据兼容验收保持 pending。

### Non-blocking defects

本轮只读完整性、离线契约和环境检查未发现新的产品缺陷；人工验收未执行不构成 defect 结论。

### Fixes

本轮没有修改产品代码、版本、tag 或安装包；只新增本报告。既有主线收口和软件自动化修复详见主线收口报告。

## Final Freeze

### 后续平台范围备注（2026-09-10）

本报告中的 Windows Server 2012/2012 R2 `PENDING` 保留为当时现场事实。后续正式平台范围已调整为 Windows 10、Windows 11 和 Windows Server 2016；Server 2012/2012 R2 不再属于后续开发、测试、安装验收或发布目标。用户已确认 Windows Server 2016 环境运行正常。

- `main` 当前为 `6ce04fcc7b4ded972f4ee48f783aa0df28836287`，工作树保持 clean，只有本报告新增待提交文档。
- 产品 commit 和 `v1.5.6` tag 保持 `ebcd35356a136bddd016de399b89bb2c49fac6ef`，不移动、不重打。
- Full/Customer 包保持原 SHA256、`published=false` 和 `packaged_dirty=false`；不因人工环境缺失重打包。
- 本阶段结论是 `V1_5_6_SOFTWARE_ACCEPTANCE = PASS`，不是完整交付 PASS；最终交付必须等待安装、Server 和真实设备门禁。
