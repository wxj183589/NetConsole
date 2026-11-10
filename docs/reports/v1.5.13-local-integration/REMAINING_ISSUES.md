# v1.5.13 剩余问题与发布门禁

## 必须保留的限制

1. 全量 Renderer 的 `tracksideSeriesColors` 性能测试在本机为 112.35ms，超过 100ms 阈值；本轮未调整无关算法或放宽测试。
2. AC-MESH 组合运行出现一次 Windows 文件锁时序失败，隔离复跑通过；仍建议在后续稳定性门禁中确认 resident polling 线程退出与 SQLite 句柄释放。
3. 本轮未重复 30 分钟长稳；不得把既有 Phase 11.10/11.9 证据当成本轮新长稳。
4. Excel GUI 未安装；WPS 已有历史打开证据，但不等同于 Excel 实机验收。
5. 真实设备、现场网络、安装/升级/卸载和正式 Release 未执行。
6. Workspace layout 检查继续因既有顶层 `D:/study/NetConsole-Workspace/docs` 失败；不得通过删除或放宽规则获取 PASS。
7. 应用版本源仍为 v1.5.12。本轮 v1.5.13 仅是本地 changelog/集成记录，不是正式版本发布。

## 受保护的未合并状态

- `codex-A/global-dataroot-disk-policy` 的 DataRoot dirty 修改未合入。
- `codex-A/r2-3-2-ground-unattended` 的 Ground worktree、未跟踪报告和独有提交未清理。
- 两个旧 MESH 分支保留，因补丁等价但原提交身份非 main 祖先，且存在远端历史。
