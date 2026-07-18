# Web 路由

本目录定义页面路由、Feature Guard 和路由级导航边界。路由只负责页面进入条件与布局挂载，不实现 API、数据库或业务状态机。

主要入口为 `index.ts`、`routes.ts` 与 `featureGuard.ts`；新增路由需接入 Feature Registry 和 i18n。使用路由测试验证启用、隐藏和回退行为。
