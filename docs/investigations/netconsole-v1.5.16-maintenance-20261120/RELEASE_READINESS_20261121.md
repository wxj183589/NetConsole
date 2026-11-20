# NetConsole v1.5.16 合并后发布准备判断

日期：2026-11-21（Asia/Shanghai）

## 状态

```text
MAIN_INTEGRATION=PASS
POST_MERGE_L3_GATE=PASS
SUPPLEMENTAL_ACCEPTANCE=PARTIAL
DATA_SAFETY=PASS
RELEASE_READINESS=PARTIAL
OVERALL_STATUS=PARTIAL
```

## 判断依据

- PR #125 已正常 Squash Merge，最终 `github/main` 为 `5ba59a41434ee86cca846ac9fac702a8df27b2eb`，无未解决冲突。
- 固定该 SHA 的本地 Full Gate 全部通过：Python 5620/2 skipped、Renderer 211/1544、Electron 38/315、Architecture 12/12、Main contract 12、Docs/path 22，Ruff/layout/diff-check 通过。
- 原验收矩阵的 9 项 PASS 保持有效；7、8、9、11、12、13 六项仍缺真实设备、人工 GUI、8 小时、完整站序或 Win10 20H2 证据，因此不能提升为 PASS。
- 未创建正式 Release、Tag 或新安装包；当前不宣称 v1.5.16 正式发布完成，仅允许进入后续受控发布候选准备。

## 真正未完成事项

1. 获得明确逐设备只读授权后，完成 Heartbeat 真实 AP/站点新鲜度和 V5 AC/FIT-AP 脱敏回显。
2. 在真实 Electron 的 1920x1080 与 2K 环境完成 MR 监控截图、Resize 和同步交互记录。
3. 使用独立合成测试根完成不少于 8 小时的生命周期、Heartbeat/Syslog、Quick Ping、SQLite、进程和恢复记录。
4. 使用完整 canonical 站点资料完成 AC/Mesh-Link 站序、车辆段/停车场置底和端口排序验收。
5. 在 Windows 10 20H2 实机完成 Storage Audit 的 ACL、中文路径、安装态菜单和错误状态验收。

完成上述外部验收后，另行执行 Release Gate；本报告不授权生产数据迁移、设备写入、安装包发布或 GitHub Release 创建。
