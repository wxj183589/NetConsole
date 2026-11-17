# 杭州地铁9号线昌达路及491条轨旁 AP 验收

- 最终状态：`LOCAL_PASS_GUI_VERIFIED`
- 产品：NetConsole 旧版 v1.5.15
- HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- Branch：`codex-A/trackside-ap-template-station-closure-20261116`
- Site：`hzdt-09` / 杭州地铁9号线
- 实际数据根：`D:\NetConsoleData-dev`
- 本轮未修改源码、未 Push、未创建 PR、未升级版本、未打包。

## 备份

- 备份方式：SQLite Backup API；源连接使用 `mode=ro`，未执行写入。
- 源数据库：`D:\NetConsoleData-dev\sites\hzdt-09\db\devices.db`
- 源库 SHA-256（备份前）：`e372ddfad4cd8026f514ca2da70e5cf7c811ae8f81617739533a3aa35389f3ef`
- 备份文件：`D:\study\NetConsole-Workspace\backups\trackside-ap-station-completion-20261117\hzdt-09-devices-before-gui-final.db`
- 备份 SHA-256：`4ebd1f72793826b281372669678fa87b441f48b145a9b8f06dbaabf40a08020e`
- 备份 `PRAGMA integrity_check`：`ok`
- 源库 WAL 备份前大小：0 bytes；未删除 WAL/SHM。

SQLite Backup API 生成的是一致性备份文件，备份文件 SHA 与源文件 SHA 不要求字节级相同；完整性检查和源库前后 SHA 是本次恢复证据。

## 数据安全

- `PRODUCTION_DATA_MODIFIED=0`
- `DEV_REAL_DATA_MODIFIED=0`（本轮 GUI 预览/导出/unchanged 重导入未产生 AP 数据差异；昌达路和491条记录在本轮开始前已存在）
- `DATABASES_REMOVED=0`
- `USER_WORKBOOKS_MODIFIED=0`
- 未修改 `D:\NetConsoleData`、`G:\NetConsoleData`。
