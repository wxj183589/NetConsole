# 宁波地铁12号线真实数据验证

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
数据状态：只读验证；未访问 `D:\NetConsoleData` Production。

## 数据范围

本轮只读取 `D:\NetConsoleData-dev` 既有 Authority，没有复制整个 Site/数据根，没有重新导入 raw log，没有启动会写入真实 Authority 的完整 Electron runtime，也没有连接设备。

- 站点：宁波地铁12号线
- Session：`7c7b6df2-e67b-452a-ab1a-91760014501f:1`
- Train/MR：列车03 / 列车03-MR-CW
- `source_id/detail_source_id`：1
- parsed DB：`列车03-MR-CW-2026_10_20_1meshlog.mesh.sqlite`
- 原始日志：`列车03-MR-CW-2026_10_20_1meshlog.log.gz`
- 记录范围：`2026-10-20 00:00:32.413` 至 `18:01:07.949`
- 直接只读统计：`mesh_links=110058`、`samples=39167`、`source_files=1`、`switch_events=2692`

验证 HTTP 使用最小 FastAPI app：仅配置 `PathResolver(data_root=D:\NetConsoleData-dev)`、已构造的 `MeshAnalysisQueryService` 和 MESH router。该方式验证真实 Router/Service/SQLite 链路，同时避开完整应用启动时可能存在的初始化写路径。

## 真实查询结果

5 分钟 raw 查询（Radio 1）：目标/返回 905 条，`raw_sample_complete=true`，版本 `mesh-raw-v1`，context 0，SQL 3，Service 用时约 65.99 ms，墙钟约 66.47 ms。

20 秒窗口 `00:05:00.000–00:05:20.000`：可见 61 条、items 64 条（含 context 3），可见角色 ACTIVE 21 / STANDBY 40，context ACTIVE 1 / STANDBY 2，可见链路身份 4 个，raw 完整，SQL 3。

分段窗口的可见 id 对照：

- 第一段 `00:05:00.000–00:05:10.000`：31 条，items 34，context 3，首/末 id `803/836`（返回序列中 context 位于可见起点之前）。
- 第二段 `00:05:10.001–00:05:20.000`：30 条，items 33，context 3，首/末 id `834/866`（context 为 `834,835,836`）。
- 一次性 20 秒：61 条，items 64，返回 items 首/末 id `803/866`，可见首/末 id `806/866`。
- 一次性可见 id 与两段可见 id 串联完全一致，连续为 `[806..866]` 的实际目标序列；context 不计入目标总数。

另做 1 小时 raw 查询：目标 10820 条，完整，SQL 3，Service 用时约 660.3 ms。该结果用于规模/性能观察，不等同于完成全工作台长稳验收。

## 文件保护核验

以下为本轮验证前后内容核验。主 DB、catalog、raw gz 和 WAL 的 size/SHA 前后一致；SHM 内容 SHA 一致，但 SQLite 读取期间 `-shm` 的 mtime 发生漂移，不能宣称“所有文件系统元数据零变化”。

| 文件 | Size | Before SHA256 | After SHA256 | mtime 证据 |
|---|---:|---|---|---|
| `catalog.sqlite` | 110592 | `48b64eabb5047bea2a0aac932c6a26068fd03d13c65c1683f14d4d4fd009ccfd` | 同左 | `2026-11-09T12:12:38.5564922Z` |
| `列车03-MR-CW\mesh.sqlite` | 249856 | `b89146547fa0577fd2643660347de942b2aef7493736e1f586a0b94225e73cb0` | 同左 | `2026-10-20T12:18:02.1708472Z` |
| parsed 主 DB | 158621696 | `27efefb951be073e9f43d22c8bbd583ca7a86ded225f8a8ad9d7a5e2551524fc` | 同左 | `2026-10-20T12:18:02.1489477Z` |
| parsed `-wal` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 同左 | 内容/大小未变；不据此推断 runtime 零写入 |
| parsed `-shm` | 32768 | `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb` | 同左 | mtime_ns 从 `1794247248302463200` 变为 `1794247248425832500` |
| raw `.log.gz` | 2953314 | `282e2166cc7abf15a8e20794db7a5f83174768fabe807ae2b74da3c639a3d2bc` | 同左 | `2026-10-20T12:17:25.2072822Z` |

## 结论与边界

内容级 SHA 核验通过，未发现主 DB、catalog、WAL 或 raw 日志内容变化；SHM mtime 漂移被保留为真实风险证据。真实 Service/Router/raw SQL 验证通过，但由于没有启动完整真实 Electron，本报告不宣称 GUI、Renderer Heap、长稳、Excel/WPS 或现场设备验收通过。
