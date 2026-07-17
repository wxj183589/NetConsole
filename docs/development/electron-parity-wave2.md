# Electron 对等迁移第二波归档

## 结论

第二波以 `main@ee88fd01` 为起点，在 `codex/electron-parity-wave2-integration` 集成 21 个中文逻辑提交，并以 fast-forward 方式进入 `main`。本波不建立第二套 Renderer、Task、Artifact、设置或功能开关体系；Electron 继续复用唯一 Vue、FastAPI 组合根、Application Service、Task Center、Export Process 和严格 Native Bridge。

v1.3.9 起 Electron 是唯一正式桌面产品方向。Qt 已完成既有打包成果，不再进入新版本发布和新功能门；源码暂留作为真实功能、字段、命令和交互的迁移事实源，只有在全部有效功能达到可执行、可持久化、可恢复并完成真实验收后才能删除。无线勘测与 SNMP Center 继续排除。

## 已集成范围

- 系统设置与中央功能 profile：主题、语言、工具路径、功能预览、工程师包选项、原子保存和运行时 Gate 刷新。
- 网络工具：Ping/fping/TCP、持续结果游标、iPerf、无线扫描、状态网格、分页、详情和安全导出。
- 命令参考：实时查询、独立导航、统一任务窗口导出、取消终态和公开文件名收口。
- 应用日志与安全维护：脱敏显示、白名单清理、取消/恢复、日志与许可证导出、Artifact 下载。
- 公共桌面契约：统一任务窗口、Artifact、Desktop Bridge、受管下载、打开文件/目录、终态竞态和 Renderer 路径边界。

第一波已进入 `main` 的设备、AC/FIT-AP、轨道交通、配置采集和文件管理在本波公共契约上完成组合回归。所有缺少真实设备或原生桌面点击的模块继续使用 `IMPLEMENTED_UNVERIFIED` 或 `REAL_DEVICE_PENDING`，不得写成 `COMPLETE`。

## 自动验证

| 范围 | 结果 |
| --- | --- |
| Python 组合测试 | 2577 passed、2 skipped、1 deselected |
| 唯一 deselect | 旧 Qt PyInstaller 实包冒烟；Qt 已退出 v1.3.9 发布门 |
| Vue | 58 files、174 tests passed；typecheck/build passed |
| Electron | 10 files、70 tests passed；typecheck/main/preload build passed |
| Electron smoke | 开发资源 PASS、生产资源 PASS、无效 Python 预期失败 PASS |
| 退出清理 | 5173、Electron、Vite、受管 Python 无残留 |
| Ruff | 改动范围 PASS；全仓 125 项既有基线未扩大修复 |
| 文档 | 相对链接检查 PASS |

## 未完成验收

- Electron 原生选择文件、选择目录、另存为、打开文件和定位目录仍需用户在最终 `main` 人工点击。
- SSH/Telnet/SNMP、真实 AC/FIT-AP、Online MR、fping/iPerf、SFTP、大文件中断恢复和外部终端仍需对应现场环境。
- Electron 安装包、冻结 Python backend bundle、签名、升级、托盘和卸载仍是后续独立阶段。

## 资源回收

- 已完成或被替代的 Codex 后台任务在结果采纳后归档，模型容量错误且无代码回合的任务不再保留为空闲任务。
- 第二波合入并双远端推送后，删除所有非 `main` 登记 worktree 与已吸收/明确放弃的本地分支。
- CentOS 7、Windows Legacy、旧 Qt 临时终版明确放弃，未提交实验内容不进入 `main`。
- 不删除远端历史分支；远端只更新 `main`，避免扩大不可逆清理范围。
