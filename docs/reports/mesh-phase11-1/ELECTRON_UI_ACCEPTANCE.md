# Electron UI 验收

2026-11-09；实际 Development Electron；1920×1080；宁波地铁12号线 列车01-MR-CW；真实数据根 `D:\NetConsoleData-dev`。截图由实际 Renderer CDP Page.captureScreenshot 获取，非静态设计图。Windows 125% DPI 按要求不测试。

## 截图索引

| 内容 | 截图 | 结果 |
| --- | --- | --- |
| 紧凑概览 | [01](screenshots/01-overview-compact.png) | PASS |
| 四业务入口 | [02](screenshots/02-four-workspaces.png) | PASS |
| 主链路三列布局 | [03](screenshots/03-main-monitor-layout.png) | PASS |
| 八指标纵图（中段/底部） | [04中](screenshots/04-eight-metrics-middle.png)、[04底](screenshots/04-eight-metrics-bottom.png) | PASS |
| 时间操作前后 | [05](screenshots/05-timeline-before.png)、[06](screenshots/06-timeline-after.png) | PASS，需结合 JSON 核对精确时间 |
| 悬停联动 | [07](screenshots/07-hover-linked.png) | PASS |
| 点击采样详情 | [08](screenshots/08-selected-detail.png) | PASS |
| 单 AP 历史 | [09](screenshots/09-single-ap-history.png) | PASS |
| LinkCnt=0 关闭/开启 | [10](screenshots/10-linkcnt-zero-off.png)、[11](screenshots/11-linkcnt-zero-on.png) | PASS |
| 零槽位详情 | [11详情](screenshots/11-zero-selected-detail.png) | PASS，未连接 |
| RSSI 同期跳转 | [12](screenshots/12-rssi-jump-main-monitor.png) | PASS |
| 统一建链记录 | [13](screenshots/13-unified-build-records.png) | PASS |
| 连续操作后 | [14](screenshots/14-memory-after-continuous-operations.png) | 仍可用；内存数值见独立报告 |

八张纵图超过一屏高度，使用实际滚动截图展示，没有把页面缩小到不可读尺寸。截图只证明该时刻的画面；交互时序由同目录 JSON 补足。

## 时间轴与详情

`timeline-interactions.json` 保存 wheel zoom、真实鼠标平移、底部导航器、悬停、采样点点击及八实例 options。actualPanBefore/actualPanAfter：18:36:19.032–18:41:53.709 → 18:36:15.832–18:41:50.509，八图一致。所有轴为 time，使用真实时间戳，各实例一个 Canvas。悬停指针统一，采样选择同步右侧历史详情；摘要及记录选择也可更新详情。

Radio2、STANDBY、重复 AP 和快速切换取证于 `rapid-cache-lifecycle.json`。LinkCnt 开关及统一建链表取证于 `filters-interactions.json`。RSSI 跳转以 `rssi-jump.json` 的锁定窗口、实际选点和结果为准。

## 离页清理取证纠正

早期 `route-lifecycle.json`、`route-lifecycle-final.json` 使用动态 import router.push，虽改变 URL，仍有八个图表容器，不能证明工作区已离开。保留原证据，不采用其离页 PASS 结论。

最终通过真实顶部「打开 Dashboard」按钮，再点击「MESH：列车01-MR-CW」工作区标签验收，证据 `actual-navigation-lifecycle.json`：

- 离页 Mesh DOM=false，chartContainers=0，groups=0；取消并清理图表状态。KeepAlive 保留有界缓存16项以支持返回。
- 重入八张图各一个 Canvas，同一时间窗与定位点。视口外图保持 RENDERING，不提前完成；每张实际进入视口后八项全部 COMPLETED。
- 页面离开/重入不是整个 Electron 进程退出；关闭进程场景未用此证据替代。

## UI 字段审查

四工作区、概览统计、AP 表、主监控摘要、右详情、统一建链表、历史采样及图表图例以运维字段为主；普通表格不展示内部 ID、来源文件/行号、解析/匹配规则或身份来源，不重复 Peer/Peer Radio MAC。内置底层追溯信息未删除。既有导出入口保留，本轮未实际生成并逐列验收 Excel，因此不声称 Excel GUI 验收通过。

## 限制

慢 SQL、真实单图查询失败/绘制故障注入及长稳未执行；错误隔离与竞态用自动化补充。真实 Electron 本轮交互未出现可复现 OOM，长期稳定性仍有限制。
