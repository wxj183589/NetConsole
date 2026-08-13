# 轨道交通基础资料编辑生命周期

`/rail-transit/base-data` 是轨道交通基础资料的唯一 Web 入口，默认落在“基础资料总览”查看态。总览、站点与区间、轨旁 AP、轨旁 AP 规划、列车与车载 MR 都先展示已保存数据；用户必须点击各自的“解锁当前子页”后，才为该 scope 建立草稿并显示输入、选择、增删和保存控件。不存在全局解锁、全局草稿或全局保存。数据质量、导入预览、导入审计和关联运行状态始终只读。

## 可编辑范围

- 局点基础信息：线路名称、项目类型、网络类型、站序方向名称、对应线路侧映射和备注；局点名称为只读。
- 站点与区间：名称、编码、顺序、起止站、上下行、区间物理里程范围和备注等基础字段。
- 轨旁 AP：名称、点位编码、MAC、归属站点/区间、里程、行车方向和备注。线路方向不在主表直接编辑，后端按正式区间与局点映射推导并继续保存、导出和校验。
- 轨旁 AP 规划：站点、AP 数、管理 VLAN 和备注；站点只通过设备管理来源预览生成或手工维护，不从规划模板导入。
- 车载 MR：名称、管理地址、MAC、协议、端口、归属站点和备注。列车汇总由 MR 关系派生，不能直接写入第二套列车表。

## 编辑会话

每个维护子页独立使用以下状态：

```text
VIEW -> EDITING -> DIRTY -> VALIDATING -> SAVING -> VIEW
         ^           ^         |             |
         +-----------+---------+-------------+-- SAVE_FAILED
READ_ONLY
```

页面加载或切换 Tab 不创建编辑草稿。用户解锁当前子页后，页面调用 `GET /api/rail-transit/base-data/edit-snapshot?scope=...`，在同一 revision 边界取得该子页实体和必要只读依赖；编辑基线只来自该作用域快照，不使用带分页、搜索或当前筛选的查看列表拼接。快照成功且写权限仍有效时才复制纯 DTO 草稿；失败不建立部分草稿，并显示明确只读原因。总览 scope 可编辑线路名称、项目类型、网络类型、主线路径编码、方向/线路侧、行驶头端和备注；局点 ID、来源分组/字段、更新时间和说明仍是系统事实。新增记录使用稳定领域 ID 或临时记录 ID并显示“新增”；正式记录删除先标记“待删除”，可在提交前撤销。

切换内部标签时，干净编辑会话直接释放并回到 `VIEW`；脏子页提供“保存并切换 / 放弃并切换 / 取消切换”。离开路由、关闭窗口或切换局点时，脏子页同样提供“保存并继续 / 放弃修改并继续 / 继续编辑”，不自动保存或静默丢弃。保存成功、放弃修改或手工刷新都会销毁当前 scope 草稿并回到 `VIEW`；保存失败进入 `SAVE_FAILED` 并保留完整草稿和字段错误。revision 冲突禁止覆盖，用户只能刷新服务器数据并重新解锁。只读轮询可以继续刷新正式数据，但不得覆盖任何已解锁子页草稿。离开基础资料模块后再次从普通入口进入，必须回到总览；只有 URL 明确携带 `?tab=...` 时才进入指定维护子页。

编辑快照遵循 `Router -> Application Service -> Query Service -> Repository`。Repository 使用 SQLite `mode=ro`、`PRAGMA query_only` 和只读事务按 `scope` 读取当前子页实体及必要依赖，并在读取前后核对局点 metadata；接口不初始化或迁移 schema，不写 revision/缓存，不连接设备，不加载 AC/MESH 运行态，也不触发 AP Identity rebuild。查看态同类刷新若已有请求在途，会复用并等待同一个 Promise，调用方不会因“正在刷新”而提前成功返回。

## 设备站点来源

“从设备管理生成”只读取“车站”分组的 `station` 字段。字段开头 1～3 位数字确定来源顺序，分隔符可省略；正式名称始终去掉数字与分隔符，无数字前缀也可进入草稿。来源预览按“规范站名 + 节点类型”匹配既有资料，匹配项默认建议覆盖现有记录并保留 `id/node_uid`、引用和人工维护字段。车辆段与停车场保留来源编号，但不占用主线 `sort_order`。

只有数字、同名不同类型、同顺序不同站名和同站名不同顺序属于阻断项。来源应用仍只是草稿变更，不会自动保存；既有带编号名称会在用户应用并保存后规范为无编号正式站名。

轨旁 AP 规划资格与主线区间拓扑资格分离。启用的普通站、车辆段和停车场都可生成逐站规划；`participates_in_direction` 只决定普通站是否参与主线区间生成，不过滤车辆段或停车场规划。新增规划行默认 `planned_ap_count=0`、`management_vlan=null`，并按“普通站正式顺序、车辆段、停车场、其他历史手工行”稳定排序。车辆段和停车场保持自身 `node_type`，不会因此生成主线区间。

## 保存链路

```text
Vue 草稿
  -> POST /api/rail-transit/base-data/validate
  -> RailTransitBaseDataApplicationService
  -> BaseDataWriteGuard + revision 校验
  -> POST /api/rail-transit/base-data/changes
  -> RailTransitBaseDataRepository
  -> SQLite BEGIN IMMEDIATE 单事务
```

每次 changes 请求只允许提交其 `scope` 对应的实体：总览写局点元数据，站点与区间写站点、设备 `station_id` 绑定和区间，轨旁 AP 写 AP，规划写 `trackside_ap_plan`，列车与车载 MR 写 MR。后端在事务前拒绝任何跨作用域实体。revision 同时覆盖 SQLite 和 `site_meta.json`；任意稳定 ID、引用、唯一性、metadata 原子写入或 SQLite 错误都会使本次子页保存整体回滚；返回新 revision 后页面只刷新受影响正式数据、销毁当前草稿并回到 `VIEW`。

后端业务校验负责 IP、MAC、里程、站点引用、MR 历史和逐站规划唯一性等规则；规划中的 AP 起始地址、掩码和网关只作参考，不触发地址分配或网段容量计算。Vue 只做输入展示、轻量状态和字段错误定位。Router 不执行 SQL、设备连接或命令拼接。

## 区间物理里程

区间物理里程是基础资料，不复用 `mileage_min/mileage_max`。后两者继续表示区间内正式归属轨旁 AP 的实际里程统计，即使区间暂时没有 AP，物理范围也能独立存在。新增字段为 `section_mileage_start_m`、`section_mileage_end_m`、`section_mileage_open_end` 和 `section_mileage_source`，沿用 `__base_section__` 记录的 `raw_payload_json` metadata 持久化边界，不修改 SQLite schema。

每条 `path_code` 独立按站点顺序生成。普通相邻站取两个 `center_mileage_m` 的 `min/max`，所以上下行共享同一个从小到大的物理范围。低里程端优先采用可解析的明确端点里程，其次采用端点延伸距离，否则默认到 `0 m`；高里程端同样优先采用明确里程和延伸距离，均未配置时保存为开放终点，不伪造终点数值。缺少或重复中心里程时区间仍生成，但范围标记为 `unavailable` 并在预览中告警；站序与里程方向相反时保留站序，范围仍按 `min/max` 生成并提示核对。

自动区间的物理字段属于生成器管理字段。页面人工修改后将来源改为 `manual` 并写入 `manual_override_fields`，再次生成保留人工值；“恢复自动值”按当前站点资料重算并清除覆盖字段。模板的区间 Sheet 分别导入导出物理起点、物理终点、开放终点、范围来源和人工覆盖字段，原 AP 范围列明确命名为“AP里程统计”。旧局点缺少 metadata 字段时读取为 `unavailable`，旧模板缺少新列时不清空已保存范围。

## 授权

真实写入仍由 Feature Registry、环境开关和局点范围共同控制。Electron Desktop 的受管会话在后端显式启用真实局点写入能力，普通 Server/浏览器不会继承该能力：

```text
capability.rail_base_data.write
RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED=1  # Server/副本脚本写入开关；Electron 受管会话不依赖环境变量
NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE=1  # copy_validation 局点
NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE=1  # 正式局点的额外授权
```

未获得写权限时，维护子页为 `READ_ONLY`，不显示“编辑”、生成站点、导入或增删入口，后端也拒绝越权写入。Electron 写入必须同时通过短期 `desktop_session_token`；导入预览只在对应可写维护子页中进入，确认结果仅应用到该子页草稿。`site_meta.json` 写入只允许当前受控局点，使用临时文件和 `os.replace()`，并保留未知安全字段。

稳定 ID、规划 reconcile、事务顺序、业务投影和迁移规则见 [轨旁 AP 主数据与关联模型](./TRACKSIDE_AP_DOMAIN_MODEL.md)。

## 定向验证

```text
pnpm exec vitest run src/views/rail-transit/RailTransitBaseDataView.behavior.test.ts src/components/rail-transit/base-data/TracksideApPlanningTab.behavior.test.ts src/stores/railTransitBaseData.test.ts
.venv/Scripts/python.exe -m pytest tests/test_rail_transit_base_data_edit_api.py tests/test_rail_transit_write_guard.py -q
```
