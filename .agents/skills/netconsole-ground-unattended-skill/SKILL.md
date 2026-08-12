---
name: netconsole-ground-unattended-skill
description: "NetConsole 地面无人值守、07:00-23:00/跨午夜调度、列车资格、正线/场段、AC 常驻轮询、Fleet fping、UDP Syslog/WMESH、深度采集、时间轴、原始数据、归档恢复或长时间运行任务时使用。人工 Online MR、离线 MESH 或普通 Traffic 页面不使用本 Skill。"
---

# 目标

维护地面无人值守独立状态机、长运行资源和原始事实，使 AC、Ping、Syslog、深采、归档和恢复在 Backend 生命周期内可追溯、可停止且不污染人工 Online MR。

# 触发与反例

触发示例：

- “修改无人值守时间窗口、资格分类、调度或 AC 常驻轮询。”
- “修复 Fleet Ping、Syslog/WMESH、深采或运行恢复。”
- “处理 raw 生命周期、READY ZIP、历史查询或归档删除。”

不应触发：

- “修改人工 Online MR 实时页面或离线 MESH 分析。”
- “只修改通用 fping/iPerf 页面。”

# 输入与输出

- 输入：局点 Profile、run/operation/session、列车/MR/AP 事实、时间窗口、原始文件与生命周期问题。
- 输出：Ground Application/Supervisor/Repository/API/Vue 的最小修改、原始数据保护、调度/恢复影响和验证。
- 允许修改生产代码：允许，限 Ground 领域和直接共享适配；不得借此改变 Online MR 命令、MESH 算法或真实局点数据。

# 开始前读取

- `docs/rail-transit/ground-unattended/README.md`、`src/netconsole/services/ground_unattended/README.md`。
- `src/netconsole/services/ground_unattended/`、`src/netconsole/repositories/ground_unattended_repository.py`。
- `src/netconsole/backend/api/ground_unattended_router.py`、`src/netconsole/models/api/ground_unattended.py`。
- `src/netconsole/services/job_center/handlers/ground_unattended_jobs.py`、共享 Online MR/fping/AP Identity 入口。
- `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.vue`、对应 API/类型和相关 pytest/Vitest。

# 当前架构事实

- Ground 是独立页面和业务状态机，不复用人工 Online MR 页面状态，也不把整日运行塞进一个 Online MR Session。
- `GroundUnattendedSupervisor` 由 FastAPI lifespan 管理；页面卸载只停止 Renderer 轮询，托盘隐藏时 Backend、AC Poller、Ping 和深采继续运行。
- Current AP 与 WMESH old/new 通过局点 AP Identity 的完整 48 位 MAC 精确解析；名称、尾号、前缀和 SQL `LIKE` 不授予资格。
- 默认窗口为 `07:00-23:00`、时区为 `Asia/Shanghai`，支持跨午夜；Profile 运行中更新只有文档明确允许的字段热生效，其余保持当前 run 冻结语义。
- Ground 与 Online MR 共享部分 Session/fping/Job 基础设施，但资格、调度、覆盖、停止、归档和历史语义不同。

# 工作流程

若变更触及 AP Identity、共享 fping/Online MR、Task/Job、动态图、DataRoot 或文件契约，编码前先组合 `netconsole-change-review-skill` 完成消费者审计。

1. 先定位 Profile、Supervisor、active/latest run、operation、raw、query 或 Renderer 生命周期中的单一问题，写明受影响的长期资源。
2. 将 `mainline_eligible`、`ping_eligible` 和 `deep_collection_eligible` 分开；使用当前 run 的同一决策 revision，未知、陈旧、歧义或无精确 AP 身份时失败关闭。
3. AC 常驻轮询每个 controller/run 复用一个受管 Worker/SSH；重连、立即轮询和停止保持同一 task/session 边界，不把凭据或命令写入 Task。
4. Fleet Ping 按稳定目标、分片、预热和增量游标运行；场段开关不能改变正线统计或启动 iPerf/SSH 深采。
5. UDP Syslog 保持有界队列、原始 NDJSON、来源隔离和结构化派生；旧记录只读 enrichment，不改写历史 raw。
6. 深采只构造强类型 Online MR 请求，复用既有命令、会话、fping、正常停止、解析和原子 ZIP；不停止人工任务，同一 MR 仍互斥。
7. 停止、最终化、归档和删除走持久 operation/Job；ZIP/manifest/hash 校验 READY 后才白名单清理 active，失败保留原始数据。
8. 页面按 activity/tab 增量轮询，使用 Abort/generation/防重入；图表、浮窗、Observer 和 listener 在关闭/卸载时成对释放。

# 禁止模式与不变量

- 不用 AP 名称、站点文本、MAC 相似度或当前显示值替代精确 Identity；ambiguous 不选第一条。
- 不让页面卸载、隐藏到托盘或历史切页停止后台运行；明确退出才走受管收口。
- 不把 Ground 的 Fleet Ping 当作深采 Session fping，不把人工 Online MR 与自动深采状态机混用。
- 不静默删除或重写 raw、OPEN 文件、READY ZIP、manifest 或正式历史；不在 Router 同步压缩/清理。
- 不把 fake、本机回环、规模测试或单台 MR 证据外推为多列车、长时、主备 AC 或真实桌面验收。

# 验证与失败报告

- 覆盖跨午夜、手工停止抑制、资格矩阵、静止恢复、AC 重连/停止、目标分片/预热、Ping 增量游标和恢复。
- 覆盖 Syslog 身份/重复/分页/预算、raw 锁与原子重写、ZIP CRC/hash/path/bomb 防护、READY/active/MIXED 查询和启动恢复。
- 运行受影响的 `tests/test_ground_unattended_*.py` 和 Ground Vue 定向测试；图表改动同时执行 `dynamic-chart-stability` 要求。
- 报告 Profile/调度/命令是否变化、进程和 raw/SQLite/归档影响、兼容性、实际验证和现场/长时/GUI 缺口。

# 相关 Skills

- L3/L4 影响审计：`netconsole-change-review-skill`。
- Online MR、Traffic 和 Job：`netconsole-online-mr-skill`、`traffic-test-skill`、`netconsole-job-center-skill`。
- AP Identity、数据安全和动态图：`netconsole-ap-identity-skill`、`netconsole-data-safety-skill`、`dynamic-chart-stability`。
- Artifact 保存：`netconsole-user-file-interaction-skill`。
