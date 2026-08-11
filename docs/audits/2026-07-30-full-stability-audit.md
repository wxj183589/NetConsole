# NetConsole 全仓稳定性审计

## 审计元数据

- 审计日期：2026-07-30（Asia/Shanghai）
- 审计基线：`9320e8df7979430ca623b79169166702db9bcaeb`
- 基线提交：`合并：修复基础资料部分接口刷新失败`
- 产品版本：`v1.4.6`（事实源：`src/netconsole/core/version.py`）
- 审计分支：`audit/full-stability-20260730`
- 审计 worktree：`D:\study\NetConsole-worktrees\full-stability-audit-20260730`
- 原主工作区：审计开始时干净，`main` 与 `github/main` 一致
- 开放 PR：Draft PR #13 `codex/adr-open-source-capability-integration`，仅文档 ADR；本次不修改其 worktree

> **历史快照说明**：本文记录 2026-07-30 基线的审计结果。文中的 `apps/web/...`、`apps/web/package.json` 等路径是该基线工作树中的历史路径，仅用于复现当时证据，不作为当前代码导航。当前 Vue Desktop Renderer 路径为 `apps/desktop_renderer/...`；活动文档和新审计应以当前路径为准。

## 产品边界

- `full_migration` 保持 `format_version=4` 的未加密普通 ZIP 语义，继续保留真实设备凭据。本次不新增密码、加密、签名、HMAC 或密钥体系。
- Windows Server 2012 x64 已由用户现场确认，NetConsole 主程序和 Agent 均可运行，证据等级为 `USER_FIELD_CONFIRMED`。
- 仓库如无自动化 Windows Server 2012 VM 记录，则自动化证据记为 `AUTOMATION_NOT_RECORDED`，不得据此否定现场运行事实。
- 不修改真实数据、数据根或真实凭据，不连接真实设备执行写命令。
- 不修改 Monaco、xterm.js、外部工具集、OmniPeek、WinMerge、CBTC 等无关在研范围。

## 检查范围

- 架构分层、现有架构 Guard 和例外清单
- API 错误分类、查询超时与恢复
- 轨道交通基础资料、轨旁 AP 规划和轨旁 AP 业务
- 轨旁 AP 相关 Task Center 与 Export Process 语义
- 数据迁移包完整性与既定明文凭据语义
- Electron 安全、生命周期和 Windows Server 2012 兼容状态
- 依赖、版本、SBOM、发布、测试、CI 和文档事实源

## 明确不检查或不执行

- 不连接真实设备，不执行设备写命令或 AC 固化动作。
- 不使用真实用户数据执行测试。
- 不执行正式安装包 GUI 人工验收；最终状态记为 `PENDING`，由独立人工环境完成。
- P2 大规模重构只形成计划，不在本次实施。

## 发现汇总

| ID | 级别 | 证据 | 模块 | 状态 | 本次实施 |
| --- | --- | --- | --- | --- | --- |
| P0-01 | P0 | CONFIRMED | 轨旁 AP 规划 | 已修复 | 是 |
| P0-02 | P0 | CONFIRMED（基线已修复） | 基础资料刷新 | 已有实现，待回归 | 否 |
| P0-03 | P0 | CONFIRMED | 基础资料错误状态 | 已按域隔离，诊断字段仍可扩展 | 是 |
| P0-04 | P0 | CONFIRMED（基线已修复） | 规划/上线概览 | 已有实现，待回归 | 否 |
| P0-05 | P0 | CONFIRMED（基线已修复） | 轨旁 AP 业务 | 已有实现，待回归 | 否 |
| P1-01 | P1 | CONFIRMED | 轨旁 AP 任务状态 | 已修复 | 是 |
| P1-02 | P1 | CONFIRMED | Task Center 业务结果 | 已统一兼容投影，legacy 仍需逐域收敛 | 是 |
| P1-03 | P1 | CONFIRMED | Feature/验收事实 | 文档维度不完整 | 是（文档） |
| P1-04 | P1 | CONFIRMED | Windows Server 2012 文档 | 已修复（文档） | 是 |
| P1-05 | P1 | CONFIRMED | 版本/依赖元数据 | 已修复（文档/元数据） | 是 |
| P1-06 | P1 | CONFIRMED | API Client | 已修复 | 是 |
| P1-07 | P1 | CONFIRMED | UI 架构分类 | 已修复 | 是 |
| P1-08 | P1 | CONFIRMED | 全仓查询部分刷新 | 已修复 | 是 |

当前确认发现共 13 项：P0 5 项、P1 8 项。另有 12 项 P2 整改候选，仅记录计划，不在本次实施大规模重构。

## 发现详情

每项发现记录：ID、严重级别、证据等级、所属模块、代码路径、用户表现、根因、数据风险、修复建议、自动测试建议、本次是否实施和实施提交。

### P0-01 AP 数量为 0 时空 VLAN 被拒绝

- 严重级别：P0
- 证据等级：CONFIRMED
- 所属模块：轨旁 AP 规划、导入和基础资料统一事务
- 代码路径：`apps/web/src/components/rail-transit/base-data/TracksideApPlanningTab.vue`、`src/netconsole/services/trackside_ap_plan_io.py`、`src/netconsole/services/rail_transit/ap_management_vlan_planning.py`、`src/netconsole/repositories/rail_transit_base_data_repository.py`
- 用户表现：自动站点骨架的 `planned_ap_count=0, management_vlan=null` 被计入“有 N 项需要修正”；导入和保存同样拒绝或把空 VLAN 转成 `0`。
- 根因：前端对所有行无条件校验 VLAN；导入标准化无条件要求 VLAN；兼容规划无条件要求组 VLAN；基础资料事务仓储用 `int(value or 0)` 丢失空值语义。
- 数据风险：用户可能为尚未规划 AP 的站点填写伪 VLAN 以绕过校验；统一事务保存会因数据库范围约束失败。
- 修复建议：仅在 AP 数量大于 0 时要求 VLAN；已有 VLAN 无论数量是否为 0 都必须保持 1～4094；空值原样落为 SQL `NULL` 和兼容空字符串。
- 自动测试建议：覆盖前端骨架/按钮/边界值、导入标准化、服务保存、事务仓储和导出。
- 本次是否实施：是
- 实施提交：`e71eb2ac`

### P0-02 基础资料单接口失败曾放大为整组失败

- 严重级别：P0
- 证据等级：CONFIRMED（基线已修复）
- 所属模块：基础资料 Store
- 代码路径：`apps/web/src/stores/railTransitBaseData.ts`、`apps/web/src/stores/railTransitBaseData.test.ts`
- 用户表现：旧实现中数据质量、MR 等单接口失败会阻止同组成功结果写入；当前基线已改为端点独立刷新并保留最后成功数据。
- 根因：旧实现使用整组 `Promise.all` 后统一赋值；基线提交 `0f2678b4` 已按端点收敛成功与失败。
- 数据风险：旧行为不修改数据，但会闪空表、显示旧统计或把未知误解为真实 0；当前基线风险转为回归风险。
- 修复建议：不重复改写现有 Store；保留端点独立更新、失败保留旧值和单域恢复语义。
- 自动测试建议：回归 quality/MR/station 单接口失败、首次部分成功、已有数据后失败和单域恢复。
- 本次是否实施：否，基线已有实现；本次只回归
- 实施提交：`0f2678b4`（本次基线之前）

### P0-03 数据域错误诊断字段不完整

- 严重级别：P0
- 证据等级：CONFIRMED
- 所属模块：基础资料 Store 和错误 Banner
- 代码路径：`apps/web/src/stores/railTransitBaseData.ts`、`apps/web/src/views/rail-transit/RailTransitBaseDataView.vue`
- 用户表现：局部失败已能独立保留数据，但详情无法说明是否保留最后成功数据、最近成功时间和连续失败次数。
- 根因：`BaseDataRefreshError` 只保存失败时间及 API 诊断；成功时间和连续失败计数保存在不可见的分散状态中。
- 数据风险：无直接写入风险，但用户难以区分首次加载失败与旧数据降级展示。
- 修复建议：为每端点维护最近成功时间，并把 `retainedLastSuccess`、`consecutiveFailures`、`lastSuccessfulAt` 写入错误对象和展开详情。
- 自动测试建议：覆盖首次失败、已有成功数据后失败、连续失败和单域恢复。
- 本次是否实施：是
- 实施提交：`3bccedb5`

### P0-04 规划维护与上线概览曾互相阻断

- 严重级别：P0
- 证据等级：CONFIRMED（基线已修复）
- 所属模块：轨旁 AP 规划
- 代码路径：`apps/web/src/components/rail-transit/base-data/TracksideApPlanningTab.vue`、`TracksideApPlanningTab.behavior.test.ts`
- 用户表现：旧实现中上线状态接口失败可能让规划区域一并进入错误或空状态；当前基线已拆分 `planError/onlineStatusError` 和对应加载状态，失败不清空上一份数据。
- 根因：旧实现复用请求链和错误状态；基线提交 `ea7ce289` 已拆分规划与上线概览的数据生命周期。
- 数据风险：旧行为不直接写坏数据，但会阻断规划编辑并可能让用户误解规划为空。
- 修复建议：保持两个接口、错误、加载状态和缓存独立；上线刷新不得覆盖未保存规划草稿；API 错误不得进入字段校验计数。
- 自动测试建议：回归 plan 成功/status 失败、反向失败、状态失败保留缓存和 validationCount 独立。
- 本次是否实施：否，基线已有实现；本次只回归
- 实施提交：`ea7ce289`（本次基线之前）

### P0-05 轨旁 AP 业务曾把部分来源失败显示为空表

- 严重级别：P0
- 证据等级：CONFIRMED（基线已修复）
- 所属模块：轨旁 AP 业务聚合
- 代码路径：`apps/web/src/views/rail-transit/TracksideApBusinessView.vue`、对应 API/Application Service 和部分成功测试
- 用户表现：旧实现中 FIT-AP 或设备事实来源失败会放大为空表或统计 0；当前基线已保留成功构建的交换机/AP 端口行，并区分未加载、失败、部分成功与真实 0。
- 根因：旧聚合链把来源可用性与最终行存在性绑定；基线已增加分来源状态和降级展示。
- 数据风险：不修改设备事实，但会误导运维判断，尤其把未知当成真实 0。
- 修复建议：不重复重构聚合服务；保持每个来源独立状态、成功行增量保留和导出部分成功语义。
- 自动测试建议：回归 FIT-AP、LLDP、光模块三类来源的独立失败以及统计卡四态。
- 本次是否实施：否，基线已有实现；本次只回归
- 实施提交：`ea7ce289` 及后续主线部分成功修复（本次基线之前）

### P1-01 轨旁 AP 页面维护第二套任务状态

- 严重级别：P1
- 证据等级：CONFIRMED
- 所属模块：轨旁 AP 规划、业务和基础资料任务交互
- 代码路径：`TracksideApPlanningTab.vue`、`TracksideApBusinessView.vue`、`RailTransitBaseDataView.vue`
- 用户表现：同一任务可能同时被全局 Task Store 和页面每秒轮询；页面通过三个 `localStorage` 键恢复任务，并显示冗余“打开任务中心”入口。
- 根因：轨旁页面仍保留全局 Task Store 建立前的局部恢复、轮询和终态处理。
- 数据风险：无数据库风险；会放大 Backend 请求、产生状态竞争和页面卸载后的恢复差异。
- 修复建议：全局 Task Store 成为唯一轮询/恢复事实源；页面只记录当前内存 `taskId` 并从 Store 派生状态，详情复用全局抽屉。
- 自动测试建议：静态禁止局部任务 localStorage/轮询，并覆盖页面重进、终态和详情入口。
- 本次是否实施：是
- 实施提交：`5515f667`

### P1-02 Task Center 缺少统一的业务结果投影

- 严重级别：P1
- 证据等级：CONFIRMED
- 所属模块：Job Center 查询、任务 DTO、轨旁 AP 光衰任务
- 代码路径：`src/netconsole/models/task_history_policy.py`、`src/netconsole/services/job_center/query_service.py`、`src/netconsole/models/api/job_center.py`、`apps/web/src/types/task.ts`、`apps/web/src/views/job-center/JobCenterView.vue`
- 用户表现：Task Center 已能用 `has_warning` 标记部分成功或告警，但列表仍只展示七状态生命周期；成功、失败、跳过、告警计数及主要失败原因只在部分任务的 `details` 中出现，无法稳定区分“执行完成”和“业务完全成功”。
- 根因：现有 `business_result_has_warning()` 只输出布尔值，尚未把不同 handler 的 `status/business_outcome/partial_success/count` 兼容字段投影成统一结构。
- 数据风险：不改变任务调度或结果数据，但列表可能把 `COMPLETED + failed_count > 0` 理解为普通完成。
- 修复建议：保持七状态生命周期不变；在 Job Center 查询层增加只读、兼容旧结果的业务结果投影，输出 `business_status`、成功/失败/跳过/告警计数、`partial_success` 和 `primary_failure_reason`；列表展示业务状态。历史 `NO_TARGET` 读取时兼容投影为 `NO_EFFECTIVE_TARGET`，不重写历史任务结果。
- 自动测试建议：覆盖完全成功、部分成功、完成有告警、无有效目标、失败和旧结果兼容；列表与详情使用同一投影。
- 本次是否实施：是
- 实施提交：`ca5f9f87`

### P1-03 Feature 状态未完整表达验收事实

- 严重级别：P1
- 证据等级：CONFIRMED
- 所属模块：Feature Registry、迁移矩阵和发布事实文档
- 代码路径：`src/netconsole/core/feature_registry.py`、`docs/architecture/MIGRATION_MATRIX.md`、`README.md`
- 用户表现：`FeatureStatus.ENABLED` 只表达入口可用，不能说明自动化、Electron 人工、真实设备和正式包验证状态；迁移矩阵虽区分 `IMPLEMENTED_UNVERIFIED/REAL_DEVICE_PENDING/COMPLETE`，但没有稳定列出四类验证证据。
- 根因：Feature 开关与产品验收属于不同事实维度，活动文档尚未建立统一验证矩阵。
- 数据风险：无；发布评审可能把“入口启用”误读为“真实设备与正式包均已验收”。
- 修复建议：不改 `FeatureItem` Schema；在活动文档增加主要模块验证矩阵，分别记录实现、自动化、Electron 人工、真实设备和正式包状态，并保留 Windows Server 2012 的现场事实等级。
- 自动测试建议：文档 Guard 校验矩阵列和受控状态词；Feature/Navigation 现有一致性测试继续作为入口事实证据。
- 本次是否实施：是，仅更新文档
- 实施提交：`925863f0`

### P1-04 Windows Server 2012 文档结论与现场事实冲突

- 严重级别：P1
- 证据等级：CONFIRMED / USER_FIELD_CONFIRMED
- 所属模块：兼容性与发布文档
- 代码路径：`apps/agent/README.md`、`docs/AGENT.md`、`docs/BUILD_AND_RELEASE.md` 及开放 Draft PR #13
- 用户表现：活动文档仍写 Server 2012 不得视为已支持，和用户确认的主程序、Agent 现场运行事实冲突。
- 根因：文档只采用仓库自动化证据，未单独记录现场事实和自动化 VM 证据等级。
- 数据风险：无。
- 修复建议：主程序与 Agent 标记 `USER_FIELD_CONFIRMED`；自动化 VM 标记 `AUTOMATION_NOT_RECORDED`；不新增 OS 启动阻断。PR #13 不在本 worktree 修改，只在报告声明旧结论已过时。
- 自动测试建议：静态文档 Guard 确认不再出现否定现场事实的活动表述。
- 本次是否实施：是
- 实施提交：`925863f0`

### P1-05 版本和依赖元数据漂移

- 严重级别：P1
- 证据等级：CONFIRMED
- 所属模块：构建元数据
- 代码路径：`constraints.txt`、`apps/web/package.json`、`src/netconsole/core/version.py`、`apps/desktop_electron/package.json`
- 用户表现：Python 锁文件注释仍写 `v1.3.9`；Web `0.1.0` 未在包元数据中说明不是产品版本。
- 根因：版本升级未同步非事实源注释。
- 数据风险：无运行数据风险；发布审计可能误判组件版本。
- 修复建议：去除锁文件中的过期产品版本；保留 `version.py` 唯一产品事实源，明确 Web 包版本仅为内部工作区版本。
- 自动测试建议：版本一致性和元数据静态测试。
- 本次是否实施：是
- 实施提交：`925863f0`

### P1-06 API 查询缺少超时和有限恢复

- 严重级别：P1
- 证据等级：CONFIRMED
- 所属模块：Web API Client
- 代码路径：`apps/web/src/api/client.ts`
- 用户表现：GET 可无限等待；Backend 短暂重启时立即失败；超时没有稳定专用错误码。
- 根因：`fetch` 未使用集中超时，所有方法均单次调用。
- 数据风险：写请求若错误重试会重复写入，因此只能对 GET/HEAD 查询实施。
- 修复建议：集中 AbortController 超时；GET/HEAD 对可恢复传输错误做一次短指数退避；外部 signal 和写请求不自动重试。
- 自动测试建议：GET 超时、GET 恢复、最大次数、POST 不重试和调用方 Abort 保持可取消。
- 本次是否实施：是
- 实施提交：`60c3f18f`

### P1-07 轨旁 AP 站点骨架缺少 UI 架构分类

- 严重级别：P1
- 证据等级：CONFIRMED
- 所属模块：UI 架构 Guard、轨旁 AP 规划
- 代码路径：`apps/web/src/components/rail-transit/base-data/TracksideApPlanningTab.vue`、`config/architecture/ui_business_logic.yaml`
- 用户表现：安装锁定的 Web 依赖后，`ui-business-logic` 架构门以 `UI_BUSINESS_LOGIC_UNCLASSIFIED` 拒绝 `mergePlanRows`，阻断组合验证和发布门。
- 根因：站点规划骨架合并函数已进入基线，但对应精确符号没有同步登记到 UI 人工分类清单。
- 数据风险：无直接数据风险；函数只把 Backend 规划行与当前站点列表投影为页面可编辑骨架，正式保存仍由 Backend 独立校验。
- 修复建议：把该精确路径和符号登记为 `DISPLAY_ONLY`，指向已有规划行为测试；不放宽扫描规则、不增加目录级豁免。
- 自动测试建议：运行 `TracksideApPlanningTab.behavior.test.ts` 和 `check_ui_business_logic.py`，同时保持配置陈旧项检查开启。
- 本次是否实施：是
- 实施提交：`588b8893`

### P1-08 全仓查询子接口失败放大

- 严重级别：P1
- 证据等级：CONFIRMED
- 所属模块：Online MR、无线看板、AC/FIT-AP、Agent 任务详情、局点存储
- 代码路径：`apps/web/src/stores/onlineMr.ts`、`apps/web/src/views/rail-transit/RailTransitWirelessDashboardView.vue`、`apps/web/src/stores/acManagement.ts`、`apps/web/src/views/agents/AgentListView.vue`、`apps/web/src/views/settings/SiteStoragePanel.vue`
- 用户表现：配对的只读请求中任一接口失败时，成功返回的数据不落入页面，旧数据可能被清空或轮询被停止。
- 根因：详情/日志、局点列表/数据根及多个看板域使用整组 `Promise.all` 或共享错误/失败计数。
- 修复结果：改用 `Promise.allSettled` 或按域结算；成功结果立即落值，失败域保留旧值，恢复只清除自身错误；未加载数字显示 `—`。
- 自动测试：覆盖 Online MR、无线看板、AC Store、Agent 详情、Site Storage 和基础资料行为。
- 本次是否实施：是
- 实施提交：`a13eb8ac`

## 其他审计结论

### 架构与分层

- 基线首次运行九个架构门时，`forbidden-imports`、`direct-sql-access`、`device-command-hardcoding`、`removed-features`、`runtime-paths`、`orphan-modules`、`migration-map` 七门通过。
- 安装锁定的 Web/Electron 依赖后，`architecture-boundaries` 通过；`ui-business-logic` 确认唯一未分类符号为 `TracksideApPlanningTab.vue` 的 `mergePlanRows`，已按 P1-07 登记为精确 `DISPLAY_ONLY`。
- Python 分层当前 23 个、orphan Service 当前 21 个命中均由精确限时例外覆盖；本次不扩展例外、不把既有债务伪报为已迁移。
- 未发现新增直接 SQLite 访问、被移除功能入口或 Qt/PySide 回流证据。

### 数据迁移包

- `full_migration` 当前正式语义保持 `format_version=4`、未加密普通 ZIP、完整局点数据与真实设备凭据；本次不把这一产品边界列为缺陷。
- 现有实现保留 manifest、文件 SHA-256、成员路径约束、符号链接拒绝、解压预算、SQLite 一致性检查和原子导入/回滚边界。
- `sanitized_share`、`field_collection`、`collection_return` 与 `site_uuid` 合并语义继续独立；本次只做回归验证，不修改包类型或稳定 UUID 规则。

### Electron 安全与生命周期

- `webPreferences` 仍为 `nodeIntegration=false`、`contextIsolation=true`、`sandbox=true`、`webSecurity=true`、`webviewTag=false`。
- 新窗口、导航、重定向、WebView、下载和权限均有默认拒绝边界；Renderer 退出诊断、主窗口首次最大化、托盘恢复和受管 Backend 生命周期已有专门测试。
- 未发现因本次范围需要修改 Electron 安全配置或增加 Windows Server 2012 OS 启动判断的确认缺陷；后续仅回归现有测试。

### 版本、发布与兼容

- 产品版本事实源为 `src/netconsole/core/version.py` 的 `v1.4.6`；Electron package 为 `1.4.6`，一致。
- Web package 的 `0.1.0` 是工作区内部包版本，不应被解释为产品版本；`constraints.txt` 首行仍引用 `v1.3.9`，属于确认漂移。
- 正式构建已有 clean、upstream、Git metadata、唯一制品、Notice/SBOM、冻结 Backend 和最终 Electron package smoke 门；本次不放宽这些门。
- Windows Server 2012 x64 的主程序与 Agent 现场运行事实均为 `USER_FIELD_CONFIRMED`；自动化 VM 记录为 `AUTOMATION_NOT_RECORDED`，两者不得互相替代。
- 本轮稳定性补丁提交为 `a13eb8ac`；仅包含只读查询刷新与前端状态语义，不改变设备命令、凭据、迁移包或导出协议。

## P2 后续计划

以下 12 项不在本次进行大规模实现。除明确事实外，设计收益和拆分顺序均为后续建议。

| 项目 | 当前事实与风险 | 推荐拆分及涉及路径 | 验收门 | 独立 worktree |
| --- | --- | --- | --- | --- |
| `RailTransitBaseDataView.vue` 拆分 | 页面同时承载多数据域、编辑、导入和任务交互，修改回归面大 | 按 summary/static/runtime/governance/import-task 逐域抽 composable/子组件；`apps/web/src/views/rail-transit`、`components/rail-transit/base-data` | 行为测试逐步迁移且 DOM/Store 契约不变 | 是 |
| `TracksideApPlanningTab.vue` 组件化 | 规划编辑、导入预览、上线概览和任务交互集中 | 先抽纯校验与表格编辑，再拆预览、上线状态；不得改变规划规则 | 规划全边界、草稿保护和视觉回归 | 是 |
| `trackside_ap_business.py` 拆分 | scope、identity、optical、export 聚合在大模块，领域边界难评审 | 按只读查询、身份投影、光衰采集、导出 builder 分提交 | 三来源部分失败、真实 0/未知语义与导出一致 | 是 |
| E11 设备命令 Profile | 仅部分只读命令进入受控 Profile，仍有既有硬编码例外 | 按设备厂商和用例逐项迁移 `services`、`resources/device_command_profiles.json` | 命令文本、顺序和设备回显 parser 回归；架构门无新增例外 | 是 |
| E12 API v1 契约 | 当前内部 API 可用，但缺少全领域正式版本治理 | 先冻结高价值只读 DTO，再建立兼容/弃用策略，不全仓改路由 | OpenAPI 契约快照、旧客户端兼容和错误码稳定 | 是 |
| Python 分层例外 | 当前 23 个命中由精确限时例外覆盖 | 每次只迁移一个领域依赖方向，更新 `config/architecture/exceptions.yaml` | 九门通过且例外数量净下降 | 是 |
| orphan Service | 当前 21 个命中由精确限时例外覆盖 | 逐个证明动态入口、接线或删除；禁止批量猜测删除 | orphan 门通过、功能/导入契约回归、例外数量净下降 | 是 |
| 全仓 Task Store 迁移 | 本次仅收敛轨旁 AP 范围，其他页面可能仍有历史局部状态 | 按页面族迁移到全局 Store 与统一详情抽屉 | 无页面级任务 localStorage/重复轮询，页面恢复测试通过 | 是 |
| Server 2012 自动化 VM | 已有现场运行事实，但仓库无自动化 VM 记录 | 建立隔离 VM、安装包与 Agent smoke，不改变现场支持结论 | 记录 OS/架构、安装、启动、健康、退出与 Agent API 结果 | 是 |
| GitHub Actions 完整 CI | 本地门禁丰富，远端执行覆盖需独立审计和资源规划 | 分 Python、Web、Electron、架构和 package 分层流水线 | 与本地命令一致、缓存可追溯、失败日志留存 | 是 |
| 代码签名和自动升级 | 当前不是已完成发布能力 | 分别设计签名、证书保管、升级源、回滚和离线场景 | 独立威胁评审、签名验证、升级/回滚安装测试 | 是 |
| Draft PR #13 重新设计 | PR 仅为 ADR，含已过时的 Server 2012 结论；本 worktree 不修改 | 在其所属 worktree 基于本报告更新事实与范围 | 不否定 `USER_FIELD_CONFIRMED`，ADR 评审单独通过 | 是 |

## 验证记录

### 已执行

- `git fetch github --prune`
- 基线、工作区、worktree、开放 PR 和版本元数据只读核对
- `D:\study\NetConsole\.venv\Scripts\python.exe -m pytest tests/test_ap_management_vlan_planning.py tests/test_trackside_ap_web.py tests/test_task_center.py -q`：`116 passed, 1 warning`
- Python 相关业务回归：`249 passed, 7 warnings`
- Python 全量：`3183 passed, 2 skipped, 1 quality gate fixed`（初次唯一失败为缺少 `docs/audits/README.md`，补齐后质量门 `15 passed`）
- Web 全量 Vitest：`146 files, 839 tests passed`
- Web `vue-tsc -b` 和 production build：通过
- Electron Vitest：`32 files, 228 tests passed`；typecheck 与 main/preload build：通过
- Agent Go：`go test ./...` 通过；Python `compileall`、Ruff、`pip check`：通过
- 架构 Guard：`9/9 passed`；稳定性脚本：100 轮规划/基础资料 HTTP 200，0 网络错误，Backend PID 未变化
- 修改差异和 Markdown 链接检查：通过
- 正式 NSIS 与 package smoke：通过；制品名称、SHA-256、字节数和构建提交以 `dist/electron/*.exe.release.json` 为准，`NSIS-3 Unicode`，`REAL_WINDOWS_INSTALL_STATUS=PENDING`

### 待执行

- Windows Server 2012 自动化 VM 和正式包 GUI 人工验收

## 既有失败

完整 Python 首次门禁发现 `docs/audits` 缺失 README，已补充目录索引并通过质量测试；没有业务测试失败。

## 修复结果

本轮已完成查询部分刷新审计及修复，提交 `a13eb8ac`；文档与审计索引提交 `d3272991`。正式包已按最终提交构建并通过 smoke，详细制品身份见随包 release metadata。

## 未验证项

- Windows Server 2012 自动化 VM：`AUTOMATION_NOT_RECORDED`
- 正式安装包 GUI 人工验收：`PENDING`

## 后续建议

继续按 P2 计划逐域迁移 legacy handler、建立 Server 2012 自动化 VM，并完成正式安装包 GUI 验收；这些不影响本轮只读查询稳定性修复的自动化结论。
