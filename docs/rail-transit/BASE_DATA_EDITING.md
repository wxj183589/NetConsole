# 轨道交通基础资料编辑生命周期

`/rail-transit/base-data` 是轨道交通基础资料的唯一 Web 维护入口。编辑只适用于已授权的局点，页面默认锁定；查询、导入预览、质量问题、导入审计和关联运行状态保持只读。

## 可编辑范围

- 局点基础信息：线路名称、项目类型、网络类型、站序方向名称、对应线路侧映射和备注；局点名称为只读。
- 站点与区间：名称、编码、顺序、起止站、上下行、区间物理里程范围和备注等基础字段。
- 轨旁 AP：名称、点位编码、MAC、归属站点/区间、里程、行车方向和备注。线路方向不在主表直接编辑，后端按正式区间与局点映射推导并继续保存、导出和校验。
- 轨旁 AP 规划：站点、AP 数、起始地址、掩码、网关、管理 VLAN 和备注。
- 车载 MR：名称、管理地址、MAC、协议、端口、归属站点和备注。列车汇总由 MR 关系派生，不能直接写入第二套列车表。

## 编辑会话

页面使用以下状态：

```text
LOCKED -> UNLOCKED_CLEAN -> UNLOCKED_DIRTY
                         -> VALIDATING -> SAVING -> LOCKED
                         -> SAVE_FAILED
```

解锁时读取 `site_id`、`base_revision` 和写入范围，并停止基础资料轮询。服务端快照与 Renderer 草稿分离，轮询或刷新不会覆盖草稿。新增记录使用临时 ID 并显示“新增”；正式记录删除先标记“待删除”，可在提交前撤销。

锁定、刷新、切换页签、路由离开或关闭窗口时，存在未保存修改必须通过统一 Confirm Service 选择保存、放弃或取消。保存失败保留完整草稿和字段错误，不能用重新加载覆盖用户输入。

## 设备站点来源

“从设备管理生成”只读取“车站”分组的 `station` 字段。字段开头 1～3 位数字确定来源顺序，分隔符可省略；正式名称始终去掉数字与分隔符，无数字前缀也可进入草稿。来源预览按“规范站名 + 节点类型”匹配既有资料，匹配项默认建议覆盖现有记录并保留 `id/node_uid`、引用和人工维护字段。车辆段与停车场保留来源编号，但不占用主线 `sort_order`。

只有数字、同名不同类型、同顺序不同站名和同站名不同顺序属于阻断项。来源应用仍只是草稿变更，不会自动保存；既有带编号名称会在用户应用并保存后规范为无编号正式站名。

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

局点元数据、站点、区间、轨旁 AP、车载 MR 和轨旁 AP 规划在同一个 changes 请求中提交。revision 同时覆盖 SQLite 和 `site_meta.json`；任意校验、引用、唯一性、metadata 原子写入或 SQLite 错误都会整体回滚；返回新 revision 后页面重新读取服务端事实并自动锁定。

后端业务校验负责 IP、MAC、里程、站点引用、MR 历史和规划网段等规则；Vue 只做输入展示、轻量状态和字段错误定位。Router 不执行 SQL、设备连接或命令拼接。

## 区间物理里程

区间物理里程是基础资料，不复用 `mileage_min/mileage_max`。后两者继续表示区间内正式归属轨旁 AP 的实际里程统计，即使区间暂时没有 AP，物理范围也能独立存在。新增字段为 `section_mileage_start_m`、`section_mileage_end_m`、`section_mileage_open_end` 和 `section_mileage_source`，沿用 `__base_section__` 记录的 `raw_payload_json` metadata 持久化边界，不修改 SQLite schema。

每条 `path_code` 独立按站点顺序生成。普通相邻站取两个 `center_mileage_m` 的 `min/max`，所以上下行共享同一个从小到大的物理范围。低里程端优先采用可解析的明确端点里程，其次采用端点延伸距离，否则默认到 `0 m`；高里程端同样优先采用明确里程和延伸距离，均未配置时保存为开放终点，不伪造终点数值。缺少或重复中心里程时区间仍生成，但范围标记为 `unavailable` 并在预览中告警；站序与里程方向相反时保留站序，范围仍按 `min/max` 生成并提示核对。

自动区间的物理字段属于生成器管理字段。页面人工修改后将来源改为 `manual` 并写入 `manual_override_fields`，再次生成保留人工值；“恢复自动值”按当前站点资料重算并清除覆盖字段。模板的区间 Sheet 分别导入导出物理起点、物理终点、开放终点、范围来源和人工覆盖字段，原 AP 范围列明确命名为“AP里程统计”。旧局点缺少 metadata 字段时读取为 `unavailable`，旧模板缺少新列时不清空已保存范围。

## 授权

真实写入仍由 Feature Registry、环境开关和局点范围共同控制。Electron Desktop 的受管会话在后端显式启用真实局点写入能力，普通 Server/浏览器不会继承该能力：

```text
web.rail_transit_base_data_write
RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED=1  # Server/副本脚本写入开关；Electron 受管会话不依赖环境变量
NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE=1  # copy_validation 局点
NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE=1  # 正式局点的额外授权
```

未获得写权限时，页面始终保持锁定，后端也拒绝 validate/save 之外的越权写入。Electron 写入必须同时通过短期 `desktop_session_token`；导入预览是独立流程，不复用普通表格的草稿提交。`site_meta.json` 写入只允许当前受控局点，使用临时文件和 `os.replace()`，并保留未知安全字段。

## 定向验证

```text
pnpm exec vitest run src/views/rail-transit/RailTransitBaseDataView.test.ts src/components/rail-transit/base-data/TracksideApPlanningTab.test.ts src/stores/railTransitBaseData.test.ts
.venv/Scripts/python.exe -m pytest tests/test_rail_transit_base_data_edit_api.py tests/test_rail_transit_write_guard.py -q
```
