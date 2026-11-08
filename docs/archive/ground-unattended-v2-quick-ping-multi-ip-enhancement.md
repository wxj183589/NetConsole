# Ground Unattended V2 Quick Ping 多 MR / 多 IP 优化

日期：2026-11-07。原版仓库；保持所有任务开始前 dirty 修改。Branch `main`，基线 HEAD `9031d00017cecf8802f34a96f136bbf01007d862`。按任务禁止 Commit / Push / Merge / Release。

## 架构与修改

原有 QuickPingService 管理批次、fping 流、NDJSON 段、异步压缩、任务 manifest 和 SQLite 统计，独立于 Heartbeat/Fleet Ping。本次复用这些边界，将执行单位改为规范化 IPv4：一个 IP 一个受管 fping generator、停止事件、writer、状态和统计。同一 MR 的 PRIMARY/BACKUP 只要 IP 不同即可同时执行。

前端保留列车、CT/CW、主备筛选，新增 MR 名称/UUID/IP 搜索、IP 去重的多选、可移除标签和清空、占用任务提示与禁选。选中内容与筛选列表独立；历史翻页响应携带独立 active_ips，避免翻页遗漏占用。开始时再次检查选中 IP；后端 409 冲突留在页面上。详情增加每 IP 状态、开始时间、当前/平均/最大 RTT、独立停止。

QuickPingTarget 用 Python ipaddress 严格校验并转标准 IPv4 字符串，不接受域名/IPv6；输入前后空白归一。互斥键固定 `quick_ping:ip:<normalized_ip>`，与 MR UUID、地址角色、列车、参数无关。同批重复 IP 拒绝；前端按 IP 去重。

## 互斥与执行生命周期

同一索引库中的预留使用 BEGIN IMMEDIATE 整批事务，先验证所有 IP 和活动批次数，再插入全部预留。冲突整批失败，不启动空闲部分。进程内 guard 同时保护其他 Service/Site；多连接/多进程访问同一索引库依靠唯一主键和 SQLite 写事务竞争。

新增 additive 表 `ground_unattended_quick_ping_ip_reservations` 保存 owner PID+创建标识、实际 child PID+创建标识、QUEUED/RUNNING 预留；`ground_unattended_quick_ping_target_runtime` 保存批次中每 IP 状态。未删除或改变旧表列。storage_registry 已登记 producer/consumer/保留边界。

最多 4 个活动批次、每批最多 32 IP、全局最多 4 个执行 worker。超过执行槽的目标显示 QUEUED 且提前持锁。每 IP 独立 generator；单 IP 停止只设置其事件，批量停止覆盖全部目标。generator close 等待实际 fping 终止，writer 关闭且 manifest/SQLite 结果写入成功后才释放 IP。存储故障保留锁并记录 health error；局部收尾成功后或下一次 admission 重试写入，再释放。异步 gzip 延续既有有界压缩流程；SQLite 不存每个 Ping 样本。

共享 fping runner 仅新增可选 process_observer，在注册真实 Popen 后通知 Quick Service，既有消费者调用兼容；observer 异常仍进入原 finally 终止进程。未重写 fping 引擎。

## 恢复与数据边界

Windows 通过进程创建 FILETIME 避免 PID 复用误判。owner 存活时不改写其运行状态；owner 退出但记录 child 存活时保留占用。Toolhelp direct child fping 检查保护 Popen 与持久化 PID 之间的崩溃窗口。无法查询进程身份时保留占用，禁止按超时解锁。确认旧 owner/child 均退出后，持久化 INTERRUPTED 和 per-IP 终态，释放预留。已完成部分 IP、其余 IP 崩溃的批次也能终止，不依赖“剩余锁数等于全部目标数”。第二 Service 的外部 owner 状态从 SQLite 刷新，避免缓存幽灵活动状态。

跨实例停止非本实例 owner 返回 409；原实例负责退出收尾。测试数据均位于 Workspace test-data fixture 和 .local 测试证据内，RuntimeMode.TEST；未连接真实设备，真实 fping 测试仅访问 127.0.0.1 / 127.0.0.2。未复制或改写 Production / Dev 真实数据。

## 验证

- Quick/service/repository/exclusivity/shared-fping：62 passed，12.16s。
- 新 exclusivity 最后一轮（补外部 owner 状态刷新）：8 passed，2.15s。
- API Quick 定向：5 passed、33 deselected，13.73s。
- Renderer Quick：13 passed，11.75s。
- 独立 Playwright 真实 Vue+Chrome+合成 HTTP：1 passed，1920×1080@100%，9.1s；含六图与单 IP 停止后批次仍 RUNNING 断言。
- Ruff：Quick Service、ownership helper、共享 runner 与 Quick 测试均 PASS。
- storage guard 当时唯一 finding 为其他并行任务 monitoring.py 未注册；已通知主任务处理。该项不作为整个项目 gate PASS。
- 全 API 文件随共享回归为 97 passed / 2 failed；两项 Heartbeat 历史 mrs 空列表已交主任务/Heartbeat Agent，Quick API 均通过。

测试覆盖：同 MR 主备并行、别名/参数不可绕过、冲突整批回滚、4 worker 排队预留、并发独立 DB 连接仅一个预留赢家、活 owner 恢复保护、实际子进程存活/退出恢复、落盘故障后重试释放、同批重复 IP 拒绝。真实 bundled fping loopback 测试核验两个不同 PID、收到样本、单 IP 停止后 PID 已退出再解锁、另一 IP 子进程继续运行、全部停止无残留占用。

## 截图

证据目录：`.local/tests/quick-ping-multi-ip-visual/quick-ping-multi-ip.visual-1dcca--and-independent-statistics-1920x1080-100-/`。

1. `quick-01-multiple-mr-selection.png`：多 MR 多选。
2. `quick-02-same-mr-primary-backup.png`：同 MR 主备同时运行。
3. `quick-03-occupied-ips-disabled.png`：占用任务与禁用选项。
4. `quick-04-independent-ip-statistics.png`：每 IP 状态、统计、RTT。
5. `quick-05-batch-with-one-ip-stopped.png`：独立停止一 IP，其他 IP 继续。
6. `quick-06-concurrent-ip-conflict.png`：后端 409 竞争冲突。

已人工检查独立统计全图和六图联系表。证据为合成业务数据的真实组件，不是设备或完整 Electron 验收。

## Consumer Audit 与剩余边界

Quick UI → API client/types → site/capability protected router → ApplicationService → QuickPingService → repository/manifest/raw writer 的新增字段和 stop-target 操作均有 consumer。活 IP 不受历史筛选影响。旧 run 无 target_runtime 仍可读取，UI回退批次状态；旧活动 manifest 无预留仍按既有 interrupted 路径终止。新终态 INTERRUPTED 纳入 DTO、筛选、retention；target_runtime 随精确终态 summary 保留策略清理，不清理任务事件。共享 runner 可选回调通过已有 fping 测试和真实 loopback 回归。

本报告仅证明 Quick 范围；项目 FULL Gate、全链路 Electron/Backend/UDP/AC/深采持续 3600 秒、其他页面验收由主任务统一记录。未执行安装包、真实设备、24 小时压测。未新增依赖。整个 dirty 树包含原有和并行任务修改，未制造独立 commit。
