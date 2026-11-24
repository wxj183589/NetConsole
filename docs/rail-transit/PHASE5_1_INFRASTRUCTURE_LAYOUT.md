# 基础设施工作台布局

Phase 5.1基线：产品 `3f6dee222c3dd5003626fd915018f2c422d0523b`；DevStatus `1961fe35bf73422dfd81979905fd9af1020984d7`。本轮只调整独立基础设施View/工作台布局、对应文案与测试，风险L2；不改基础资料、设备详情实现、工程关系Application Service、数据库、导航、路由或Feature定义。

## 来源审计

当前页面为 `RailTransitInfrastructureView.vue` → `InfrastructureWorkbench.vue` → 原 `DeviceDetailPanel.vue` / `RelationshipEditor.vue`。原样式按1:2:2分栏，树和工程资料随窗口变宽；工作区高度为 `clamp(460px, 58vh, 810px)`，无法利用路由容器的剩余高度。View和工作台各有一个刷新入口，并重复显示页面/局点/线路名称。

当前基础设施没有底部基础资料统计卡片：Phase 5已经把原 `RailTransitBaseDataView.vue` 的 `.summary-grid` 留在独立基础资料页面。不能为本轮截图问题误删原资料统计或API。基础设施 `.site-counts` 读取工程投影，改为单行轻量摘要；没有新增占位卡片或猜测AP/MR统计。车站、区间、车辆段、列车计数来自实际工程节点集合，设备及关联异常读取原DTO字段。

## 布局和交互

- 使用既有 `.app-main` → `.app-route-viewport` 的可用高度，页面 `height:100%`、flex与 `min-height:0` 向下传递；工作台三栏填满剩余高度，不硬编码应用头部/标签栏高度，不修改共享Shell。
- 树宽 `clamp(240px,18cqw,280px)`，工程资料宽 `clamp(340px,28cqw,420px)`，设备详情 `minmax(500px,1fr)`。按工作台容器宽度适配，侧栏开合不把窄栏继续拉大。
- 树、工程资料各自滚动；右栏复用原DeviceDetailPanel内部Tabs/表格/overview滚动。外层设备栏不再叠加overview纵向滚动，保留完整表格字段和水平滚动。AC关系维护仍在原位置，内容超出可单独滚动。
- 顶部显示线路、当前工程节点、工程数量、异常、搜索和唯一刷新入口；页面名由共享Shell标题给出。树根改为线路概览，工程字段中不再重复编号/标题；正式名称、有效项目、名称记录、区间、关系和设备均保留。空编号/项目/服务站点行不占位，未配置状态仍由树/关系空态表达，不隐藏已存在字段。
- 长节点与设备名省略并提供Tooltip，完整正式名称和业务事实仍在详情中。相同工程角色与设备名称不在树里重复拼接。
- 容器≤1100px时保留树，右侧在工程资料/设备详情间切换；选设备自动显示设备，选工程节点返回工程资料。两个面板仍保持组件挂载，切换不清除设备选中/Tab、不更改权限或写保护。容器≤740px时树在上、详情在下，避免强挤三栏。
- 既有关系新增/修改/解除、MR历史、Revision冲突和脏稿离开保护仍由原组件处理。弹窗内容、业务字段、数据来源和删除冻结不变；`can_delete=false`。

## 实际验收与交付边界

必须在实际Electron运行同一源码，并用模拟测试局点验证控制中心、车站、交换机、区间、列车、设备接口/光模块/LLDP、关系维护与历史、Tooltip、深链接刷新、独立基础资料导航。分辨率1648×927、1920×1080、2560×1440；额外验证1280×720两栏切换。CSS deviceScaleFactor=1，不代表Windows原生缩放验收。

原采集字段为空时保持未知/未采集/暂无数据，不填视觉用数值、不连接设备。既有最小合成fixture仅用于布局验收，不复制真实数据根。

本轮报告和逐分辨率前后尺寸、执行命令、最终提交与远端SHA位于 `D:/study/NetConsole-Workspace/reports/tests/infrastructure-workbench-layout-phase5-1/`：`layout-audit.md`、`renderer-regression.md`、`electron-visual-validation.md`、`delivery-verification.md`，原始截图在 `screenshots/`、日志在 `logs/`。

定向范围包括Infrastructure View/Store/tree、DeviceDetailPanel、RelationshipEditor、工程上下文、模块隔离、Feature及Router回归、TypeScript/Renderer build、Architecture、main smoke、文档链接与diff。Python生产代码未改，Ruff不适用。Full Gate、全量测试、真实设备/现场、安装包、原生DPI和长稳未执行；不把本轮空间优化写成平台完整验收或main合并。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
REAL_DEVICE_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```

本轮复用既有产品/DevStatus工作树，分别建立指定分支；不合并main、不删除其他分支/Worktree。既有模拟fixture及截图证据保留用于复核，任务运行进程退出；无本地分支回收事件，未启动历史目录清理。

## 本轮定向结果

2026-11-24，定向验收PASS。实施提交 `3c35de7448a7a7c17c976862b5dcdbd05f6a850d` 上完整重启Electron后复跑三种目标视口14场景/视口（42张）、1280×720两栏切换（2张）；另有原布局对比3张，共47张截图，pageerror为空。截图、尺寸和SHA256见Workspace报告与manifest；不是Windows原生DPI或真实设备验收。

| 视口 | 树宽 前→后 | 中栏 前→后 | 右栏 前→后 | 工作区高度 前→后 | 底部闲置 前→后 |
| --- | --- | --- | --- | --- | --- |
| 1648×927 | 282.8→254.9 | 565.6→396.5 | 565.6→762.7 | 537.7→781 | 182.3→0 |
| 1920×1080 | 337.2→280 | 674.4→420 | 674.4→986 | 626.4→934 | 246.6→0 |
| 2560×1440 | 465.2→280 | 930.4→420 | 930.4→1626 | 810→1294 | 423→0 |

三栏等高，切换设备前后树/中栏宽度稳定，路由容器无整体横向溢出或纵向滚动；设备overview内部可滚动，关系/历史弹窗在视口内。实际场景包括控制中心、车站、交换机、区间、列车、接口、光模块、LLDP、Tooltip、工程关系新增/取消、MR历史、独立基础资料导入审计、新深链接刷新、AC稳定ID跳转。少节点和短内容仍有自然余白，未用假数据或占位卡片填充。

Renderer 10文件/116项通过，基础设施/Feature/权限/工程上下文/关系84项通过；main smoke12项、Architecture12/12（0waived）、文档13项通过。TypeScript检查、Renderer build与diff通过。Python生产代码未修改，Ruff不适用；Full Gate及其它未执行项保持上节边界。最终产品/DevStatus SHA、Push与clean结果由 `delivery-verification.md`记录。
