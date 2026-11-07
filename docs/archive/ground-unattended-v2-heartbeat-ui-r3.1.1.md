# Ground R3.1.1｜心跳检测整车状态列去重优化

日期：2026-11-08
Branch：`codex-A/ground-unattended-v2-20261107`
基线：`7063d85d`
状态：本轮未 Commit、未 Push、未合并。

## 修改内容

- 车辆列表保持四列：列车、CT 端、CW 端、整车状态。
- CT/CW 卡片继续独立展示状态、RTT、接入区间 AP、接入站点、最近成功/丢包率和操作入口。
- 整车状态列仅保留综合状态标签和“整车详情”入口，移除更新时间、CT/CW RTT、端设备名称、AP、站点及端状态重复信息。
- 整车详情优先触发现有 `show-train` 综合详情；无库存详情时回退到 MR 综合监测抽屉。
- 综合状态直接使用后端 CT/CW 聚合结果，支持双端在线、仅 CT、仅 CW、整车离线、待检测、已暂停、已停止和数据过期。
- 未启动监测且无采样时，车辆总数/MR 总数仍显示库存数量，可达性统计显示 `—`，待检测 MR 单独显示。
- 保留设备库存与监测数据解耦逻辑；未修改调度器、Ping 状态机或设备库存。

## 布局核验

隔离 Electron 运行目录：`D:\study\NetConsole-Workspace\test-data\NetConsole\ground-r311-20261108`
截图目录：`D:\study\NetConsole-Workspace\reports\tests\ground-r311-20261108`

本轮截图和 Electron DOM/布局 JSON 保存在上述 Workspace 临时目录，未纳入 Git 归档；下方保留其核验结论。

实际 Electron DOM 结果：

- 1920：`88px 699px 699px 124px`
- 2048：`88px 763px 763px 124px`
- 1672：`88px 575px 575px 124px`
- 三种尺寸 `overflow=false`。
- `.train-summary` 仅包含“整车状态 / 待检测 / 整车详情”，不含时间戳。
- CT/CW 卡片保留独立状态、RTT、接入区间 AP、接入站点和最近成功信息。

## 测试结果

- `pnpm exec vitest run src/views/rail-transit/HeartbeatPage.test.ts`：16 passed。
- `pnpm exec vue-tsc -b`：通过。
- `pnpm run build`：通过（仅保留既有 chunk size warning）。
- `git diff --check`：通过（仅显示行尾格式提示）。
- `pnpm exec playwright test tests/visual/e2e/heartbeat-monitor.visual.spec.ts --project='1920x1080@100%'`：4 passed；测试内覆盖运行态、未启动态、2048×1091、1672×941。
- `python -m pytest -q tests/test_ground_unattended_heartbeat_state.py tests/test_ground_unattended_heartbeat_inventory.py tests/test_ground_unattended_api.py`：78 passed，1 个既有 Starlette/httpx 弃用警告。
- 隔离 Electron 实际运行：已检查 1920×1080、2048×1091、1672×941，未连接真实设备，未写入真实业务数据。

## 剩余问题

- 未执行真实设备连接和生产数据验收，需按发布流程另行授权。
- 工作区原有 R3 dirty 修改全部保留，本轮没有清理或回滚。


修改前对照截图：

修改前截图同样保存在上述 Workspace 临时目录，未纳入 Git 归档。
