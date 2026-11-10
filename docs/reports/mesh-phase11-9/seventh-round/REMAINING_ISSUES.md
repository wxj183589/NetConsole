# 第七轮剩余问题

## 产品/证据状态

1. `PHASE_11_9_SEVENTH_ROUND=PARTIAL_WITH_CORE_MESH_ACCEPTANCE`。MESH raw cache、热缓存零查询、A+C 仅补 B、派生字段一致性和 ECharts/listener 计数均有真实证据；整体不提升为 PASS，原因见下列边界。
2. Workspace layout 仍被与 MESH 无关的既有顶层 `D:\study\NetConsole-Workspace\docs` 阻塞，分类为 `BASELINE_WORKSPACE_BLOCKER`；本轮未删除、移动或放宽规则。
3. TEST runtime 的 catalog rebuild 会刷新 `mesh_catalog_index_state.updated_at` 和 `mesh_source_fingerprints.updated_at`。本轮已证实为 `EXPECTED_RUNTIME_WRITE`，没有原始数据写入；若要求所有查询绝对只读，需后续单独收敛 TEST 运行策略。
4. 第七轮没有重复 30 分钟长稳；沿用第六轮 1803 秒/117 操作结果，并新增真实生命周期计数。不能把本轮短时复测写成新的长期 Heap PASS。
5. 逆序、多缺口、LRU 淘汰、Counter reset 和链路切换的边界由现有单元/Python 回归覆盖；本轮真实 Electron 重点是 A/C/中间 B 和重复 ABC，不声称每个边界都重新做了独立真实设备采样。

## 不属于本轮缺陷

- `D:\NetConsoleData`、`D:\NetConsoleData-dev` 未作为 runtime 写入目标。
- 未修改生产/真实开发数据、设备配置、独立 `D:\study\fping` 项目。
- Excel/WPS 原生 GUI、现场设备、安装包和 125% DPI 仍按既有交接保持未验收，不作为本轮缓存专项的伪 PASS 或伪 FAIL。
