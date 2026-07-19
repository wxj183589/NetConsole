# 轨道交通基础资料编辑生命周期

`/rail-transit/base-data` 是轨道交通基础资料的唯一 Web 维护入口。编辑只适用于已授权的局点，页面默认锁定；查询、导入预览、质量问题、导入审计和关联运行状态保持只读。

## 可编辑范围

- 站点与区间：名称、编码、顺序、起止站、上下行、备注等基础字段。
- 轨旁 AP：名称、点位编码、MAC、归属站点/区间、里程、线路方向和备注。
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

站点、区间、轨旁 AP、车载 MR 和轨旁 AP 规划在同一个 changes 请求中提交。任意校验、引用、唯一性或 SQLite 错误都会整体回滚；返回新 revision 后页面重新读取服务端事实并自动锁定。

后端业务校验负责 IP、MAC、里程、站点引用、MR 历史和规划网段等规则；Vue 只做输入展示、轻量状态和字段错误定位。Router 不执行 SQL、设备连接或命令拼接。

## 授权

真实写入仍由 Feature Registry、环境开关和局点范围共同控制：

```text
web.rail_transit_base_data_write
RAIL_TRANSIT_BASE_DATA_WRITE_ENABLED=1
NETCONSOLE_ALLOW_BASE_DATA_COPY_WRITE=1  # copy_validation 局点
NETCONSOLE_ALLOW_REAL_BASE_DATA_WRITE=1  # 正式局点的额外授权
```

未获得写权限时，页面始终保持锁定，后端也拒绝 validate/save 之外的越权写入。导入预览是独立流程，不复用普通表格的草稿提交。

## 定向验证

```text
pnpm exec vitest run src/views/rail-transit/RailTransitBaseDataView.test.ts src/components/rail-transit/base-data/TracksideApPlanningTab.test.ts src/stores/railTransitBaseData.test.ts
.venv/Scripts/python.exe -m pytest tests/test_rail_transit_base_data_edit_api.py tests/test_rail_transit_write_guard.py -q
```
