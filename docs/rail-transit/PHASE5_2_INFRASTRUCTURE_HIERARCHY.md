# 基础设施工程层级与真实开发数据验证

Phase 5.2，基线产品`250bee85`、DevStatus`f3169e8`。实施范围为基础设施只读展示，不修改基础资料、设备资产、Phase 4专业算法、关系写入契约或Schema。延用Phase 5.1三栏列宽、高度和窄窗切换。

## 工程树和字段

工程树保留控制中心、正线车站、车辆段与停车场、车载设备四个顶层分组；站间区间位于正线车站的轻量子分组，不再与正线车站平级。区间保留原UID、两个端点和设备关系；仅根据端点稳定UID查已存在站点编号生成展示名称，不用名称推断关系。上下行/线路侧继续区分，端点无完整编号时保留原名。

站点、区间、车辆段以现有交换机UUID组织设备，交换机下AP只读取正式Trackside Query确认的Identity/LLDP关联。当前节点内同设备UUID去重展示；不跨工程节点删除合法服务范围。未关联入口保留，数量为0时不加数字；选择设备后可查看原DeviceDetailPanel，也可显式选择工程节点调用既有关系编辑器，不自动关联。

默认仅保留基本信息、工程关系、关联设备；工程关系及名称历史按需展开。名称在当前节点标题显示一次，空编号/工程名/项目/型号/位置不生成空行；内部UUID不在基础设施普通详情显示。右侧详情沿用原组件，隐藏其内部UUID副标题，不重写接口、光模块、LLDP、配置或任务逻辑。

| 节点 | 默认字段 |
| --- | --- |
| 控制中心 | 名称、COCC/BOCC类型、非空项目、关联设备 |
| 正线车站 | 编号、不同的有效工程名、多项目及阶段、下属交换机数、关联区间 |
| 站间区间 | 编号式名称、两个端点、非空项目、资料AP数量、关联交换机 |
| 车辆段/停车场 | 名称、类型、非空项目、交换机数、已确认交换机关联AP数量 |
| 列车 | 编号、正式活动MR-CT/MR-CW、当前关系状态；无assignment明确未配置 |
| 交换机 | 原查询返回的型号、工程节点、物理安装位置、关联AP；IP/MAC/SN仍在右侧 |

多项目按项目ID保留，不用名称去重。工程名只显示不同于正式名的有效engineering alias；过去工程名和历史名折叠。旧列车目录存在不等于有正式CT/CW assignment，禁止按设备名补齐。

基础设施自有`/api/rail-transit/infrastructure/switch-aps`新增独立只读响应DTO：携带原查询的身份状态、识别原因、点位区间ID、partial与不可用来源；原基础资料兼容API及原DTO不变。只确认的switch/AP关系进入树，身份冲突不能变成已关联。查询失败/部分数据不显示0；AP身份不明不展示内部UUID代替名称。资料AP数与交换机已确认AP数量分别标明来源，不混为一项。

## 真实数据方法和限制

数据Authority为`D:/NetConsoleData-dev`，生产根未访问。普通应用启动存在数据库初始化、Identity索引和恢复写入，因此不直接启动原Authority。用户本轮明确授权一致性副本：使用SQLite Backup API只建立两个选定局点的单库candidate与必要描述元数据，不复制完整Site、数据根、任务库、凭据配置或原始日志。报告记录源数据库、空WAL、SHA256、mtime、时间和候选路径。

原库初次普通`mode=ro`审计刷新了三个devices.db-shm文件；主数据库、WAL和配置未变。随后只在WAL为空、源字节稳定时使用`mode=ro&immutable=1`，前后核对；没有checkpoint、VACUUM、回写SHM或伪造mtime。因SHM副作用，本轮不能宣称整个原始根逐字节完全未修改；业务数据未修改与SHM元数据变化必须分别报告。

候选启动沿用既有初始化，会在候选库增加当前工程表，但本轮未改Schema代码、未给原库迁移。对比启动前原库投影和候选投影，缺失工程事实不补造。首个候选出现一条`desktop-session`手工MR关系保存，审计原因“1”；非自动化脚本写入，不在原库，保留记录不回滚，不用于原生MR场景验收。最终主验收使用未受该操作影响的第二候选，候选级关闭工程/资料写Feature和采集动作，正式库不受影响。

真实数据有多车站、交换机、车辆段、停车场、列车目录和未关联设备，但没有正式工程区间、工程多项目/别名、原生CT/CW工程assignment；场景记为NOT AVAILABLE。确认AP证据不足时不按名称/MAC近似或业务IP补关联；不得以模拟fixture替代真实场景。多项目、端点、名字历史和AP冲突规则通过定向测试验证，不能写成真实数据全场景已验收。

采集保护：候选运行`NETCONSOLE_COLLECTION_MODE=disabled`，关闭AC轮询、Heartbeat/Syslog、Quick Ping和自动采集；不点击连接/刷新采集，不连接真实设备。候选级写Feature关闭，`can_write=false`，`can_delete=false`。

## 验证与交接

实际Electron使用上述候选数据在1648×927、1920×1080、2560×1440运行。现有场景验证与缺失场景分别记录；页面无整体横向溢出，原三栏宽度、高度保留。原基础资料9Tab、导入审计、API、独立Store/路由/Feature不变。

风险L3（基础设施自有只读DTO扩展）。前置消费者审计、原始清单、快照来源、字段清单、定向命令、截图和最终交付结果见Workspace报告`reports/tests/infrastructure-hierarchy-simplification-phase5-2/`。文档和DevStatus不提交真实数据库、身份/设备清单或截图。

总体状态：PARTIAL。实施和可用真实场景定向通过，但完整真实场景不可用，并保留初始SHM元数据副作用。Full Gate、真实设备连接、安装包、原生DPI、长稳和main合并验证NOT RUN。后续缺失资料维护须独立授权，不因本轮展示验证自动修复真实数据。

实施提交`f48ffd45`已完整重启Electron复验：三个视口共42张真实候选截图，pageerror为空。最终Renderer11文件/121项、后端85项、API收口5项、Main Smoke12项、Architecture12/12（0waived）、Ruff、TypeScript/Renderer构建与文档检查通过；批次重叠不合计。候选设备/基础资料/AP Identity与原库逐表一致；原主库/WAL/config文件hash、大小、mtime一致，三个SHM变化单列保留。最终Git、远端与进程核对在交付报告中记录。

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_BUSINESS_DATA_MODIFIED=0
DEV_SOURCE_SHM_METADATA_CHANGED=3
DATABASES_REMOVED=0
REAL_DEVICE_CONNECTIONS=0
MAINTENANCE_AUTHORIZED=NO
```
