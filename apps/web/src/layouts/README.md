# Web 应用布局

本目录承载唯一应用外壳 `AppLayout.vue`，负责导航、顶部状态、主工作区和 RouterView 宿主，不实现设备、任务或数据业务规则。

侧栏、顶部栏、滚动条和路由页面宽度由 `../styles/main.css` 消费 `../theme/` 的语义 Token。浅色与深色必须同时覆盖完整外壳；不得恢复固定深色侧栏。主工作区和直接路由根节点使用流式宽度，2K/4K 最大化时利用全部可用空间，850px 以下收缩 gutter 并保持宽表可横向滚动。

布局状态仅在 `sessionStorage` 保存侧栏折叠、展开组和轻量页面标签清单。`openPageTabs` Store 只持久化路由名、路径、短标题、导航 ID、顺序和当前标签，不保存页面组件、API payload、文件路径或图表数据；主题持久化仍由系统设置 API 负责。

`OpenPageTabs.vue` 负责已打开页面、激活、关闭和溢出操作，`AppRouteView.vue` 只按路由 `meta.keepAlive` 与 Store 生成的组件名 include 清单缓存实例。普通页面可以保留标签但离开即卸载；关闭 KeepAlive 标签会从 include 清单移除组件名并触发实际卸载。修改布局后运行 `AppLayout.test.ts`、`AppLayout.openPageTabs.integration.test.ts` 和主题架构 Guard。
