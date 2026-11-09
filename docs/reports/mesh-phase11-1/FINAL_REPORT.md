# Mesh Phase 11.1 最终实施报告

日期：2026-11-09；Agent：codex-A；Codex-Thread：01a1bce5-4c6a-7562-91c9-5b9139f63cd2。

## 交付结论

本轮完成 UI 收敛、主链路八图时间轴联动、LinkCnt=0 可选只读查询、建链记录合并和 RSSI 同期跳转，并在实际 Electron 1920×1080、宁波地铁12号线现有会话中验证。内存只给出实际观察，不宣称 OOM 已根治。详细状态见 [STATUS.md](STATUS.md)。

## 修改内容与主要文件

- `MeshAnalysisView.vue`：单一紧凑标题、操作栏及四工作区；概览主统计与辅助统计分层，其他工作区不重复整组统计；移除旧空口负载入口，保留原业务查询和导出能力。
- `MeshPhase11Workbench.vue`：左摘要、中间八组纵图、右侧历史详情；父级统一时间窗口、悬停、采样选择、AP/Radio/角色；统一主链路记录（建链顺序），分页历史查询，16 项缓存和请求竞态保护。
- `MeshMetricChart.vue`：受控真实时间轴与 dataZoom/axisPointer；实际 finished 完成反馈、视口绘制、独立错误；解绑事件、ResizeObserver/IntersectionObserver 和 dispose。
- `MeshRssiChart.vue`：同期跳转和标量时间戳点击修复；原来的 RSSI/轨旁分析保留在对应工作区。
- `mesh_analysis_query_service.py`、Router 与 DTO：扩展既有接口的时间窗、精确 AP、角色和零槽位选项；不建立第二套八指标 API。
- `mesh_monitor_sampling.py`：流式窗口采样，保留桶内极值、空值及角色/身份边界；计数器先分链路差分再降采样；边界过密时明确要求缩小窗口，不静默丢失切换证据。
- `mesh_log_parser.py`：新增只读零槽位迭代，不改变既有有效链路入库语义；从已有归档读取被旧解析忽略的 LinkCnt=0，不回填数据库。
- Renderer 与 Python 回归覆盖共享窗口、选择、跳转、过滤、计数器、峰值/边界、事件释放、取消与缓存；新测试 SQL 访问登记为 TEST_ONLY。

上述源码位于 `apps/desktop_renderer/src/components/mesh-analysis/`、`apps/desktop_renderer/src/views/rail-transit/`、`src/netconsole/`，未修改 Electron 主进程、版本、发布或数据迁移代码。

## 实测验证

- Python 六个定向文件：233 passed，3 项弃用警告，62.93 秒。
- Renderer 十个文件：154 passed，0 skip。`pnpm build`（含 vue-tsc -b）通过，仅已有 chunk 体积警告。
- 修改范围 Ruff 通过；最终 diff 检查通过（Windows 换行提示）。
- 架构门 11/12 通过。唯一失败：未修改的 `mesh_link_detail_export.py:1439` 文档字符串 `display formatting or unit conversion` 被命令扫描器识别成设备命令。保留 FAIL，不为本任务修改无关文件。
- 实际 Electron：八图窗口/定位线、点击详情、Radio/角色、LinkCnt 开关、RSSI 同期跳转、单 AP 历史、统一记录及实际离页重入已取证。
- 实际导航 Dashboard 后图表容器和数据组为 0；重入各图仅一个 Canvas，滚动进入视口后八项 COMPLETED。旧动态 import router 脚本只改变 URL，不能作为离页证据；详见截图验收报告。

命令及结果摘要见 [automated-validation.json](automated-validation.json)。未跑完整全仓测试，未跳过已有失败来制造通过。

## Consumer Audit 与集成边界

Registry 路径最低 L2；因领域接口参数、响应及多个图表消费者扩展，按 L3 审视。写入、读取、缓存、导出、旧格式及并行修改已在 [PLAN.md](PLAN.md) 登记。旧调用缺省参数保持兼容；UI 字段移除不删除底层追溯数据。精确 MAC 支持冒号、连字符和点分格式，未增加模糊/跨站身份匹配或读请求重建身份投影。

消费者回归覆盖 parser/query/API/业务统计以及 Renderer 页面、图表、视口、加载和 RSSI 上下文。唯一 worktree，任务初始干净；三项审查/测试子任务已完成，最终在组合代码上复验。没有合并，合并后测试不适用，未来合入必须重跑。

## 性能、加载与剩余限制

实际内存观察见 [PERFORMANCE_MEMORY_REPORT.md](PERFORMANCE_MEMORY_REPORT.md)。本轮操作未复现异常退出；曾有旧进程超过 1 GiB 的记录，不能跨进程对比后宣称根治。当前监控八组查询并发，各图独立完成，视口外延迟绘制；完整的每图查询懒加载仍是限制。服务端无处理阶段推送，后台 SQL/差分/降采样的子阶段不伪造成前端进度。长稳、慢查询和真实故障注入未执行。

## 数据与提交

只读直接使用 `D:\NetConsoleData-dev`，未完整复制 Site/数据根，未改真实 raw、数据库或 schema；核对 SQLite/归档 SHA 前后一致。未访问 Production 做测试，未操作设备。源码、测试、文档及截图进入本地提交；DevStatus 独立本地提交。分支 `codex-A/mesh-analysis-scope-ui-optimization`；产品与 DevStatus 的实际提交 ID 见最终交付消息和 DevStatus。按照最新任务书未 Push、Merge、Release。
