# NetConsole v1.5.16 六项补充验收更新

日期：2026-11-21（Asia/Shanghai）  
结论：六项均保持 `PARTIAL`；没有用自动化、Mock 或短时运行替代现场证据。

| 项目 | 原状态 | 本轮状态 | 真实证据 | 剩余问题 |
| --- | --- | --- | --- | --- |
| 7. Heartbeat AP/站点关联与新鲜度 | PARTIAL | PARTIAL | 合并后 Python/Renderer Full Gate 通过；自动化覆盖 AP、站点、MAC、更新时间和 AC 状态展示契约 | 未获逐设备只读授权，未做 AC 切换后的真实现场回放；不能确认真实采集及时性 |
| 8. MR 监控 GUI | PARTIAL | PARTIAL | Renderer `211/1544`、typecheck/build 通过；组件契约覆盖布局、事件折叠、中文状态和图表模型 | 未在真实 Electron 1920x1080 与 2K 窗口完成截图、Resize 和人工同步交互验收 |
| 9. 8 小时长稳与故障恢复 | PARTIAL | PARTIAL | 合并后 Python/Electron/Renderer 全量回归通过；确定性关闭、DTO 和资源生命周期回归通过 | 本轮未运行完整 8 小时；不能推断 Renderer crash、内存/句柄趋势或强杀恢复已验证 |
| 11. V5 AC/FIT-AP 兼容 | PARTIAL | PARTIAL | 当前 main 的 V5 fallback、fixture、命令白名单和快照保护包含在自动化回归中 | 无真实 V5 AC/FIT-AP 只读回显授权；命令兼容和部分成功语义仍待脱敏现场证据 |
| 12. AC/Mesh-Link 站点与端口排序 | PARTIAL | PARTIAL | 页面回归、服务端顺序保持、Peer MAC 回退和端口逻辑测试通过 | 缺少完整 canonical 站点/车辆段/停车场真实数据，未完成现场站序和方向展示核验 |
| 13. Windows 10 20H2 Storage Audit | PARTIAL | PARTIAL | Storage Audit API/UI、错误状态区分、Renderer build 和 Main contract 通过 | 当前环境非 Win10 20H2；ACL、中文路径、安装态 Electron 菜单和实机截图未验证 |

## 约束

- 未连接真实设备，未下发配置写命令。
- 未读取或写入 `D:\NetConsoleData`、`D:\NetConsoleData-dev`。
- 未生成新的 Installer/Portable、Release 或 Tag。
- 不把 PR 分支 CI 结果代替合并后主线结果；本轮主线证据见 `L3_POST_MERGE_FULL_GATE_20261121.md`。
