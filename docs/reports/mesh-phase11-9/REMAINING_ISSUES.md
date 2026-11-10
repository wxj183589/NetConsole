# 第四轮剩余问题与风险

日期：2026-11-10
Branch：`codex-A/global-dataroot-disk-policy`
结论：`PHASE_11_9_FOURTH_ROUND=PARTIAL`

## P0/P1 未闭环项

1. **真实 Renderer 端到端未运行**：本轮没有在 Electron 中完成冷缓存、双缺口、缩小窗口、右侧详情、时间轴和多图联动的网络/SQL/绘图证据。
2. **真实业务字段逐条对照未完成**：fixture 已验证 counter previous/delta/per-second、reset、role change、gap；真实数据已验证 raw record identity/时间/顺序/角色和分段数量，但真实 Renderer 的 derived row 尚未与一次性基准逐字段规范化比较。
3. **分段组合覆盖不完整**：真实数据只完成两段前向与一次性窗口；三段、多段、逆序加载、先中间后两侧、重叠区间和缓存淘汰后重查尚未做真实 route/Renderer 对照。
4. **工作台全域 raw 统一尚未完成**：主工作台非 zero-link 指标、历史、时间定位和右侧本地详情已接入；`include_zero` 仍走旧 metric endpoint，AP 统计、Active Build Order/建链分页、摘要和解析问题仍为独立查询。不能宣称所有十类数据消费者均只读同一 raw cache。
5. **最近采样兼容路径仍存在**：真实 raw metadata 正常时定位使用本地二分查找；旧后端/test double 无 raw metadata 时保留 request-local nearest fallback。该 fallback 不推进 raw coverage，但需要在兼容后端退役前持续监控。
6. **计数器重置语义需业务确认**：当前派生算法遇到累计值倒退或 LinkCnt=0 时返回 null/status，不将当前累计值擅自当作增量；尚未用真实历史基线确认这与所有既有业务报表完全一致。
7. **LRU 没有 active-scope pin**：默认 8 scope/100000 sample 有界，但当前显示 scope 未做引用保护；极端并发/多会话下可能淘汰正在展示的数据，之后会重新规划缺口。
8. **SQL trace 仍是 Service 局部计数**：已在真实 raw Router 暴露 count，但不是应用全局 SQLite profiler；AP、build order、分页、nearest 等接口的统一 operation/request trace 尚未完成。

## 外部验收未执行

- 真实 Electron/Windows 原生窗口、截图、滚轮/Shift/Ctrl/Esc 交互。
- JS Heap、Renderer RSS、100 次操作和 30 分钟长稳。
- Excel/WPS GUI、现场设备和任何配置写入。
- Production 数据、设备和 `D:\NetConsoleData`。

## 安全与数据边界

本轮未触碰 Production、未复制完整真实 Site、未改 schema、未连接设备。开发数据主 DB/catalog/raw/WAL 内容 SHA 前后一致；parsed `-shm` 内容 SHA 一致但 mtime 漂移，已在真实数据报告中保留，不将其隐藏为“零副作用”。

## 建议下一步

提供可控的只读 Electron 运行环境后，首先记录同一真实 20 秒窗口的一次性与两段/三段/逆序派生 JSON，逐字段比较；随后补齐完整工作台 HTTP/SQL trace 和 Heap/长稳。若要关闭缓存淘汰风险，再为当前显示 scope 增加 pin/refcount，并补对应单元测试。
