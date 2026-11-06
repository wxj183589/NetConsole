# Ground Unattended V2 文件审计（2026-11-07）

## 1. 基线与结论

**PASS（源码/隔离自动化范围）**。起始清单 `.local/ground-v2-final-audit/baseline-112.json` 共112个文件，均存在。按起始 SHA-256 比较，17个包含本轮修复/回归调整，95个字节未变。此处“本轮修复”只描述审计开始后变化，不能将原112文件归为本轮新开发。

当前 main / `9031d00017cecf8802f34a96f136bbf01007d862`；未commit/push/merge。新增 `scripts/dev/ground_v2_soak.py` 及5份审计报告不属于原112台账。最终118个dirty路径。没有覆盖起始工作成果。

审计覆盖职责/调用方、重复实现/废弃入口、调试临时内容、不安全默认值/路径、异常处理/吞噬、资源释放、前后端DTO、API使用方及配置/存储登记。未发现需要本轮无关清理的文件；共享基础资料、人工Online MR、AC、fping、Export、Feature/i18n改动都是V2直接消费者。发现的故障见缺陷登记；不借审计删除旧raw/目录或恢复已退役架构。现存raw/索引故障采用health显式暴露，不能把所有异常catch视为吞噬。

每项“证据”表示其所属套件/消费者链验证，**不表示112个文件各自都有独立专项测试，也不表示所有分支均被覆盖**。完整FULL在收尾前启动，最后变更由定向回归/build/浏览器验证；原生和长时缺口见主报告。

## 2. 分类统计

| 分类 | 数量 | 审核边界 |
| --- | ---: | --- |
| Python Backend | 26 | Service/Supervisor/DTO/API/共享适配 |
| Electron Main | 0 | 原112中无Main/Preload变更；仍做生命周期契约回归 |
| Renderer | 29 | 页面/组件/上下文/API/type/i18n |
| Database | 3 | Repository/schema/index及storage登记 |
| Tests | 44 | Python/Vitest/视觉E2E/Fixture |
| Documentation | 6 | canonical规则/实现说明/交付/导航 |
| Other | 4 | Feature版型及架构登记 |

证据键：P=FULL Python 5458 passed/2 skipped；G=最后Ground+关联消费者453 passed/1 skipped；R=Renderer193文件/1367项及typecheck/build；Q=最后Quick两文件10项及chart1项；V=六浏览器配置12项；H=历史/Repository/raw/hash/CRC完整性回归；A=架构12/12；D=文档路径guards22项与新报告链接检查。详细日志见主报告；P/G等存在重叠，不能相加算唯一测试数。

## 3. 原112文件逐项台账

哈希为磁盘原始字节SHA-256，不受Git diff展示方式影响。“否”表示相对审计起始未变，不表示相对HEAD没有V2改动。

| # | 路径 | 分类 | 职责/检查点 | 实际检查证据 | 本轮变动 | 起始SHA-256 | 当前SHA-256 |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | `apps/desktop_renderer/src/api/acMeshLink.test.ts` | Tests | AC Mesh 查询/刷新客户端与设备/接收时间 DTO 契约的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `5dbe772c7eb14f46587e02f305228a102cf078fafb209141498dc6be474d49e4` | `5dbe772c7eb14f46587e02f305228a102cf078fafb209141498dc6be474d49e4` |
| 2 | `apps/desktop_renderer/src/api/acMeshLink.ts` | Renderer | AC Mesh 查询/刷新客户端与设备/接收时间 DTO 契约 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `5c4c010d32a557976152018d7a3b31e2331605b73bf06f8a3df9a2d16be97efe` | `5c4c010d32a557976152018d7a3b31e2331605b73bf06f8a3df9a2d16be97efe` |
| 3 | `apps/desktop_renderer/src/api/groundUnattended.ts` | Renderer | Ground API/DTO 契约及运行、分页、Quick/历史数据映射 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `5bd46ac8e1a2fdb9d58449bc3862fcbc22503d4adad172c360cb3e9941a43455` | `5bd46ac8e1a2fdb9d58449bc3862fcbc22503d4adad172c360cb3e9941a43455` |
| 4 | `apps/desktop_renderer/src/components/ground-unattended/QuickPingChart.vue` | Renderer | Quick 单实例图表、异步挂载/卸载与 Toolbox 注册 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 是 | `146ced1437d3d78c6e3ee5ea82fcb1e9ba73b29852a858086713af4115ffa32c` | `0a5d5e5c6434c7cef8914e21da7b6f073c6944a445fccd1be867f712a6c648a2` |
| 5 | `apps/desktop_renderer/src/components/ground-unattended/quickPingChartOptions.test.ts` | Tests | RTT ms/丢包%双轴、真实 null 缺口、局部 grid 与缩放选项的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `3a10a5d25f47b57f0700b77760a5738ed86aa27a541b9ceba07efe0c47edca25` | `3a10a5d25f47b57f0700b77760a5738ed86aa27a541b9ceba07efe0c47edca25` |
| 6 | `apps/desktop_renderer/src/components/ground-unattended/quickPingChartOptions.ts` | Renderer | RTT ms/丢包%双轴、真实 null 缺口、局部 grid 与缩放选项 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 是 | `40eaf3fc4f54ae32685c39e1b85e02ad470368d5dddb07bf32b0634e4560c698` | `7dd861d0b7839a3dd924e8831aa99fb09ff1ebf231c72880cd69df8159e319fa` |
| 7 | `apps/desktop_renderer/src/i18n/groundUnattended.ts` | Renderer | 十页完整中英文词条、参数/状态/单位和动态语言切换 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `443a181b111d1e90f44b876312ebb157bce4cfb1bd16e6c9fafa9fc8133f798f` | `443a181b111d1e90f44b876312ebb157bce4cfb1bd16e6c9fafa9fc8133f798f` |
| 8 | `apps/desktop_renderer/src/i18n/runtime.test.ts` | Tests | 已有 i18n runtime 注册 Ground 翻译与切换通知的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `c6b72e1f29d7385cc5956d1e0566b26bf30136f641e1aed68c61226dc4d623fa` | `c6b72e1f29d7385cc5956d1e0566b26bf30136f641e1aed68c61226dc4d623fa` |
| 9 | `apps/desktop_renderer/src/i18n/runtime.ts` | Renderer | 已有 i18n runtime 注册 Ground 翻译与切换通知 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `64e59d4859c7e0fb6e2e1ceb27e11413769d45e0eab8b8adccf4aef457171bf0` | `64e59d4859c7e0fb6e2e1ceb27e11413769d45e0eab8b8adccf4aef457171bf0` |
| 10 | `apps/desktop_renderer/src/navigation/registry.test.ts` | Tests | 现有导航登记/旧入口收敛及 Feature 可见性的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `0629eaa9279811608de46edd3c23a348b1dd4a5f73a7d33b37ba9be87a1ca190` | `0629eaa9279811608de46edd3c23a348b1dd4a5f73a7d33b37ba9be87a1ca190` |
| 11 | `apps/desktop_renderer/src/navigation/registry.ts` | Renderer | 现有导航登记/旧入口收敛及 Feature 可见性 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `dde49d5b2206a147947034bdaefa8dbd4236ed87708f5115146bcbddb6a62260` | `dde49d5b2206a147947034bdaefa8dbd4236ed87708f5115146bcbddb6a62260` |
| 12 | `apps/desktop_renderer/src/platform/exportActionRegistry.ts` | Renderer | 历史 CSV 固定导出动作接入既有 Export 协调器 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `0838281b5a0a06306894acaf6c4a93e82a5ca00a8438f0a147b9a50398f35a3b` | `0838281b5a0a06306894acaf6c4a93e82a5ca00a8438f0a147b9a50398f35a3b` |
| 13 | `apps/desktop_renderer/src/platform/exportEntryAudit.test.ts` | Tests | 导出入口登记与用户文件交互约束的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `ebc102e4884626a656425484f6af952a5c257782bb3cad83e847c1336cf9fde2` | `ebc102e4884626a656425484f6af952a5c257782bb3cad83e847c1336cf9fde2` |
| 14 | `apps/desktop_renderer/src/router/index.test.ts` | Tests | 路由入口/旧路由兼容与 Feature 限制的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `3a170280df85a61fd38b7695dfd6afadc904a7e9413debe5adb2ef87869a73a1` | `3a170280df85a61fd38b7695dfd6afadc904a7e9413debe5adb2ef87869a73a1` |
| 15 | `apps/desktop_renderer/src/router/routes.ts` | Renderer | Ground 真实页面路由及旧入口重定向 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `ca17304f2578036a688eb99125763119c378d0a7cd250ff9baa0cb05b9d92053` | `ca17304f2578036a688eb99125763119c378d0a7cd250ff9baa0cb05b9d92053` |
| 16 | `apps/desktop_renderer/src/types/acMeshLink.ts` | Renderer | AC Mesh 查询/刷新客户端与设备/接收时间 DTO 契约 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `0af93673b2d881b99074f659508b3de6962e8f0560f473446d9202ced7b96767` | `0af93673b2d881b99074f659508b3de6962e8f0560f473446d9202ced7b96767` |
| 17 | `apps/desktop_renderer/src/types/groundUnattended.ts` | Renderer | Ground API/DTO 契约及运行、分页、Quick/历史数据映射 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `56801076a9ccd6327fd011293fb9c8aa51b102e6a4f3a3348f7b174b090ee1cd` | `56801076a9ccd6327fd011293fb9c8aa51b102e6a4f3a3348f7b174b090ee1cd` |
| 18 | `apps/desktop_renderer/src/types/railTransitBaseData.ts` | Renderer | 基础资料备用地址监测策略 DTO，与 MR UUID 对齐 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `bf4879a6bf3e8f259fe66ef3bba8386b8e218c6c811a7da14a4f4c84a75f0192` | `bf4879a6bf3e8f259fe66ef3bba8386b8e218c6c811a7da14a4f4c84a75f0192` |
| 19 | `apps/desktop_renderer/src/views/rail-transit/AcMeshLinkPage.vue` | Renderer | AC 数据查询/刷新、设备时间、接收时间和 freshness 展示 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `d858f4cc4ba9a975cb5a43f7fe46bce5eee6e180ccf243693532c28ad04d805f` | `d858f4cc4ba9a975cb5a43f7fe46bce5eee6e180ccf243693532c28ad04d805f` |
| 20 | `apps/desktop_renderer/src/views/rail-transit/ArchivePage.test.ts` | Tests | 历史索引分页筛选排序/CSV 导出与归档结果入口的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `ddc220d356c045ecac8a382f8098ee063bff3920b74a942e6987a2fa60540d7c` | `ddc220d356c045ecac8a382f8098ee063bff3920b74a942e6987a2fa60540d7c` |
| 21 | `apps/desktop_renderer/src/views/rail-transit/ArchivePage.vue` | Renderer | 历史索引分页筛选排序/CSV 导出与归档结果入口 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `b994451ab024ecf3043894e6af32eb51324492b53ac8774bb20f2fbcaf137286` | `b994451ab024ecf3043894e6af32eb51324492b53ac8774bb20f2fbcaf137286` |
| 22 | `apps/desktop_renderer/src/views/rail-transit/DeepCollectionPage.vue` | Renderer | 既有深采会话、队列、失败和停止状态展示 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `3af3cdfca3712c7963c4f38b8d5cf7da29b139f10453ae6d186fa764dfb73d4c` | `3af3cdfca3712c7963c4f38b8d5cf7da29b139f10453ae6d186fa764dfb73d4c` |
| 23 | `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.behavior.test.ts` | Tests | 十页父壳、运行操作和公共上下文，不承载业务状态机的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `3c8d0ab6ef4f6333255a43b4451c71ed42266b13aed632ae7f8893631d84c0c8` | `3c8d0ab6ef4f6333255a43b4451c71ed42266b13aed632ae7f8893631d84c0c8` |
| 24 | `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.test.ts` | Tests | 十页父壳、运行操作和公共上下文，不承载业务状态机的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `5bdf33cd2d441a7fe8863cd202350dabeb623ac5bf6e823347fae8849107f1fc` | `5bdf33cd2d441a7fe8863cd202350dabeb623ac5bf6e823347fae8849107f1fc` |
| 25 | `apps/desktop_renderer/src/views/rail-transit/GroundUnattendedView.vue` | Renderer | 十页父壳、运行操作和公共上下文，不承载业务状态机 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `5e5777d89ddc9b3ea0defe35898c5e019d869b7174fbd7676545f5b5c6972216` | `5e5777d89ddc9b3ea0defe35898c5e019d869b7174fbd7676545f5b5c6972216` |
| 26 | `apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.test.ts` | Tests | MR/整车状态、双 IP 详情抽屉及 Quick 跳转的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `f22cbc38c8112706ddd0349adbd90ebf0a1d82eead28f3016b9a94c87a96a030` | `f22cbc38c8112706ddd0349adbd90ebf0a1d82eead28f3016b9a94c87a96a030` |
| 27 | `apps/desktop_renderer/src/views/rail-transit/HeartbeatPage.vue` | Renderer | MR/整车状态、双 IP 详情抽屉及 Quick 跳转 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `67402b87f72748fddaece2e205585acb50b068d463462eda2154a176837f49de` | `67402b87f72748fddaece2e205585acb50b068d463462eda2154a176837f49de` |
| 28 | `apps/desktop_renderer/src/views/rail-transit/MeshAnalysisView.test.ts` | Tests | 必要共享消费者：MESH/Ground 入口和图表行为兼容的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `cccf56e2f9168e773c2a806a8eb77a5c7a44260feb739e255ea595a0cd997e96` | `cccf56e2f9168e773c2a806a8eb77a5c7a44260feb739e255ea595a0cd997e96` |
| 29 | `apps/desktop_renderer/src/views/rail-transit/MeshAnalysisView.vue` | Renderer | 必要共享消费者：MESH/Ground 入口和图表行为兼容 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `751a56aa03767475b42f82b101abb9b8becd81ee81420158f2702eb10c3a8daa` | `751a56aa03767475b42f82b101abb9b8becd81ee81420158f2702eb10c3a8daa` |
| 30 | `apps/desktop_renderer/src/views/rail-transit/OverviewPage.vue` | Renderer | 运行、MR/车辆计数与近期事件展示 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `199f513ee9eb842a1f5864331b44ee250c95d9b342a61ea0558377a6c11f56a0` | `199f513ee9eb842a1f5864331b44ee250c95d9b342a61ea0558377a6c11f56a0` |
| 31 | `apps/desktop_renderer/src/views/rail-transit/QuickPingPage.test.ts` | Tests | 目标选择、参数、run 启停、样本轮询及终态按钮保护的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 是 | `8b1e5bb6e4b4ae31cbe0a3930d33f1165077d8d6091215f4c336f5be79924713` | `63984fbfceb97a9e93e97f29656485e6ae19e729a9d596c63a6c82132eae677b` |
| 32 | `apps/desktop_renderer/src/views/rail-transit/QuickPingPage.vue` | Renderer | 目标选择、参数、run 启停、样本轮询及终态按钮保护 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 是 | `6dfe0d4e82dba53530bcbfed6f94fc4c391197bc8333ee12bde688ecd9d45681` | `a253d469c4051e4780b0f529dac9869c6214682408c31b0d00600fb3ace5b6ad` |
| 33 | `apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.test.ts` | Tests | MR 备用地址策略编辑和既有基础资料保存流程的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `4c906353eb026313da6a6b891d2bb2626b7c01132ab2fd7f31a4e7b18a4fa27b` | `4c906353eb026313da6a6b891d2bb2626b7c01132ab2fd7f31a4e7b18a4fa27b` |
| 34 | `apps/desktop_renderer/src/views/rail-transit/RailTransitBaseDataView.vue` | Renderer | MR 备用地址策略编辑和既有基础资料保存流程 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `5f3e4f5cce0fc0c557f03ca223c7363f837f0cb1a17f6e2ca1051b6d13b6ec61` | `5f3e4f5cce0fc0c557f03ca223c7363f837f0cb1a17f6e2ca1051b6d13b6ec61` |
| 35 | `apps/desktop_renderer/src/views/rail-transit/SettingsPage.locale.test.ts` | Tests | 既有 Profile 参数、窗口与运行策略保存/校验的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `b8339e3b75c29e7d8d984b2640b2d7277daec30390ff613152ea23625ae88547` | `b8339e3b75c29e7d8d984b2640b2d7277daec30390ff613152ea23625ae88547` |
| 36 | `apps/desktop_renderer/src/views/rail-transit/SettingsPage.vue` | Renderer | 既有 Profile 参数、窗口与运行策略保存/校验 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `2e47bc79fa945f39d8b7859744f739e2c7bc09b5eb4f42098c8f8dad40284e26` | `2e47bc79fa945f39d8b7859744f739e2c7bc09b5eb4f42098c8f8dad40284e26` |
| 37 | `apps/desktop_renderer/src/views/rail-transit/SyslogPage.locale.test.ts` | Tests | 全模块日志查询、服务端筛选分页、原文/详情的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `dee47735eb9b6161fcfbd519f8bf1da6e9f6a6b53def446ab1b617e28983ae6f` | `dee47735eb9b6161fcfbd519f8bf1da6e9f6a6b53def446ab1b617e28983ae6f` |
| 38 | `apps/desktop_renderer/src/views/rail-transit/SyslogPage.vue` | Renderer | 全模块日志查询、服务端筛选分页、原文/详情 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `6a3942c7174b9a710b77f17b3dd9ebf1d8f8be4fa63cc8d1eabe4d3689af9f8c` | `6a3942c7174b9a710b77f17b3dd9ebf1d8f8be4fa63cc8d1eabe4d3689af9f8c` |
| 39 | `apps/desktop_renderer/src/views/rail-transit/SystemHealthPage.test.ts` | Tests | 引擎/队列/存储等健康与设备可达状态分离的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `ccee1f0de906867cf59f7b6ff1ea596b2681f5f5adf24b15874acef97f44b89d` | `ccee1f0de906867cf59f7b6ff1ea596b2681f5f5adf24b15874acef97f44b89d` |
| 40 | `apps/desktop_renderer/src/views/rail-transit/SystemHealthPage.vue` | Renderer | 引擎/队列/存储等健康与设备可达状态分离 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `e1adbf0004abc32344ed7019153defd5afa49d1cb0bf8d0d4da60a5f7d265447` | `e1adbf0004abc32344ed7019153defd5afa49d1cb0bf8d0d4da60a5f7d265447` |
| 41 | `apps/desktop_renderer/src/views/rail-transit/TimelinePage.vue` | Renderer | 心跳/Syslog/AC 时间轴筛选与设备/接收时间 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `0cd082a91419d46f2d45350a8e48a1b75a0b334214d36dd5f9ce30c0200f32f2` | `0cd082a91419d46f2d45350a8e48a1b75a0b334214d36dd5f9ce30c0200f32f2` |
| 42 | `apps/desktop_renderer/src/views/rail-transit/groundFeatures.ts` | Renderer | Ground 页面/操作 Feature 标识及可见性适配 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `fc14016715e27cef6df11f56318d388f456c239d3d8f90ab827742b306c3fad6` | `fc14016715e27cef6df11f56318d388f456c239d3d8f90ab827742b306c3fad6` |
| 43 | `apps/desktop_renderer/src/views/rail-transit/groundUnattended.css` | Renderer | 十页剩余高度、滚动和局部布局 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `bcba94ef7007a5195cc48e4e2c6e9a1acc18ab1811c5398bdacb6eb51d5edce9` | `bcba94ef7007a5195cc48e4e2c6e9a1acc18ab1811c5398bdacb6eb51d5edce9` |
| 44 | `apps/desktop_renderer/src/views/rail-transit/groundUnattendedLabels.test.ts` | Tests | 枚举与可达端含义的本地化标签的回归测试 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `dfb09d143b2861e1beb4acf5741e8dde877dacd1bd4db63baed6df249fc09e7a` | `dfb09d143b2861e1beb4acf5741e8dde877dacd1bd4db63baed6df249fc09e7a` |
| 45 | `apps/desktop_renderer/src/views/rail-transit/groundUnattendedLabels.ts` | Renderer | 枚举与可达端含义的本地化标签 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `63bfd93ff07287ae5cafc0b6a06a85268309be7b74f10b6e43345cdd5b2f7881` | `63bfd93ff07287ae5cafc0b6a06a85268309be7b74f10b6e43345cdd5b2f7881` |
| 46 | `apps/desktop_renderer/src/views/rail-transit/useGroundUnattended.ts` | Renderer | 公共上下文、Abort/generation/防重入与页面轮询生命周期 | R；十页链路 V（适用页面）；Quick 最后定向 Q（适用文件） | 否 | `423f21a32f75fbc788f3cbe28ed4faf2e7a605bb1dbd86c5b77132fa72682856` | `423f21a32f75fbc788f3cbe28ed4faf2e7a605bb1dbd86c5b77132fa72682856` |
| 47 | `apps/desktop_renderer/tests/visual/README.md` | Tests | 视觉 Fixture 启动/配置和证据边界 | V；R/typecheck/build；HTTP mock 边界 | 否 | `1112cc321b6346df9ecce17d5c06008c5d1c2032d25d9d76e9bcb9f48f300325` | `1112cc321b6346df9ecce17d5c06008c5d1c2032d25d9d76e9bcb9f48f300325` |
| 48 | `apps/desktop_renderer/tests/visual/VisualGroundFixture.vue` | Tests | 视觉测试挂载真实 Ground 页面，HTTP mock 边界 | V；R/typecheck/build；HTTP mock 边界 | 否 | `98a68453867bd12f83bca2faccf026934e3cd4bf9701d1c93e3a0dbd60456b60` | `98a68453867bd12f83bca2faccf026934e3cd4bf9701d1c93e3a0dbd60456b60` |
| 49 | `apps/desktop_renderer/tests/visual/e2e/ground-unattended.visual.spec.ts` | Tests | 六浏览器配置十页/抽屉/Quick/分页及 ECharts 错误验收 | V；R/typecheck/build；HTTP mock 边界 | 是 | `2aebee872e717c0ceaeb477ce00a47a0000ab3e563a93ffeb88c8e8a2c90f618` | `a6b984473455f97410a44874b08e012e80e2957bcb3d91a4ec789b21d4610123` |
| 50 | `apps/desktop_renderer/tests/visual/ground-main.ts` | Tests | 视觉 Fixture Vite 启动入口 | V；R/typecheck/build；HTTP mock 边界 | 否 | `0363e99361577e0ac6e291aa4097b77e9828106c4fea06abde7c1f24888d4c16` | `0363e99361577e0ac6e291aa4097b77e9828106c4fea06abde7c1f24888d4c16` |
| 51 | `apps/desktop_renderer/tests/visual/ground.html` | Tests | 视觉测试专用 HTML 挂载入口 | V；R/typecheck/build；HTTP mock 边界 | 否 | `2aa495314749b2055c86a6bedff74bc4ae12f5eeda10c40cf698e3eee9b2f92d` | `2aa495314749b2055c86a6bedff74bc4ae12f5eeda10c40cf698e3eee9b2f92d` |
| 52 | `config/architecture/direct_sql_access.yaml` | Other | 现有 Repository SQL 和 Soak TEST_ONLY 直接 SQL 边界登记 | A；Soak TEST_ONLY 登记后复验 | 是 | `cf451d94d7656e14cfed5017da11640bf0d3b153b0ea29f045d89e2563a81293` | `d88e0a5ad612d21e64b5dfcc415dcb0893f5b003fb7cfc72ae34fc21a19ccc0c` |
| 53 | `config/architecture/ui_business_logic.yaml` | Other | 现有 UI 业务逻辑架构清单与页面边界登记 | A；P/R 的 Feature/配置契约；L4 消费者门 | 否 | `db92050321ffe14dced0e7eff5e2bed6d8ef5c80013f64f3a77d4262ccdff3ba` | `db92050321ffe14dced0e7eff5e2bed6d8ef5c80013f64f3a77d4262ccdff3ba` |
| 54 | `config/profiles/features/customer.json` | Other | Customer 版 Ground 页面/动作 Feature 配置 | A；P/R 的 Feature/配置契约；L4 消费者门 | 否 | `f521203757502fd0a3d0b540b67ea2aa3ed7cdd3dcb0abe8da042fcec0ce7e04` | `f521203757502fd0a3d0b540b67ea2aa3ed7cdd3dcb0abe8da042fcec0ce7e04` |
| 55 | `config/profiles/features/full.json` | Other | Full 版 Ground 页面/动作 Feature 配置 | A；P/R 的 Feature/配置契约；L4 消费者门 | 否 | `873af08b112f881da08cc200e1c95d5c8561465b26711f29b95bbcd8424d03e1` | `873af08b112f881da08cc200e1c95d5c8561465b26711f29b95bbcd8424d03e1` |
| 56 | `config/storage_registry.yaml` | Database | Ground 心跳/Quick 新表和原始数据根存储归属登记 | P/G；H；存储/SQL guards A | 否 | `87f1bd378dbfdabb5e88b4ec0ae4615746b90935a10908cce3cf61fa1f320b91` | `87f1bd378dbfdabb5e88b4ec0ae4615746b90935a10908cce3cf61fa1f320b91` |
| 57 | `docs/CHANGELOG.md` | Documentation | 用户可见 V2 变更记录 | D；与源码/参数和测试结果交叉核对 | 否 | `fb227f23ed2b0d1a841cd0cd674501d5124935c3f89a2027b07be73e94ad9e37` | `fb227f23ed2b0d1a841cd0cd674501d5124935c3f89a2027b07be73e94ad9e37` |
| 58 | `docs/architecture/REFACTOR_MAP.md` | Documentation | 既有架构地图同步 Ground 当前实现边界 | D；与源码/参数和测试结果交叉核对 | 否 | `85dcc415a8df09a37a67f12064daa453acc6bf3539170d69943fab21945cdcf6` | `85dcc415a8df09a37a67f12064daa453acc6bf3539170d69943fab21945cdcf6` |
| 59 | `docs/archive/ground-unattended-v2-delivery-2026-11-07.md` | Documentation | 原 V2 交付、测试及原生/设备验收缺口记录 | D；与源码/参数和测试结果交叉核对 | 否 | `b4bbcc75ef420fde541875b9b02f3e83f1dc92fe69b03e6eb0733c4c840830f7` | `b4bbcc75ef420fde541875b9b02f3e83f1dc92fe69b03e6eb0733c4c840830f7` |
| 60 | `docs/rail-transit/README.md` | Documentation | 轨道模块文档导航与旧入口收敛 | D；与源码/参数和测试结果交叉核对 | 否 | `10fa6b346b7a322b133874fd71b761f16ffdcec2716893056d746567158675aa` | `10fa6b346b7a322b133874fd71b761f16ffdcec2716893056d746567158675aa` |
| 61 | `docs/rail-transit/ground-unattended/README.md` | Documentation | Ground canonical 运行/参数/存储/恢复规则 | D；与源码/参数和测试结果交叉核对 | 否 | `44fe537ff20bd6b52dfc92c7a0dcc45c1da756902973a4a4374780de513ff09d` | `44fe537ff20bd6b52dfc92c7a0dcc45c1da756902973a4a4374780de513ff09d` |
| 62 | `src/netconsole/application/rail_transit/base_data_application_service.py` | Python Backend | 备用监测策略保存/补偿，复用既有基础资料 Service | P/G；A；API/共享消费者契约（按文件适用） | 否 | `46beb74e2c93ee6fc25abaf1c472e596fe0bd0d3c77127629f2dc4d612d03a6a` | `46beb74e2c93ee6fc25abaf1c472e596fe0bd0d3c77127629f2dc4d612d03a6a` |
| 63 | `src/netconsole/application/rail_transit/web_application_service.py` | Python Backend | 轨道 Web facade Ground/基础资料适配 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `aa8892ba6b70ecb5ea8a3493bde060e723ad9c95468d6a790607df3e922c3dd4` | `aa8892ba6b70ecb5ea8a3493bde060e723ad9c95468d6a790607df3e922c3dd4` |
| 64 | `src/netconsole/backend/api/ground_unattended_router.py` | Python Backend | DTO/Service API 映射与模块/Quick/export Feature gate | P/G；A；API/共享消费者契约（按文件适用） | 否 | `4eec389b3210538ffc3a8714eb48d7af3695f5b243f9502dd7a0fcb0d2500e11` | `4eec389b3210538ffc3a8714eb48d7af3695f5b243f9502dd7a0fcb0d2500e11` |
| 65 | `src/netconsole/backend/api/main.py` | Python Backend | FastAPI lifespan 既有 Supervisor 启动/收口接入 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `a1dc6d54b00d2e40681fabcc4c92758c2d7e834956303366a22e81f45e08e499` | `a1dc6d54b00d2e40681fabcc4c92758c2d7e834956303366a22e81f45e08e499` |
| 66 | `src/netconsole/core/feature_registry.py` | Python Backend | 唯一 Feature authority，十页与新动作登记 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `c2b5bfa3b6d7855ee8e930b5fb3707db3445dff7cf27677cd9acb35c13ac8edf` | `c2b5bfa3b6d7855ee8e930b5fb3707db3445dff7cf27677cd9acb35c13ac8edf` |
| 67 | `src/netconsole/core/i18n.py` | Python Backend | 后端 Ground 用户可见文本登记 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `f36b9523471c6949643b1ad01341860e4b3ec3ae6fa60799d197e6fc43281043` | `f36b9523471c6949643b1ad01341860e4b3ec3ae6fa60799d197e6fc43281043` |
| 68 | `src/netconsole/core/ping/fping_v5_runner.py` | Python Backend | 共享 fping 可选全局发包间隔与参数执行层兼容 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `9bd4e4fc0d8358deb516888b07469df0e3346b319a07a758c4bcd31f253e0d2b` | `9bd4e4fc0d8358deb516888b07469df0e3346b319a07a758c4bcd31f253e0d2b` |
| 69 | `src/netconsole/models/api/ac_mesh_link.py` | Python Backend | AC API 设备时间/接收时间与新鲜度模型 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `9b3031bf11a56a614bd91400e73c864aff36c66f4bfdf1f6238aa6f5c1ff843a` | `9b3031bf11a56a614bd91400e73c864aff36c66f4bfdf1f6238aa6f5c1ff843a` |
| 70 | `src/netconsole/models/api/ground_unattended.py` | Python Backend | Ground Profile/心跳/Quick/健康/历史请求响应模型 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `67dcccdec5811a29239d3c6ae79fce5179746be22aa62d07a1e8c4b58709a9b4` | `67dcccdec5811a29239d3c6ae79fce5179746be22aa62d07a1e8c4b58709a9b4` |
| 71 | `src/netconsole/models/api/rail_transit_base_data.py` | Python Backend | 基础资料备用地址监测策略模型及参数校验 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `97cc8a1f9d98bc8f7d5714042d7110cab1a320f75d0c237dd6e943805c25c1c8` | `97cc8a1f9d98bc8f7d5714042d7110cab1a320f75d0c237dd6e943805c25c1c8` |
| 72 | `src/netconsole/repositories/ground_unattended_repository.py` | Database | 既有 Ground SQLite schema/index、快照/Quick/run/event/raw 索引持久化 | P/G；H；存储/SQL guards A | 否 | `55278c231a8d925ccee3bff1405858e38a64aa3c614019540af66293f93d4e62` | `55278c231a8d925ccee3bff1405858e38a64aa3c614019540af66293f93d4e62` |
| 73 | `src/netconsole/repositories/rail_transit_base_data_repository.py` | Database | site_meta 备用监测策略读写，保留原表兼容 | P/G；H；存储/SQL guards A | 否 | `06ae53ae0c307babd6fcf415ef782be5d893f35bc2cd4b02274ff60d1c1f5dc7` | `06ae53ae0c307babd6fcf415ef782be5d893f35bc2cd4b02274ff60d1c1f5dc7` |
| 74 | `src/netconsole/services/ac/mesh_link_query_service.py` | Python Backend | AC 查询 freshness 分级和双时间字段投影 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `ff49cff4573de56a66a663843022ce16dc3b1e2486c650ff8e4514a923fae459` | `ff49cff4573de56a66a663843022ce16dc3b1e2486c650ff8e4514a923fae459` |
| 75 | `src/netconsole/services/export/export_handlers.py` | Python Backend | 既有独立 Export Worker 的 Ground 历史 CSV handler | P/G；A；API/共享消费者契约（按文件适用） | 否 | `48d34a01badb9958194c35cf2ab8dcda20cce1e7469690f7e4b22323aae6d2d0` | `48d34a01badb9958194c35cf2ab8dcda20cce1e7469690f7e4b22323aae6d2d0` |
| 76 | `src/netconsole/services/ground_unattended/README.md` | Documentation | Ground Service/Supervisor 与组件边界 | D；与源码/参数和测试结果交叉核对 | 否 | `9c47f7b4bccd3cb7b413d68a1c977fe5a41df3b4b651fa82ca285a2f89aaf6b3` | `9c47f7b4bccd3cb7b413d68a1c977fe5a41df3b4b651fa82ca285a2f89aaf6b3` |
| 77 | `src/netconsole/services/ground_unattended/application_service.py` | Python Backend | Ground 应用编排/查询，当前库存过滤与历史事实保留 | P/G；A；API/共享消费者契约（按文件适用） | 是 | `7e8e8585a93a619819595e417960f2c21c0d53681982bdd5e30b95dca5c510aa` | `4e9e186f55d3c389af77b6d728e962dc43b3162ee528f3b9ea2982bb06fd4a20` |
| 78 | `src/netconsole/services/ground_unattended/eligibility.py` | Python Backend | 心跳/正线/深采资格分离，未知或冲突失败关闭 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `fa3542fd344bcdbd1ce7c291dd61ea123ed1acbe85118dd937f788a6d2cba0c1` | `fa3542fd344bcdbd1ce7c291dd61ea123ed1acbe85118dd937f788a6d2cba0c1` |
| 79 | `src/netconsole/services/ground_unattended/fleet_ping.py` | Python Backend | 共享 fping 的 Ground 稳定目标/分片/采样与输出生命周期 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `3f3b658d76d0e54b75be3e577dc3367af0cd743a5c5d2f232574c1564b551196` | `3f3b658d76d0e54b75be3e577dc3367af0cd743a5c5d2f232574c1564b551196` |
| 80 | `src/netconsole/services/ground_unattended/heartbeat_state.py` | Python Backend | 逐 IP/MR/整车状态机、双端交集、采样空窗和目标重配 | P/G；A；API/共享消费者契约（按文件适用） | 是 | `877260c0d168e77d273483aea5d873ee852e38e4bbd0053c0586ba2e02ae03a5` | `ef5a9ab5ca9e734b294fbe2688cf3e97d27ef70b8f630366083385a9a210d976` |
| 81 | `src/netconsole/services/ground_unattended/history_export.py` | Python Backend | 同筛选排序的流式 CSV、BOM/公式转义及 snapshot | P/G；A；API/共享消费者契约（按文件适用） | 否 | `1f2375df496b5da0b2112088e0a4c4c86487d101758951b5b3df5c0d78824019` | `1f2375df496b5da0b2112088e0a4c4c86487d101758951b5b3df5c0d78824019` |
| 82 | `src/netconsole/services/ground_unattended/history_query.py` | Python Backend | 受限历史索引分页、稳定排序及查询预算 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `9f5613b97af12e2db4a61f302b9a28a22612220a12841fd7707cafeff5fb2b06` | `9f5613b97af12e2db4a61f302b9a28a22612220a12841fd7707cafeff5fb2b06` |
| 83 | `src/netconsole/services/ground_unattended/inventory.py` | Python Backend | 基础资料生成稳定 MR UUID/端位/合资格管理地址库存 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `57d9a7012223154596f6076e08653ac7812663f92b96c417edeb58a12d42d6f7` | `57d9a7012223154596f6076e08653ac7812663f92b96c417edeb58a12d42d6f7` |
| 84 | `src/netconsole/services/ground_unattended/quick_ping.py` | Python Backend | 独立有界诊断 run、原始分段/压缩/保留、停止及重启 INTERRUPTED | P/G；A；API/共享消费者契约（按文件适用） | 是 | `60c0b83cf202c2737efa984ca3db7bf4fdbe1a296a4c55d691fab85054ab4c35` | `d31eccd2835e0e86126b1409558aa8b3297ac99a3f0b4f29f52bc579be46d332` |
| 85 | `src/netconsole/services/ground_unattended/raw_lifecycle.py` | Python Backend | 原始数据/READY 归档生命周期，保留失败证据和路径边界 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `ba151902703681114a65ce5fe1e015661fb145f52aecaeacb9cc63623d213193` | `ba151902703681114a65ce5fe1e015661fb145f52aecaeacb9cc63623d213193` |
| 86 | `src/netconsole/services/ground_unattended/supervisor.py` | Python Backend | 后台子系统调度/恢复/停止、心跳事件有界锁外持久化 | P/G；A；API/共享消费者契约（按文件适用） | 是 | `e6cf7e165879a642b5ac3ec5cf241e06fff12f3431db7ab2bf1f4d5ef8a8aa4f` | `06602f212bc9bb9cf6f39ecfcb9f6bdfe0504d8daa3b57fcb7603986f1d1d90a` |
| 87 | `src/netconsole/services/ground_unattended/syslog_runtime.py` | Python Backend | UDP→raw→parser、Spool、fsync/metadata/gzip/重放可靠性 | P/G；A；API/共享消费者契约（按文件适用） | 是 | `d06933a150b4d7d8f99b601a730fb609a115e200d7fe1f625b036de26769002b` | `9008c0431316b4c0c023f91a5b51af8f4e58d6e28a40466d6d57a1b7c712b947` |
| 88 | `src/netconsole/services/job_center/artifact_reconciliation.py` | Python Backend | Ground 导出 Artifact 与既有 Job 归属对账 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `746a09b95ab78adddfb8dfc628bb856383010bcb9792bca158649a7e2b9efaea` | `746a09b95ab78adddfb8dfc628bb856383010bcb9792bca158649a7e2b9efaea` |
| 89 | `src/netconsole/services/rail_transit/base_data_query_service.py` | Python Backend | 基础资料查询投影 MR 备用地址监测策略 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `2d00539d31e9dd7fe4b882e3988d9a2461a2617a00fa43cf2d0f882258085a3d` | `2d00539d31e9dd7fe4b882e3988d9a2461a2617a00fa43cf2d0f882258085a3d` |
| 90 | `src/netconsole/services/vehicle_mr_online.py` | Python Backend | 必要共享消费者：人工 Online MR 目标/默认参数兼容 | P/G；A；API/共享消费者契约（按文件适用） | 否 | `540ceb7de0bda23e62d38cc596a109eb0e515ced3add05b4a0a724b7572fd8a2` | `540ceb7de0bda23e62d38cc596a109eb0e515ced3add05b4a0a724b7572fd8a2` |
| 91 | `tests/test_ac_mesh_link_query_service.py` | Tests | AC 查询、双时间、30/120/301 秒 freshness测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 是 | `51ce3e8a8712f4114ef155a8d506544924a5fc6d82a755e66f0ff3e58181bdd9` | `2afacacf991bc2bd6cffc8b8cc74fed00db3548e1cc86876c7992b12eb6e3833` |
| 92 | `tests/test_ac_mesh_link_refresh_service.py` | Tests | AC 刷新与独立数据链路兼容测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `99886708544e3bfda8e456c6073ec5e758148ae8c84ef91a9246e4a55bda3262` | `99886708544e3bfda8e456c6073ec5e758148ae8c84ef91a9246e4a55bda3262` |
| 93 | `tests/test_feature_registry_groups.py` | Tests | Feature 分组/版本与 Ground 登记测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `3a4415dc40e57fe881dcba9c92b7a67e30e8e14c3836ceff6cf2ab436c718cda` | `3a4415dc40e57fe881dcba9c92b7a67e30e8e14c3836ceff6cf2ab436c718cda` |
| 94 | `tests/test_ground_unattended_ac_resident.py` | Tests | AC 常驻/慢失败隔离、Supervisor/重启/停止/事件落库测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 是 | `1b29c0f7bd26433bf4ca37de73fa98d07851a568aa954e8c9ac0ba797bb24a89` | `b9d10e754cdf947fccb8f743ad1dec8572455e4bc8415e91d67e5c9e0abc00a6` |
| 95 | `tests/test_ground_unattended_api.py` | Tests | Ground HTTP DTO、Feature、当前库存/历史事实和 Quick API测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 是 | `f10bac263250d0c4cfc810e1c5e28adacf5a42b3a905aa535e9b62f06de67112` | `6eb535601b3cd3cdd552ab09bd8a8b095744214ddb5fe55aa2ce09ac026f8a15` |
| 96 | `tests/test_ground_unattended_eligibility.py` | Tests | 心跳与正线/深采资格边界及目标身份测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `c9519ad461377bb9e55bfca0a3e332983382041a852cc8f5f960543d7737b811` | `c9519ad461377bb9e55bfca0a3e332983382041a852cc8f5f960543d7737b811` |
| 97 | `tests/test_ground_unattended_fleet_ping.py` | Tests | fping 参数透传、分片和执行生命周期测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `8328415e14ef1f2541d77604892a8052bd6423e5fb2d439234916561ed92d5eb` | `8328415e14ef1f2541d77604892a8052bd6423e5fb2d439234916561ed92d5eb` |
| 98 | `tests/test_ground_unattended_fleet_ping_retention.py` | Tests | Fleet 有效目标和输出保留/边界测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `bb27dc3c5017c353967b7d47d5e310a2ae78dd39cb4768e14dc7a188113b3a34` | `bb27dc3c5017c353967b7d47d5e310a2ae78dd39cb4768e14dc7a188113b3a34` |
| 99 | `tests/test_ground_unattended_health.py` | Tests | 引擎/存储错误健康与设备可达性分离测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `b5beec1ede443126ed45607f3a947402fafd319ba5fb2123b303900436a294e4` | `b5beec1ede443126ed45607f3a947402fafd319ba5fb2123b303900436a294e4` |
| 100 | `tests/test_ground_unattended_heartbeat_state.py` | Tests | 双 IP、阈值交集、恢复、空窗、身份冲突/重配和有界状态测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 是 | `5ef6c2c73a539c86b914eff0d160a50ae6680a0523255ba70b8094194ad637e5` | `081fbd24795fa82e2a4b2b633c1d2f3c4274b62e218c14d29b3538f07ec19cdc` |
| 101 | `tests/test_ground_unattended_history_export.py` | Tests | 历史全筛选 CSV、排序一致、流式与公式转义测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `83e4d802c115a33d1aa4ac75c772e4a8f98021d8967fcbdcf07c65b6818742b0` | `83e4d802c115a33d1aa4ac75c772e4a8f98021d8967fcbdcf07c65b6818742b0` |
| 102 | `tests/test_ground_unattended_history_query.py` | Tests | 多类型历史索引分页、筛选/稳定排序与边界测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `76546e1b81e4e3211b225c163a87cb3bd1b061068de00a9a61306d05503833e5` | `76546e1b81e4e3211b225c163a87cb3bd1b061068de00a9a61306d05503833e5` |
| 103 | `tests/test_ground_unattended_quick_ping.py` | Tests | 独立任务、参数/停止/并发/重复/异常目标与持久化测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 是 | `41af0ad2f202dda90898f8b4f9684cf1d3e60302b566a7f6cc653a1451948359` | `cf40ff79c83cf6b533f42418ca0b76a8b5f553bae1dce782ae2da6b75fa7101d` |
| 104 | `tests/test_ground_unattended_quick_ping_repository.py` | Tests | Quick SQLite runs/stats/events 与重启/保留测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `47beeb4f2bfb90edeac64b799ac7075dde88b51d8ef6e3852e4836f27b0464ce` | `47beeb4f2bfb90edeac64b799ac7075dde88b51d8ef6e3852e4836f27b0464ce` |
| 105 | `tests/test_ground_unattended_raw_v2_consumers.py` | Tests | active/gzip/READY raw 查询消费者兼容测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `34e0e4f35ee0c526e62935328e93bc76a770c636b543d183a762d41047e89fd6` | `34e0e4f35ee0c526e62935328e93bc76a770c636b543d183a762d41047e89fd6` |
| 106 | `tests/test_ground_unattended_syslog_field_validation.py` | Tests | 本地设备命令/UDP 字段与禁止项校验测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `29a5c29f9ef7265837fa2e8cb33b1a9e151183cc913deab745ef8f122b4cc642` | `29a5c29f9ef7265837fa2e8cb33b1a9e151183cc913deab745ef8f122b4cc642` |
| 107 | `tests/test_ground_unattended_syslog_v2_stress.py` | Tests | 20k burst、未知模块/旋转/磁盘故障与恢复测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `68ecd8ce915d2d54ce16699bbd92358288c41cab675b679be58e3ef027785de4` | `68ecd8ce915d2d54ce16699bbd92358288c41cab675b679be58e3ef027785de4` |
| 108 | `tests/test_ground_unattended_timeline_v2.py` | Tests | 心跳/Syslog/AC timeline 与双时间关联测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `2e9cda243c36f4546b42067b178d6b42040cb90fd3d6e69d1ff1f587850f24e3` | `2e9cda243c36f4546b42067b178d6b42040cb90fd3d6e69d1ff1f587850f24e3` |
| 109 | `tests/test_ground_unattended_usability.py` | Tests | Ground 可用性、参数和受管操作契约测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `ef13abab0d67847c5f4486e1e7202c47d288d67e74dbbc8ebfe6575c0518bef9` | `ef13abab0d67847c5f4486e1e7202c47d288d67e74dbbc8ebfe6575c0518bef9` |
| 110 | `tests/test_rail_transit_base_data_edit_api.py` | Tests | 备用策略保存、校验和失败不写入测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `e5134a8d7a6ba3852c1bfa9c65a9fc6fa353a93d4a273e3ef42784fae025fc06` | `e5134a8d7a6ba3852c1bfa9c65a9fc6fa353a93d4a273e3ef42784fae025fc06` |
| 111 | `tests/test_udp_syslog_reliable_spool.py` | Tests | 回环 UDP/raw/Spool、metadata/fsync/gzip/索引/重放故障注入测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 是 | `6d7500e19fe68213319b9e8b037a064d7218bc45f38a2baf284a5bc7f403d5a6` | `fd3b93840fb850d4c4345539c3bc1c596f44a45cce64341843f547d774512e80` |
| 112 | `tests/test_vehicle_mr_online.py` | Tests | 共享人工 Online MR 行为回归，隔离 Ground 状态测试 | P；领域节点 G（适用文件）；测试断言本身也经审查 | 否 | `4c1da6b4fdff3ef6ab2cec3199425ab803bcccc93bdc340a80e448fd0b5bead5` | `4c1da6b4fdff3ef6ab2cec3199425ab803bcccc93bdc340a80e448fd0b5bead5` |

## 4. 本轮变动清单

- `apps/desktop_renderer/src/components/ground-unattended/QuickPingChart.vue`
- `apps/desktop_renderer/src/components/ground-unattended/quickPingChartOptions.ts`
- `apps/desktop_renderer/src/views/rail-transit/QuickPingPage.test.ts`
- `apps/desktop_renderer/src/views/rail-transit/QuickPingPage.vue`
- `apps/desktop_renderer/tests/visual/e2e/ground-unattended.visual.spec.ts`
- `config/architecture/direct_sql_access.yaml`
- `src/netconsole/services/ground_unattended/application_service.py`
- `src/netconsole/services/ground_unattended/heartbeat_state.py`
- `src/netconsole/services/ground_unattended/quick_ping.py`
- `src/netconsole/services/ground_unattended/supervisor.py`
- `src/netconsole/services/ground_unattended/syslog_runtime.py`
- `tests/test_ac_mesh_link_query_service.py`
- `tests/test_ground_unattended_ac_resident.py`
- `tests/test_ground_unattended_api.py`
- `tests/test_ground_unattended_heartbeat_state.py`
- `tests/test_ground_unattended_quick_ping.py`
- `tests/test_udp_syslog_reliable_spool.py`

另增脚本 `scripts/dev/ground_v2_soak.py`：独占测试根、synthetic runner/回环UDP、组件资源指标和STOP控制；无真实设备/进程，直接SQL仅TEST_ONLY integrity。另增五报告为本目录 `ground-unattended-v2-{final-stability-audit,file-audit,windows-validation,soak-test,defect-register}-2026-11-07.md`。

## 5. 依赖清单

13项与HEAD等价，没有新增框架、库或版本升级；lock均未改。constraints补充检查与此前12项审计一致。比较处理Git CRLF/LF差异；SHA仍为磁盘字节。

| 文件 | 与HEAD一致 | 当前SHA-256 |
| --- | --- | --- |
| `apps/agent/go.mod` | 是 | `b93e4a9db0ee222dec273a4bccc2181068d68b736e13559af7af955dd146f4c7` |
| `apps/agent/go.sum` | 是 | `3fa551099993c06aa5e248472bd5714e5404810630d2f60b62e1dc45e11e201c` |
| `apps/desktop_electron/package.json` | 是 | `1f2310512870dfe082a77c58ba95476e01ca5049e7c70d670a94aa841304c03f` |
| `apps/desktop_electron/pnpm-lock.yaml` | 是 | `3d39d3e0ce122caa69b875bd58c7915f7f08059fb685308f61db081684387e89` |
| `apps/desktop_renderer/package.json` | 是 | `5d132194b3b618f33afe2e9571f98b9b2d3825d610dd87d2cb9d576e4739e46e` |
| `apps/desktop_renderer/pnpm-lock.yaml` | 是 | `cb61740145625194523494bed14e20776a843b4ed07958688bf34fef9b1fb6c8` |
| `pyproject.toml` | 是 | `738043cf4fe4d9993448b0c7ad345419b1ff003a6d0025ab87483f61670d7db5` |
| `requirements-build.txt` | 是 | `0f77a83abe5031612792252d4f9956888e13459aafb147c6321ac4b232d10e4b` |
| `requirements-dev.txt` | 是 | `7444bd55221d62abb672f816a951e4353f5342bfb5efb33834543f98377e1ae9` |
| `requirements-runtime.txt` | 是 | `9d3b05bdc268f034fa2344da791aacc972ec17a53f2a7e0a0a5363f4865d2da8` |
| `requirements-test.txt` | 是 | `cad8eae93850cf0b1cc0e5a59e4e357967e8c1d49b55801cac2a096d143e2d3d` |
| `requirements.txt` | 是 | `20dc9b8cff68a61759c136ec46149d948f82104badf2ca934c35bffbf3accc26` |
| `constraints.txt` | 是 | `5c7443b10d3d5f7355fafa8e3b2698a17a34ff9007334438be808ce5e69ce557` |

## 6. FULL实际执行命令归档

以下从本轮full-gate.log提取，保留实际argv。Renderer/Electron命令在各自apps目录执行，其余在仓库根。测试根是该次独占run，重放时应使用canonical FULL入口生成新的run-id，不复用已退役basetemp。wrapper唯一调整是Renderer --maxWorkers=2。

```text
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m scripts.quality.check_repository_root_layout
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m scripts.check_workspace_layout
D:\study\NetConsole-Workspace\NetConsole\apps\desktop_renderer\node_modules\.bin\vitest.cmd run --maxWorkers=2
D:\study\NetConsole-Workspace\NetConsole\apps\desktop_renderer\node_modules\.bin\vue-tsc.cmd -b
D:\study\NetConsole-Workspace\NetConsole\apps\desktop_renderer\node_modules\.bin\vite.cmd build
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m pytest -q --tb=short --basetemp D:\study\NetConsole-Workspace\test-data\NetConsole\local-gate-13ecdadf6f2445d4b1be591dbb9186f8\pytest-python-full
D:\study\NetConsole-Workspace\NetConsole\apps\desktop_electron\node_modules\.bin\vitest.cmd run
D:\study\NetConsole-Workspace\NetConsole\apps\desktop_electron\node_modules\.bin\tsc.cmd --noEmit -p tsconfig.json
C:\Program Files\nodejs\node.EXE scripts/build.mjs
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe scripts/architecture/run_all.py
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m scripts.quality.run_main_contract_smoke --run-id local-gate-13ecdadf6f2445d4b1be591dbb9186f8-main
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m ruff check .
D:\study\NetConsole-Workspace\NetConsole\.venv\Scripts\python.exe -m pytest tests/test_project_docs_layout.py tests/quality/test_directory_readmes.py -q --tb=short --basetemp D:\study\NetConsole-Workspace\test-data\NetConsole\local-gate-13ecdadf6f2445d4b1be591dbb9186f8\pytest-docs-path-guards
git diff --check HEAD
```

最后Ground实际命令（对应453 passed/1 skipped）：

```text
COMMAND: .venv/Scripts/python.exe -m pytest tests\test_ground_unattended_ac_resident.py tests\test_ground_unattended_ap_display.py tests\test_ground_unattended_api.py tests\test_ground_unattended_archive.py tests\test_ground_unattended_eligibility.py tests\test_ground_unattended_fleet_ping.py tests\test_ground_unattended_fleet_ping_retention.py tests\test_ground_unattended_foundation.py tests\test_ground_unattended_health.py tests\test_ground_unattended_heartbeat_state.py tests\test_ground_unattended_history_archive_query.py tests\test_ground_unattended_history_export.py tests\test_ground_unattended_history_query.py tests\test_ground_unattended_log_suppression.py tests\test_ground_unattended_query_scale.py tests\test_ground_unattended_quick_ping.py tests\test_ground_unattended_quick_ping_repository.py tests\test_ground_unattended_radio_correlation.py tests\test_ground_unattended_raw_lifecycle.py tests\test_ground_unattended_raw_v2_consumers.py tests\test_ground_unattended_schedule.py tests\test_ground_unattended_scheduler.py tests\test_ground_unattended_syslog_field_validation.py tests\test_ground_unattended_syslog_v2_stress.py tests\test_ground_unattended_timeline_v2.py tests\test_ground_unattended_usability.py tests/test_udp_syslog_reliable_spool.py tests/test_ac_mesh_link_query_service.py tests/test_ac_mesh_link_refresh_service.py tests/test_vehicle_mr_online.py tests/test_rail_transit_base_data_edit_api.py -q
```

其余测试命令与重放见[主报告](./ground-unattended-v2-final-stability-audit-2026-11-07.md)。缺陷精确位置及验证见[缺陷台账](./ground-unattended-v2-defect-register-2026-11-07.md)。这些报告不改变原始交付记录；原始记录描述上一阶段快照，本报告描述本轮新增审计。
