# Ground Unattended V2 AC-Mesh-Link MR 视图专项交付

日期：2026-11-07。范围：原版 NetConsole 的 AC 查询 API、地面无人值守 AC 页面及定向测试。工作树保持未提交。

## 原有数据与限制

`vehicle_mr_online_links` 已按快照逐条保存 MR 与本地区间 AP 的关系，一个 MR 可以有多条关系；`vehicle_mr_online_snapshots` 保存采集时间和接收时间。原查询服务 `_mr_rows()` 仅挑选一个代表关系放在 MR 行，造成前端单 AP 展示限制。主用和备用管理 IP 属同一设备 UUID。区间 AP 的名称和位置是对端信息，不是车载 MR 自身的身份或位置。

现有快照能证明采样时观测到的关联，不能证明两次采样之间持续连接，也不能推算精确连接或断开时刻。旧快照缺少原始回显时仅能展示结构化记录。AC Fresh/Recent/Stale 状态沿用原阈值，独立于心跳 Ping 在线状态。未解析的 MR 自身 AP 保持空值；历史查询按持久化的精确 MR 名称、系统名及 MAC 查找，无法保证涵盖更早发生过重命名且无共同 MAC 的记录。

## 实施

- MR 默认视图按列车分组，只显示实际登记或实际观测的 CT/CW；稳定 UUID 只生成一行，完整保留该 MR 的所有 Peer AP。列表显示前两个关系及总数，抽屉分页展示完整当前关系。
- MR 自身 AP 只通过设备物理 MAC 的 AP Identity 解析得到。反向 AP 视图从同一份关系数据聚合，已确认 AP 按 ID/MAC 汇总，未知身份使用 BSSID 或单次观测 ID，避免按名称错误合并。
- 关系图在当前 MR 页按身份去重节点，并绘制每条关系；历史 RSSI 图仅显示实际快照散点。过期、断开、未知关系以虚线表示。抽屉提供时间范围、分页历史观测、已有事件、快照及原始尾部；迟到请求由取消和 generation 检查拦截。
- API 新增 `GET /peer-aps`；`GET /mrs` 增加端位、数据状态、匹配状态、多 Peer 和异常筛选；`GET /mrs/{id}` 增加历史时间范围及分页。原 DTO 字段保留，新字段为 Peer 列表、管理 IP 集合、MR 自身解析结果、关系状态与时间，以及历史观测。未改变数据库表、采集器、Parser、原始文件或数据迁移。

## 定向验证

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_ac_mesh_link_query_service.py tests/test_ac_mesh_link_web_api.py tests/test_ac_mesh_link_mr_view.py tests/test_ac_mesh_link_refresh_service.py
pnpm exec vitest run src/views/rail-transit/AcMeshLinkPage.test.ts src/api/acMeshLink.test.ts
pnpm exec vue-tsc -b --pretty false
.\.venv\Scripts\python.exe -m ruff check src/netconsole/services/ac/mesh_link_query_service.py src/netconsole/backend/api/ac_mesh_link_router.py src/netconsole/models/api/ac_mesh_link.py tests/test_ac_mesh_link_mr_view.py
```

第一轮 Python 四模块 28 passed；新增历史别名及倒置时间回归所在两模块 10 passed。页面和 API Vitest 5 passed；vue-tsc 与 Ruff PASS。覆盖 1、3、10 个 Peer、无 Peer、未知 MR、多个 MR 共用 AP、主备 IP、位置隔离、筛选与历史分页。全仓 FULL Gate 和真实 Electron 截图由最终集成验收统一记录，当前不声称完成。

## 状态与待验收

已完成：代码、定向测试、无数据库变化的兼容 DTO、当前与历史观测区分。

已完成合成数据浏览器视觉验收：独立 `apps/desktop_renderer/tests/visual/e2e/ac-mr-view.visual.spec.ts` 通过真实 `GroundUnattendedView` 组件与 Chrome，HTTP 响应为合成数据。1920x1080 和 1280x720 各 1 passed；覆盖同列车 CT/CW、CT 的三个 Peer AP、主备管理 IP、AP 反向两 MR、关系图四条边及过期虚线、当前关系抽屉和三条 RSSI 历史散点序列。截图位于 `.local/tests/ac-mr-view-visual/` 与 `.local/tests/ac-mr-view-visual-1280/`，文件依次为 `ac-01-mr-ct-cw-multi-ap.png`、`ac-02-ap-reverse-drawer.png`、`ac-03-relationship-graph.png`、`ac-04-multi-peer-rssi-drawer.png`。这仅证明合成数据下的组件交互及截图，不代表真实设备验收。

未完成：真实 AC/车载 MR/区间 AP 设备验收，因本轮禁止连接真实设备；全系统连续运行结果见最终验收报告。

受现有数据源限制：快照间连续性、精准连接/断开时刻、旧结构化快照的原始回显及没有共同身份键的历史重命名均无法确认。
