# Mesh Phase 11.3 图表滚动与联动测试

日期：2026-11-09。层级：源码审查、mock ECharts组件测试、Workbench定向测试；实际Electron交互未验收。

## 源码行为

| 操作 | 当前处理 | 请求与状态 |
| --- | --- | --- |
| 普通wheel/触控板纵向wheel | handler直接返回，不preventDefault；ECharts zoomOnMouseWheel和moveOnMouseWheel均false | 不产生viewport-change，不发窗口查询 |
| Shift+wheel，鼠标在绘图区 | host局部非passive监听；containPixel校验后convertFromPixel取得锚点，才preventDefault | 提交共享窗口，180ms合并后按当前AP/Radio/scope查询 |
| Shift+wheel，鼠标在图外 | 不接管、不preventDefault | 不提交窗口 |
| 任意图datazoom/时间轴拖动 | 读取真实startValue/endValue或domain百分比 | 同步全图；silent和applying防反馈循环 |
| 普通指针移动 | 同步所有图pointer | 不查数据库 |
| Ctrl移动选时 | 80ms合并到最新请求时间 | 完整窗口索引二分查最近ACTIVE非零采样；否则nearest_time窗口查询 |
| Shift左键任意横坐标 | 像素转换毫秒时间，固定选择 | 各图selectedTime与右详情一致，Esc解锁 |
| 窗口排除当前选点 | focus clamp到新窗口后重新定位 | 只在新窗口定位，旧请求取消/旧generation不可覆盖 |

当前Shift wheel比例：`deltaY < 0`时窗口宽度×1.25；`deltaY > 0`时×0.8，范围限制在domain内并保留鼠标锚点比例。该方向与11.3任务书“向上放大时间范围、向下缩小时间范围”对应；最终真实设备手感仍待验收。

## 自动化用例审查

`MeshMetricChart.test.ts` 包含：

- 普通wheel不defaultPrevented、无viewport-change、ECharts默认wheel关闭。
- Shift wheel在绘图区preventDefault，按像素时间生成窗口；图外不接管，缩放不越domain。
- 百分比/显式datazoom转实际时间，共享窗口和指针silent更新无回路。
- 任意Shift click、Ctrl movement、Esc和离开固定指针行为。
- lazy初始化、ECharts finished才完成、旧render不完成新render、独立图完成和失败重试。
- resize复用实例，卸载清除native/ECharts/ZRender监听、Observer和实例。

`MeshPhase11Workbench.test.ts` 实跑31/31通过，相关场景：

- 十二图共享domain/window、按可见范围加载并复用八组指标，每张完成后独立可用；受控Observer测试覆盖不可见图不查、进入可见区才查。
- 180ms窗口合并，最终窗口用于全部指标/历史请求；另有当前选点重定位请求。
- 普通指针同步不查询；确切AP、射频口、角色、零链路和范围条件传递。
- 慢请求缓存优先显示，旧finished不覆盖QUERYING；失败单指标重试。
- 80ms选时合并、毫秒最近点、过滤STANDBY/零链路、Shift固定/解锁。
- 新时间进入节流窗口即取消旧nearest请求；旧结果不覆盖、同时间命中缓存。
- 空ACTIVE结果与查询失败分开，失败后可重试；页面关闭取消请求和timer。
- 变更窗口后当前选点越界重新定位到窗口内。

## 实测边界与待完成项

happy-dom事件测试不能产生真实浏览器页面滚动，所以没有用单测假称scrollY已变化。完整Renderer1505项及TypeScript/Vite构建已通过。真实Electron启动被自动审批以`blocked by policy`拒绝；以下没有实际证据：

1. 图上普通wheel与触控板惯性滚动前后真实scrollY。
2. Shift缩放时页面不意外位移、鼠标实际锚点和12图视觉同步。
3. slider拖动与Tooltip时间指针同步的真实画面。
4. 大型真实日志首次绘图耗时、布局稳定性和取消操作的实际体感。

恢复runtime后记录操作前后scrollY、各图data-window-start/end、pointer、选中采样、AP/Radio、请求数及真实截图，才能将这些项目改为GUI_PASS。
