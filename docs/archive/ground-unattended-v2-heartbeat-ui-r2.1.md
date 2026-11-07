# NetConsole 原版｜地面无人值守 V2 心跳检测 R2.1

日期：2026-11-07  
分支：`codex-A/ground-unattended-v2-20261107`  
基线：`b3c2fd51`  
项目：`Ground-Unattended-Heartbeat-Initial-Load-And-Polling-Fix`  
PR：#105（本轮未合并）

## 根因

R2 已补齐无快照时的后端库存投影，但前端仍有两个调度边界：心跳页固定使用 `setInterval`，并且未将真实无人值守状态作为轮询门禁；父级组合式函数也把 `PAUSED`、`STOPPING` 等状态归入运行态，继续请求车辆和 Ping 目标。结果是首次进入时库存与快照读取时序不稳定，停止后仍有周期性请求。

## 修复

- `HeartbeatPage.vue` 读取父级真实状态，仅 `RUNNING` 创建单次递归 `setTimeout`；每轮请求完成后才安排下一轮，组件销毁、Tab 离开、暂停和停止状态都会清理调度器。
- 轮询失败采用 3 秒起步、上限 30 秒的退避；成功后恢复 3 秒周期，避免失败时高速重试。
- 从非运行态进入 `RUNNING` 时立即执行一次采样；离开 `RUNNING` 只中止请求和定时器，保留已有心跳数据。手动刷新仍可用，但不会启动后台轮询。
- 将运行状态命名为 `monitorStatus`，过滤条件独立为 `statusFilter`，避免真实状态与页面筛选互相覆盖。
- `useGroundUnattended.ts` 新增 `monitoringRunning`，只有真实 `status.state === 'RUNNING'` 才刷新运行期健康、车辆、Ping、AC 和深采数据；心跳页在停止、暂停、停止中状态只读取车辆库存。

## 测试证据

新增 Fake Timer 与行为测试覆盖：

- STOPPED 首次读取一次快照，60 秒内不重复请求。
- RUNNING 使用单一完成链定时器；进入 PAUSED 后不再发起周期请求。
- 心跳接口失败退避，并保留上一份成功快照。
- 停止态进入心跳页仍加载车辆库存，不请求 Ping 目标。
- 既有旧请求竞态测试继续确认 AbortSignal 和代际校验不会让旧响应覆盖新运行。

本轮定向测试：

- `pnpm exec vitest run src/views/rail-transit/HeartbeatPage.test.ts`：7 passed。
- `pnpm exec vitest run src/views/rail-transit/GroundUnattendedView.behavior.test.ts`：35 passed。
- 受影响 Renderer 合并套件（Heartbeat、Ground 页面、Ping 图表、MR 抽屉）：5 files / 71 passed。
- `pnpm exec vue-tsc -b` 与 `pnpm build`：通过。
- Python Ground Scheduler/API：48 passed；库存首加载相关 2 passed。

库存统计旧测试 `test_heartbeat_page_aggregates_real_ping_statistics` 在当前系统时间下得到 `STALE` 而非断言的 `RUNNING`，原因是 fixture 固定在 `2026-11-07T10:00Z` 且已超过 stale 阈值；该失败与本轮 Renderer 调度改动无关，未修改业务阈值或测试掩盖它。Browser E2E 未启动；真实 Electron 窗口、设备、安装包和长稳验收仍不在本轮自动化证据内。

## 数据与兼容边界

本轮只修改 Renderer 调度与测试，没有数据库 schema、API DTO、心跳 worker、Ping 阈值或真实数据根变更。未读取、复制或写入 `D:\NetConsoleData`、`D:\NetConsoleData-dev`，未连接真实 AC/MR 或现场 Syslog。

## Change Impact

Risk：L2，Ground 领域页面与组合式函数调度。  
Contracts：真实运行状态门禁、库存与心跳快照分离、单调度器和旧请求代际校验。  
Consumers：`HeartbeatPage.vue`、`useGroundUnattended.ts`、Ground 页面行为测试及 Renderer 定向套件。  
剩余：真实 Electron 截图、Windows DPI、真实设备、安装包和长时稳定性仍为 `REAL_DEVICE_PENDING`；PR #105 保持开放。
