# Web 路由

本目录定义页面路由、Feature Guard 和路由级导航边界。路由只负责页面进入条件与布局挂载，不实现 API、数据库或业务状态机。

主要入口为 `index.ts`、`routes.ts` 与 `featureGuard.ts`；新增路由需接入 Feature Registry 和 i18n。正常业务路由还需声明短标签标题 `meta.tabTitle`，未声明时仅回退完整 `meta.title`；需要缓存的页面显式声明 `meta.keepAlive` 与具名组件 `meta.cacheComponentName`。隐藏路由、重定向中间路由和独立任务窗口不进入主窗口标签栏。使用路由测试验证启用、隐藏、标签元数据和回退行为。
