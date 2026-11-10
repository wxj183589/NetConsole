# 提交祖先与等价补丁

## 起点

- 本地 `main` 起点：`293377a11dfd1075788e0def2825f9ae4a1bb97e`。
- 共同远程基线：`37b0df95a3208d0d03380e76ccfe5419af1422f1`。
- 原始分支 tip 已建立本地恢复引用，未删除 Git 对象。

## 移植映射

| 原始提交 | 集成候选提交 | 内容 |
| --- | --- | --- |
| `2806f09e` | `9615c11d` | Heartbeat/Syslog 基础闭环 |
| `8e403b7f` | `f5e3c469` | Syslog ownership/batch 保护 |
| `b3ccb1bd` | `7eaebe92` | 重复 MR 任务语义 |
| `04bd623f` | `4d9a4e66` | Backend 常驻 Heartbeat |
| `7c143d53` | `94695b07` | Syslog 位置延迟与准确性 |
| `939101fd` | `931ba07c` | Raw Persist 时间边界 |
| `de7ca957` | `51f78ae8` | Ground R2.3.1 |
| `a91a1916` | `49cf57ff` | R2.3.2 集成工具 |
| `d3588c5d` | `9141696d` | Ground R2.3.2 |
| `4c7f70ea` | `333dedcf` | Ground R2.3.3 队列/归档 |
| `18043b99` | `e69f1576` | Ground R2.3.3 报告 |
| `06a2114d` | `0d8225d8` | v1.5.13 便携数据根 |
| `201b0bc0` | `15816629` | v1.5.13 便携验收报告 |

Mesh 两条分支的每个提交均由 `git cherry main <branch>` 标记为等价补丁（`-`），因此未再次复制到整合候选。其原始 tip 和审计结果由 archive refs 保全。

## 最终祖先关系

候选在功能内容完成后使用 ancestry-only merge 记录了两个已移植分支的原始 tip：

- `597bc100`：`git merge --no-ff -s ours codex-A/r2-3-3-ground-unattended`。
- `e83b87e9`：`git merge --no-ff -s ours codex-A/v1-5-13-full-portable`。

两次 merge 使用 `ours` 仅建立提交祖先关系，不改变候选工作树内容，也不表示用一侧内容覆盖另一侧内容。核验结果：Ground、v1、DataRoot 以及两条 Mesh 原始 tip 均可由最终候选 HEAD 到达；13 组源提交与候选移植提交中 12 组 patch-id 完全相等，唯一例外是 `06a2114d -> 0d8225d8`，因五个文件的 v1.5.13/Ground 冲突手工合并而不同，相关行为已由定向回归覆盖。
