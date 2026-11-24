# Phase 5 独立模块定向验收

日期：2026-11-24（Asia/Shanghai）。实施与本次定向验收：PASS。Full Gate：NOT RUN。

产品基线 `334f6226dc7afa8905d131df86ac2b3e9c25d23b`，DevStatus基线 `ad5c10cdd24db47826df59f553f6f905870281eb`，均重新核对远端。历史审计提交 `23011b3c`，实施提交 `d7516883`。产品分支 `codex-A/rail-module-separation-phase5`，DevStatus分支 `codex-A/rail-module-separation-phase5-status`；最终交付SHA、Push及clean结果由Workspace报告 `delivery-verification.md` / `delivery-verification.json`记录。未合并main。

## 恢复来源和模块契约

Phase 1前实际源码为 `12b92a716c021a6947d74182b582d61d9e494080`，通过 `git log --all`、`git log --follow`、`git show 5b445862^:<path>`核实。原BaseData View/Store/API仍存在；移除Phase 1插入的工程工作台，恢复原页面入口和总览，不按截图重写原业务。

| 契约 | 基础设施 | 基础资料 |
| --- | --- | --- |
| Navigation | rail.infrastructure | rail.base-data |
| Route name | rail-transit-infrastructure | rail-transit-base-data |
| Path | /rail-transit/infrastructure | /rail-transit/base-data |
| Feature | module.rail_infrastructure | module.rail_base_data |
| 写能力 | capability.rail_infrastructure.write | capability.rail_base_data.write |
| View / Pinia | 独立Infrastructure View / rail-transit-infrastructure | 原BaseData View / rail-transit-base-data |

两入口并列于轨道交通；AC、Ground、Wireless、轨旁AP、MESH、Online MR保持原专业模块。基础设施复用工程组织树、RelationshipEditor、DeviceDetailPanel与Phase 4上下文，不复制事实表或采集引擎。关系Application Service仍是唯一工程关系写入入口，底层关系算法、Schema和Repository未改。

## 验收证据

报告根：`D:/study/NetConsole-Workspace/reports/tests/rail-module-separation-phase5/`。批次有重叠，不合计为唯一用例总数；完整命令与工作目录见 `commands.json`，输出见 `logs/`。

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 关系/工程树/Feature首轮 | 69 passed / 11.90s | backend-first.log |
| BaseData Query/API/Edit、上下文、资产删除冻结 | 96 passed / 68.55s | base-data-regression.log |
| 导入预览/保存/审计/回滚/站点模板 | 32 passed / 20.08s | base-import-export.log |
| Full/Customer Feature/edition与独立API权限 | 61 passed / 7.35s | features-edition.log |
| 独立模块、原页面、关系组件、Store/cache/router最终回归 | 10 files / 103 passed / 17.01s | renderer-final.log |
| 工作区与MESH 20轮切页、菜单最终回归 | 5 files / 32 passed / 12.66s | workspace-final.log |
| 导出入口/协调器、路由与权限消费者 | 6 files / 38 passed / 9.82s | navigation-routing.log |
| Electron工作区白名单 | 13 passed；typecheck/build PASS | electron-unit.log / electron-build.log |
| main关键入口 | 12 passed / 16.11s | main-smoke.log |
| Architecture / Ruff / Renderer build | 12/12、0 waived / PASS / PASS | architecture.log / ruff.log / renderer-build.log |
| 文档链接与布局 | 13 passed | docs.log |
| 实际Electron | 12场景×2视口，加冷启动2张，共26张 | electron-results.json / electron-restart-results.json / screenshots/ |

原9个主Tab：`overview`、`stations`、`trackside-ap`、`trackside-ap-planning`、`trains`、`quality`、`import-preview`、`import-audit`、`relations`。原站点/区间、列车/MR子页、表格、查询、编辑锁、导入预览/审计/回滚、质量和导出保留。模拟数据编辑与导入写入通过API/组件定向测试验证，不能说成真实数据GUI写入验收。

`907183a4`已封闭的MR资产增删和连接字段编辑不重新开放；保留MR读取和备用监测策略，页面明确提示设备资产归属。[兼容说明](./BASE_DATA_COMPATIBILITY.md)逐项披露该历史安全差异。`can_delete=false`继续冻结。

基础资料原`?tab=`、规划重定向、显式书签/刷新保留；菜单普通重入仍回总览。显式资料书签不会覆盖基础设施的已有工作区标签和cache key。基础设施只解释`node_uid`；不存在节点明确提示，不回退其他身份。旧路径不再解释为基础设施，Phase 1–4的外部工程书签须迁往新路径。

独立模块查看与写权限均经HTTP校验，不能只隐藏菜单。旧`base-data/infrastructure`兼容查询要求两个模块权限；新查询只要求基础设施模块，原BaseData API保留原模块归属。权限切换、读操作无写入、非法Site、删除冻结由`test_rail_module_separation.py`及既有安全测试验证。

## Electron与限制

实际运行Electron Main/Preload/Vue/受管Python Backend，模拟局点且禁用采集；实施提交`d7516883`重启后重新取证。1920×1080和2560×1440、CSS deviceScaleFactor=1。工程组织/节点/设备详情、原九Tab、站点、导入页、审计页、规划书签刷新、MR历史、AC稳定ID跳转、缺失节点、新工程深链接刷新均PASS；截图前等待loading遮罩结束，检查无页面级横向溢出，pageerror为空。

完整退出再启动按既有契约回Dashboard；进程内快照支持刷新恢复，冷启动不持久恢复标签。本次保持该设计，实际验证重启后两个菜单独立可用。Windows原生125%缩放、真实设备、现场局点、安装包、长稳、全量Python/Renderer/Electron与Full Gate均NOT RUN。构建存在既有大chunk提示，不作为功能验收替代。

## 数据和交接

无Schema变更、无迁移/重建、无真实根复制、无历史资料清理、无Phase 3关系实现回退。只使用本任务最小模拟fixture与自动化测试隔离根。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
REAL_DEVICE_MODIFIED=0
DATABASES_REMOVED=0
MAINTENANCE_AUTHORIZED=NO
```

复用两个既有工作树，无新增Worktree、无分支回收、无全局清理；证据与模拟fixture按验收用途保留，不提交日志/数据库/截图。DevStatus三份文件保留原历史字节后追加交接并单独Commit/Push。

风险L4；[前置消费者审计](./PHASE5_MODULE_BOUNDARY_AUDIT.md)与`logs/change-impact.log`记录Feature/runtime共享消费者。按用户明确范围只做定向验证，完整平台回归及main合并后复验仍独立待执行。Phase 3/3.6的PARTIAL不因本轮定向PASS改写，资产物理删除许可不开放。
