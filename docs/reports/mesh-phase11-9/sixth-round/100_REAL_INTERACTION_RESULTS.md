# 100+ 真实 Electron 交互结果

## 结论

满足数量门槛：稳定性阶段记录 30 个分钟样本、117 次真实鼠标/键盘交互；主验收动作 ledger 另有 35 个操作项。操作通过 Electron 原生窗口执行，不是浏览器替代验收。

## 覆盖项

- 页面进入、主链路监控、分析概览、报告与来源、AP 情况和页面重入。
- 主链路图表 wheel zoom in / zoom out。
- 13 个 chart host 的逐图 wheel 操作。
- tooltip hover、双击/点击详情、主链路表行和 recent-history 行。
- Shift 固定详情、Ctrl 浏览详情、Escape。
- navigator 拖动和 wheel。
- AP 链路角色切换到备用（STANDBY）及 Radio 1。
- 30 分钟期间重复滚动、详情、页面操作和缓存范围内交互。

## 缓存观察

缓存范围内 chart wheel、tooltip、键盘修饰键和详情动作没有新增 MESH HTTP/SQL，也没有页面错误或 chart rebuild 错误。跨越未覆盖 raw interval 的区间扩大动作被单独标记为 gap；它不是缓存命中场景，未被计入 0/0 结论。

## 截图

10 张固定文件均存在，尺寸均为原生 `1920x1080`；截图没有通过浏览器窗口拉伸。完整 inventory 见 `SCREENSHOT_INVENTORY.md`。
