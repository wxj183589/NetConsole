# 设备详情展示组件

## 用途与边界

本目录提供设备快速详情抽屉与完整详情页共用的 Vue presentation 组件。`DeviceDetailPanel.vue` 负责布局、页签、分页、筛选、展示和轻量交互；不实现设备识别、厂商/版本推断、能力推断、阈值计算、命令选择、AP 身份或其他 Python 业务规则。

页签可见性只消费后端 overview 的 `visible_sections`；`capabilities`、`command_profile`、阈值、来源和任务事实只按 DTO 展示。Vue 不根据 capability ID、vendor 或 version 自行决定业务页签。

## 入口

- `DeviceDetailPanel.vue`：抽屉与完整详情页共用的展示入口。
- `DeviceDetailPanel.test.ts`、`DeviceDetailPanel.mount.test.ts`：静态契约和交互测试。
- `../../views/devices/DeviceManagementView.vue`：设备列表中的快速抽屉入口。
- `../../views/devices/DeviceDetailView.vue`：`/devices/:deviceId` 完整详情入口。

## 依赖

组件依赖 Vue、Element Plus、NetConsole Design Token、`deviceManagement` API、统一 Task Store 和受控 Artifact 下载桥接。设备详情数据、分页、筛选枚举和任务状态来自后端 API/Task Store；组件不直接访问数据库、Agent、Electron Main/Preload 或 Python Service。

能力事实、动态分区和历史记录统一使用 `NcDataTable`。分区和历史分别以 section/kind 作为偏好 scope，避免接口、光模块、LLDP、配置和任务列布局相互污染；固定首列、操作列、长文本对齐和列宽均由公共列定义表达，组件不直接声明 `el-table-column`。接口、光模块、LLDP、任务记录和关联业务的正式 Electron 偏好键分别为 `device-detail.interfaces`、`device-detail.optical-modules`、`device-detail.lldp`、`device-detail.task-records` 和 `device-detail.related-businesses`；浏览器开发模式继续使用公共 localStorage 回退。偏好结构固定为 `version: 1` 和稳定列 key，保存显隐、顺序、固定方向与手工列宽；列增删通过当前代码定义合并，损坏或不兼容版本整体回退默认，“恢复默认布局”同时清除当前表的本地配置。

抽屉 Body、共享 Panel、Tabs、活动 Pane 和表格宿主形成连续的纵向 flex 高度链，所有可收缩节点均保留 `min-height: 0`。筛选栏、错误提示和来源信息使用自然高度，表格宿主占用剩余空间并将横纵滚动留在 Element Plus 表体内，分页器作为表格宿主的同级元素紧随其后；概览页签单独在 Pane 内滚动。接口、光模块、LLDP、配置、任务记录和关联业务统一使用该策略，不再按抽屉/完整页写死表格高度或最大高度。

## 数据与状态

打开抽屉或完整详情只读取数据库中的最近 overview 快照，不立即连接设备；其余页签首次激活后按后端 DTO 分页加载并缓存。筛选和分页值必须使用后端传输枚举，展示文案可以本地化。刷新通过 `device.inventory.collect` 进入现有 Task Center，组件通过共享 Task Store polling 跟踪状态，不另建 WebSocket 或第二套任务模型。任务完成、失败或取消后重新加载 overview 及已经加载的页签；请求使用 generation 防止切换设备、页签或筛选后的旧响应覆盖新状态。卸载时释放 Task Store polling，并清理本组件请求状态、图表和观察器。

接口默认顺序由 Python Repository 在筛选后的完整结果上使用 `interface_sort_key()` 计算，再执行分页；前端不对当前页二次排序。比较时接口类型别名只用于排序键，端口层级和子接口数字按数值比较，原始接口名仍按 DTO 原样展示；无法解析的名称排在可解析接口之后，空名称最后。

空值、`null` 和空字符串统一展示为“—”；数量 `0` 必须保留。接口表、详情和历史不展示入/出速率、入/出错误、CRC 错误、错误总数或最后变化；光模块不展示采集状态或内部阈值来源，严重性为正常时不展示原因，只有注意、告警、无光等异常状态显示原因。详情弹窗只展示白名单字段，不序列化任意 DTO。

接口、任务、LLDP 和光模块的稳定机器枚举在展示层集中翻译为中文，API 与筛选值保持原值。接口综合状态、管理/物理/协议状态、介质、类别和端口模式保持独立语义；`protocol_status=down` 展示为 `Down`，不得翻译为“未启用”，`optical` 只展示为“光口”。历史快照中八种固定英文光功率原因使用精确映射，未知设备文本原样保留。接收功率告警色只依据后端 `severity`，使用 `--nc-warning`/`--nc-danger` 语义 Token；组件不得按接收功率数值推断阈值。

配置快照比较、Artifact 下载、受控打开和任务窗口跳转复用现有 config-collection API、统一下载桥接和 Task Center，不复制配置采集业务规则。概览、接口、光模块和 LLDP 的数据来源分别标记为 `devices.db.latest_snapshot`、`devices.db.interfaces.latest_snapshot`、`devices.db.transceivers.latest_snapshot` 和 `devices.db.lldp.latest_snapshot`；LLDP 只展示本地接口、邻居系统名/MAC/接口/IP、PVID、TTL、描述、关联状态和采集时间等白名单字段。关联业务公开契约不返回重复的 AC ID/名称/IP、AP 型号/状态、交换机/接口、光模块严重性及 MR 会话/阶段/耗时/任务字段；历史 Repository 数据不因此删除。CPU/内存只展示 overview 返回的基础摘要。

光模块和轨旁 AP 关联业务只消费 Python 返回的严重性，不在 Vue 计算阈值。`alarm/critical/no_light/link_abnormal/link_down` 使用危险色，`warning/notice` 使用警告色，`normal` 使用正常色；`no_module` 表示端口未安装光模块，属于中性状态，不计作光衰异常，也不得把缺失功率占位符显示为红色。

历史 Repository 行也必须经过后端 DTO 白名单映射，组件不得从任意原始对象透传到表格、历史详情或导出。

命令执行状态只消费后端返回的 `command_profile.executable`。当前通用刷新允许已验证边界内的 H3C/Comware `switch`、`mobile_router` 与 ZTE/ZXR10 `switch` Profile；H3C AC 只读关联 AC Query Service，H3C MR 关联信息只读复用 Online MR Query Service，基础详情刷新走独立 `mobile_router` Profile。Huawei、未知或未验证 Profile 不得由组件回退执行 H3C 命令。

## 测试

修改后先运行设备详情 Panel mount/static、设备管理视图、公共表格和路由定向测试，并运行 `vue-tsc` 与 UI Guard；最终集成再运行全量测试和生产构建。测试应覆盖 overview 快照读取、动态页签、缺失值、正确传输枚举、分页缓存、刷新任务、任务终态刷新、请求竞态、卸载清理、完整详情路由、键盘 resize 和受控详情字段。Electron 多尺寸/多缩放视觉检查仍属于最终人工验收。

## 修改规则

新增字段先更新 `apps/desktop_renderer/src/types/deviceManagement.ts`，再更新 API client 和展示列；不得在组件中猜测后端业务含义。新增用户文案优先进入运行时 i18n。抽屉与完整页继续复用同一 presentation 组件，不复制页面逻辑；样式使用 Element Plus 或 NetConsole 语义 Token，不写固定 light/dark 基础色。

## 生成与清理

本目录不生成运行文件、数据库、日志、Artifact 或缓存。测试 mock、截图和构建产物只允许进入临时目录或标准构建目录，不写回 `src/`；任务、请求、ResizeObserver 和拖拽监听必须在卸载时清理。

## 相关文档

参见 [设备管理页面](../../views/devices/README.md)、[统一表格组件](../table/README.md)、[表格规范](../../../../../docs/ui/TABLE_AND_FIELD_STANDARDS.md)、[UI 设计系统](../../../../../docs/UI_DESIGN_SYSTEM.md) 和 [Codex Skills](../../../../../docs/CODEX_SKILLS.md)。业务事实来源以 Python 后端 DTO、`visible_sections`、capability/profile、阈值和 Task Center 契约为准；当前状态保持 `IMPLEMENTED_UNVERIFIED / REAL_DEVICE_PENDING`。
