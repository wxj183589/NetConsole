# Phase 7 真实只读设备任务验收

2026-11-25 使用当前工作树运行 `scripts/dev/verify_readonly_device_tasks.py`。脚本从环境变量取得实验凭据，调用 `create_app(RuntimeMode.TEST)`，通过 FastAPI 正常接口创建和预览模板、提交任务、读取逐设备结果、提交导出并下载 Artifact。采集与导出均由真实独立 Worker 执行。

只读保存策略收紧后重新运行，隔离根为 `D:\study\NetConsole-Workspace\test-data\NetConsole\phase7-readonly-lab-5597ce3b04`，Site 为 `phase7-lab`。脱敏摘要保存在该根的 `sanitized-result.json`。原始回显、设备数据库和内部运行日志仅保留在隔离根。首次探索验收根 `phase7-readonly-lab-7d56baffe0` 保留为本轮历史证据。

## 版本模板任务 PASS

模板 ID 为 `b57e1c48736048f0b2f453405d697f40`，通过正常保存接口创建 v1，再通过更新接口保存 v2。v2 使用 Jinja2 注释和固定 `display version`，预览摘要在提交时复核。参数化接口查询、条件与循环的保存约束另由定向测试覆盖。

任务 ID 为 `device-task-ce0053b73b9644a5a6eebdc3a08408cd`，状态 `COMPLETED`，业务结果 `SUCCESS`。并发为 3，单条查询超时为 30 秒。

| 设备 | 地址 | 逐设备结果 | 回显字符数 | 耗时 ms |
| --- | --- | --- | --- | --- |
| AC | 192.168.56.2 | success | 763 | 12139 |
| AC2 | 192.168.56.5 | success | 763 | 12152 |
| SW | 192.168.56.3 | success | 761 | 11084 |

模板 ID 与版本 2 已持久化到任务结果。

## LLDP 任务 PASS

任务 ID 为 `device-task-4807d04f5dbd4061a7a1f5b03a2e795b`，目标为 SW `192.168.56.3`，状态 `COMPLETED`，业务结果 `SUCCESS`。串行运行只读 `display lldp neighbor-information list` 与 `display lldp neighbor-information verbose`，解析得到 3 条邻居，耗时 21204ms。

## XLSX 导出 PASS

两个任务均通过 `POST /api/device-operations/tasks/{task_id}/exports` 进入真实 Export Worker，并经 `GET /api/job-center/artifacts/{artifact_id}` 成功下载。

| 来源 | Export Task | Artifact | 字节 |
| --- | --- | --- | --- |
| 版本模板 | device-task-export-dab78c7d530a46ef864258c0b9d344bb | 76ec1a25-f259-4d00-9c06-51ed7b203071 | 7513 |
| LLDP | device-task-export-d04b2ca3bb0741a39009f459181459c5 | 3673c17c-a657-4068-bbed-344d559d8a5c | 6785 |

版本模板导出 SHA-256 为 `0462c8b27d837f2a0da6a33801982bb428dfe91cbe633a56f7ba0fb532cad541`。

LLDP 导出 SHA-256 为 `ba2a324353ccb95d3db52606192395c8b237f353170ab36fc119d7932d310f33`。

## FIT-AP PARTIAL

FIT-AP `192.168.56.4` 的 TCP 23 可建立连接。当前设备任务引擎支持交换机、无线控制器和移动路由器，FIT-AP 角色尚未接入。本轮仅验证 TCP 可达性，登录、命令执行和任务结果验收仍待完成。设备配置写入为零。

## 无线信息收集 PASS

新增类型 `wireless` 在隔离根 `phase7-readonly-lab-6b362c7093` 通过正常 API 和独立 Worker 验收。任务为 `device-task-237f9197cd754074ae99d2556ab5992c`，状态 `COMPLETED`，业务结果 `SUCCESS`。

AC `.2` 与 AC2 `.5` 均执行 `display version`、`display wlan ap all`、`display wlan ap all address` 和 `display wlan ap all radio`。每台解析出 AP、地址、射频三条分类记录，AP 总数 1，在线 1，离线 0，耗时约 42.8 秒。

现场 Alpha 版本行与 Release 版本行不同。采集已使用现有 capability resolver 从实时版本原文识别 Comware major，定向测试包含 Alpha 回显。身份与 Current 的持久化写入保持原服务边界，本任务只保存解析报告。

导出任务为 `device-task-export-7ca7aade6c9d4414aaf0b2752e9faeda`，Artifact 为 `7d39bbd8-c34a-48f1-a5b4-c60ca270b0da`，公开 API 下载 8098 字节，SHA-256 为 `a14e2443f713698ce2103bd48660f696bffc48707e96f95d80a53e76a2779694`。

## MESH 收集 PARTIAL

新增类型 `mesh` 在隔离根 `phase7-readonly-lab-59396b3b1b` 通过正常 API 和独立 Worker 执行。任务为 `device-task-227469fa1205499eb1bd77e54a8f7fe4`，状态 `COMPLETED`，业务结果 `NO_EFFECTIVE_TARGET`。

AC `.2` 与 AC2 `.5` 均执行 `display clock` 和 `display wlan mesh-link ap`，设备明确返回 `WMESH is not configured.`。逐设备状态均为 `skipped`，原因为 `AC 未配置 WMESH`，记录数 0，耗时约 22.3 秒。真实非零 MESH 链路验收仍需已有 MESH 业务的实验设备。

定向 fixture 已验证非零链路解析、明确零记录、未知非空回显失败、V5 命令回退、不支持命令跳过与未配置 WMESH 跳过。复用现有 V5/V9 parser 和 Mesh-Link 验证逻辑。任务结果写入不会触发身份推断、组织关联或 MESH Current 更新。

跳过结果仍可导出。导出任务为 `device-task-export-2cea15dcad5f4460b83d12b8692b8098`，Artifact 为 `3ad8d5cd-563d-44c0-95f0-f6576e6e4cea`，公开 API 下载 6928 字节，SHA-256 为 `13e9aacedc88f67a85fe5f873638a6308d7b5b0d2e355d4f1a87b3e068511e58`。

## 数据与运行边界

```text
RuntimeMode=TEST
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```

脚本结束时通过正常应用 lifespan 关闭 Worker。测试数据留存于明确的隔离根，供本轮验收追溯。Electron 保存对话框与 GUI 视觉验收由主 Agent 独立记录。
