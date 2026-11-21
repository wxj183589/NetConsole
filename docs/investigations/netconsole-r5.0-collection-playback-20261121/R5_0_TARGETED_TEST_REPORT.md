# R5.0 专项测试报告

执行范围仅覆盖本任务，不执行 Python/Renderer/Electron Full Suite、全量 Gate 或长稳。

已覆盖：

- MESH 只读索引、窗口前序证据、相邻切换区间；
- RSSI -44/-55/-65/-75/-85、正数绝对值、NULL、非法类型与超界值；
- 丢包窗口相交、limit/offset/total 契约；
- Ping 统计与严格事件窗口分离；
- 主备 RTT/单包丢包单位、空白断线；
- 全局 visible window 与唯一 Navigator；
- 回放组件进入时零请求、零采集启动；
- Renderer 类型检查。

## 结果

- Python：`82 passed`（monitoring、heartbeat inventory、Ground API；含 immutable/WAL 拒绝测试）。
- Renderer：7 个相关测试文件，`75 passed`。
- `vue-tsc --noEmit`：PASS。
- Renderer `pnpm build`：PASS；仅保留既有大 chunk 警告。
- Ruff 定向检查：PASS。
- `git diff --check`：PASS。

GUI 不由组件测试替代，状态保持 PARTIAL。
