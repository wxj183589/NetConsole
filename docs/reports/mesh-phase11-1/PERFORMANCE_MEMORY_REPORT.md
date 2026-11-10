# 性能与内存观察

2026-11-09；真实 Electron；1920×1080；宁波地铁12号线108700条有效记录。结论：PASS_WITH_LIMITATIONS。本轮连续操作未复现异常退出，不能据此声称已根治 OOM。

## 实施措施

- 时间窗、AP、Radio、角色过滤在后端查询执行，默认监控最近5分钟。图表响应每组最多1000个采样预算；保留极值、空缺、计数器重置和角色/身份边界，边界过密明确报错。
- 游标流式读取，不把整会话所有记录复制给八个图表；计数器先分链路差分再采样。
- 前端请求去重、AbortController、generation及180ms缩放防抖；旧结果不覆盖新窗口。
- 缓存最多16项；缓存先显示并刷新。八组独立请求，视口外延迟绘制；一张图失败不阻塞其他图。
- 图表实例、事件和Observer在销毁时释放。真实离页容器/数据组为0，返回每图一个Canvas。

## 同一进程观察

原始数据见 `memory-observations.json`，含多个运行进程。下表仅比较 Browser PID56400、Renderer Tab PID44004；working set原始单位KiB，转MiB；JS heap原始字节转MiB。未强制GC，不将工作集下降直接等同于泄漏已消失。

| 操作阶段 | Renderer工作集 MiB | JS heap MiB |
| --- | ---: | ---: |
| 页面初始 final-page-initial | 500.3 | 228.3 |
| 八图完成 final-eight-charts | 692.9 | 322.1 |
| 时间轴操作 final-timeline-drag | 803.7 | 310.2 |
| 12次AP切换 final-repeated-ap-12 | 467.4 | 88.9 |
| 工作区图表销毁 final-charts-disposed | 461.3 | 99.9 |
| 工作区返回 final-leave-reenter | 458.5 | 70.9 |
| 真实Dashboard导航 actual-navigation-left | 332.6 | 65.7 |
| 真实MESH标签返回 actual-navigation-reentered | 330.3 | 65.9 |

工作区切换和应用导航分别取证。旧 `final-route-left/reentered` 标签对应的router脚本没有真正离页，不用于生命周期通过结论。真实Dashboard导航证据见 `actual-navigation-lifecycle.json`。

## 观察结论

八图和时间操作时工作集上升，后续12次AP切换及离页后明显回落，本轮未观察到随这组操作持续单调增长。缓存实测16项，返回后无重复Canvas，未出现异常退出。单次真实计数器窗口API请求802.74ms，仅为样本耗时，不作为总体延迟基准。

原始记录中旧Renderer进程曾达到约1041.7MiB，保留该证据；不能与新PID的低值直接比较以宣称优化收益或OOM根治。未做数小时长稳/压力、人工慢查询和真实故障注入；完整范围查询及大量LinkCnt=0归档扫描仍可能耗时，取消前端请求也不保证停止已进入后端的同步SQL/raw扫描。

## 剩余限制

主监控八组查询目前并发发起，视口外仅延迟绘制，未做到每图进入视口才查询。完整展开/收起级别的查询懒加载属于此前加载要求的剩余项，未虚报通过。没有服务端阶段进度流，后端差分/降采样仍归入请求等待，前端只对实际适配阶段显示PROCESSING。正式OOM验收仍需长时间真实使用观察；本轮结果不替代现场或Release门。
