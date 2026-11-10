# 时间选择验证

日期：2026-11-09。

## 已检查实现

- 图表以containPixel确认网格，再用convertFromPixel将任意横坐标转为毫秒时间；Shift左键不依赖点符号命中。
- Workbench以完整counter查询窗口建立毫秒索引，二分最近有效ACTIVE记录，排除STANDBY及LinkCnt=0；不使用可能缺少counter元数据的RSSI窗口记录替代。索引不完整则请求当前Session/AP/Radio/时间窗口内最近ACTIVE采样。
- Ctrl移动以80ms节流取最新目标；请求代次和AbortController保护旧结果，已有相同时间缓存优先复用。
- Shift固定后普通指针移出不清除选点；Esc清除固定、待执行选择、selectedTime、selectedSample及右侧详情，避免残留markLine。
- 精确focus查询仍防御性拒绝STANDBY和零链路返回，不扩大范围查询。右侧12项counter累计值及前值/增量/间隔/速率，与各图selectedSample使用同一原始记录。
- 普通滚轮不preventDefault；Shift滚轮更新共享窗口；窗口改变后180ms合并查询并将原选点重新定位到窗口内。

## 自动测试证据

| 场景 | 自动验证范围 |
| --- | --- |
| 任意X Shift点击 | 像素转时间、time-select含fixed=true、不依赖sample-click |
| Ctrl移动 | 仅Ctrl触发、网格外忽略、最新目标节流、精确条件查询 |
| 毫秒最近采样 | 完整counter索引与不同RSSI记录冲突时仍选counter原始记录、ACTIVE筛选、排除零链路 |
| 固定与离开 | 固定选择保留，普通指针不覆盖 |
| Esc | 发出selection-clear，清除选点/详情/标线输入，恢复普通指针行为 |
| focus与详情一致性 | STANDBY/零链路拒绝；12字段counter详情与所有图表使用同一条选中原始记录 |
| 共享窗口/指针 | 静默同步无反馈环、180ms最终窗口请求 |
| 快速选择/关闭 | 中止旧请求、忽略旧代次、清理timer与事件 |
| 窗口排除选点 | 新窗口内重新定位 |
| 普通滚轮 | 未阻止默认事件，ECharts关闭wheel捕获 |

对应 `MeshMetricChart.test.ts` 与 `MeshPhase11Workbench.test.ts`，四组定向运行82/82通过。happy-dom20 WheelEvent缺少修饰键/坐标，测试以MouseEvent('wheel')补deltaY驱动真实组件监听函数。

## 未完成验收

真实Electron普通滚轮页面scrollY前后、Shift滚轮共享窗口前后、Ctrl拖动、固定指针截图、网络请求数量证据与Esc视觉恢复均未执行。组件mock和单测不能替代以上实际交互。
