# 图表分段加载

日期：2026-11-08
分支：`codex-A/mesh-analysis-performance-optimization`
对照基线：`37b0df95a3208d0d03380e76ccfe5419af1422f1`

`meshLoadingPolicy.ts`：有效记录数 <=50,000 首开 full；>50,000 或未知首开 overview。保留用户显式 full。overview 全时间域保持概览，用户缩放局部窗口改为 high，恢复全域回到 overview；小数据/显式 full 主线仍由本地 DataZoom 裁剪。

复用原 full/high/overview、点数预算、时间窗口、LOD、极值/异常/切换/缺口锚点；没有引入抽样取每N点或修改底层降采样。窗口批次使用同 session/Radio/time/generation；Abort、last-wins、成组发布、失败保留旧图和当前有效 viewport 均沿用。缓存 key 保留来源/Radio/窗口/精度和 revision，有界淘汰；切换/卸载释放。

原轨旁图按可见性初始化、一个容器一个 ECharts、Resize/KeepAlive/dispose、时间缺口/null、Tooltip 和共享 viewport 基础设施保留。本次没有重写共享动态图实现。AP和单链路统计、Excel报告读取完整数据，不使用显示点。

UI 新增紧凑七卡（物理AP总数、四类信号/置信度、未识别、单链路），保持深色tokens，点击后对话框加载分页；没有增加独立导航Tab。明细请求失败保留已显示结果。

浏览器验证使用真实源码组件+基准DTO，模拟API身份摘要，三个视口1920×1080/2560×1440/1920×1080 deviceScaleFactor1.25；记录fetch到两次RAF的组件可绘制时间。该口径包含JSON解码/图表准备，但不含真实Backend网络/完整Electron启动。deviceScaleFactor不是Windows原生125%缩放；未完成原生DPI和全套动态图人工门，须保留验收缺口。
