# 杭州地铁9号线昌达路及491条轨旁 AP 验收

- 最终状态：`LOCAL_PASS_GUI_VERIFIED`
- 产品：NetConsole 旧版 v1.5.15
- HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- Branch：`codex-A/trackside-ap-template-station-closure-20261116`
- Site：`hzdt-09` / 杭州地铁9号线
- 实际数据根：`D:\NetConsoleData-dev`
- 本轮未修改源码、未 Push、未创建 PR、未升级版本、未打包。

## GUI 导出

- GUI 导出任务：`rail-export-fe93a2c9d3cd4f3facb50d44c6b78cdd`
- 任务状态：`COMPLETED` / `SUCCESS`
- Artifact：`杭州地铁9号线_轨旁AP基础资料_20261117_034644.xlsx`
- Artifact SHA-256：`8facd0627832a3848a08029d045c4b159da1d67847829817f24ddb23e0ac9e1b`
- 下载证据：`D:\study\NetConsole-Workspace\.tmp\trackside-ap-final-20261117\杭州地铁9号线_轨旁AP基础资料_GUI导出_20261117.xlsx`
- `轨旁AP` 数据行：491
- 业务列：7列，依次为 AP名称、AP MAC、归属位置、上联交换机、上联端口、建设阶段、位置类型。
- `字段说明` 和 `_netconsole_meta` 存在，说明页未混入数据。

## GUI 重导入

下载的七列 Artifact 通过真实 Electron 当前页的“导入并预览”重新导入，结果为：总行数491、可导入491、新增0、更新0、不变491、冲突0、无效0。应用到草稿后保存按钮保持禁用，符合 unchanged 保护；没有人为改字段制造写入。

## 排序

页面首屏按站序从观音塘开始，端口顺序为数字逻辑顺序；昌达路筛选中端口顺序为 `1/0/1`、`1/0/2`、`1/0/3`、`1/0/13`、`1/0/14`、`1/0/15`、`2/0/1`、`2/0/2`、`2/0/3`、`2/0/13`、`2/0/14`、`2/0/15`。
