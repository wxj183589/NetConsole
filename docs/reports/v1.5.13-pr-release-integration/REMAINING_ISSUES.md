# Remaining issues

1. 人工 GUI 验收不可用：本轮只有 packaged startup/smoke，未声称点击级通过。
2. 真实 Windows 安装向导与卸载验收仍为 `PENDING`。
3. 现场设备、真实站点数据、跨机器网络与 WPS/cloud acceptance 未执行，`FIELD_ACCEPTANCE=NOT_AVAILABLE`。
4. 没有创建 GitHub Release 或上传 tag/release 制品；当前制品保存在 workspace release 目录。
5. 旧的历史 release 制品未删除；旧 portable 也仅移入任务临时保留目录，避免覆盖或破坏用户证据。
6. 未触碰 `D:\NetConsoleData`、`D:\NetConsoleData-dev` 或独立 `D:\study\fping`。

这些是诚实的验收边界，不是 CI 门禁失败。
