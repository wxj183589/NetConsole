# Web 导航注册

本目录维护 Web 一级模块、页面入口和导航元数据，负责把 Feature key 与可见导航关联。它不实现页面业务或设备请求。

主要入口是 `registry.ts`；测试验证注册表与 Feature Registry 的一致性。增加页面前登记 Feature key、i18n 文本和路由，再运行导航测试。
