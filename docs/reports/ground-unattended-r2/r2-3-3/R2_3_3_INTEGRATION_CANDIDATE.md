# R2.3.3 本地集成候选

## 候选信息

- Branch：`codex-A/r2-3-3-ground-unattended`
- 基线：`d3588c5d57cb71e9e0df7fa3d2323f8aeaf28f97`
- 产品实现提交：`4c7f70ea4ab19d55a2a7bae1e3c504d322691de`
- 归档回放和专项报告：同一产品提交中已保全；本目录主报告随后作为独立本地文档提交。
- Push：未执行。
- Merge：未执行。
- 正式发布：未执行。

## 候选内容

- Raw 压缩 queue-full 有界恢复和 health 观测。
- AC Query Duration、timeout、snapshot processing 最小指标。
- API Available / Renderer UI Available / paint-ready 字段与 UI 增量显示。
- 100 MR loopback 突发完整性测试。
- 杭州地铁 10 号线原版归档只读盘点、Syslog/WMESH/Position/Ping/AC/三通道回放。

## 集成边界

专项 Ground、Renderer、Electron 和回放证据可复现；整仓库 Full Gate 仍为 `PARTIAL`，package-smoke 被正式安装器的 clean-worktree 保护阻断，UI Visible 证据没有直接显示 AP 详情值。因此这是“可审阅的本地集成候选”，不是 `RELEASE_READY`，也不是现场验收结论。
