# v1.5.13 分支清单与安全分类

审计日期：2026-11-10

## 目标与结果

- 初始目标：`main` `37b0df95a3208d0d03380e76ccfe5419af1422f1`。
- 功能合并后目标：`main` `c2db3f79808fdadfa53f8eddb846ee0da18a6861`。
- `github/main` 保持 `37b0df95a3208d0d03380e76ccfe5419af1422f1`；本轮没有 Push 或修改远程引用。

## 分支分类

| 分支 | HEAD | worktree/状态 | 处理 |
| --- | --- | --- | --- |
| `main` | `c2db3f79` | 正式集成目标 | 保留 |
| `codex-A/global-dataroot-disk-policy` | `d244ebcc` | 主仓库活动工作树，16 个未提交 DataRoot 文件 | 保留，不切换、不提交 |
| `codex-A/r2-3-2-ground-unattended` | `a91a1916` | 独立 worktree，14 个未跟踪 Ground 报告 | 保留，不清理 |
| `codex-A/mesh-analysis-performance-optimization` | `4d2fb5d3` | 无 worktree；`git cherry main` 为补丁等价 `-` | 保留：原 SHA 非祖先，安全 `-d` 不满足，且有远端历史 |
| `codex-A/mesh-analysis-scope-ui-optimization` | `9cd098ed` | 无 worktree；16 个原始提交均显示补丁等价 `-` | 保留：原 SHA 非祖先，安全 `-d` 不满足，且有远端历史 |
| `codex-A/v1.5.13-local-integration` | `f2bbc8ee` | 已合入 `main`，无活动用途 | 已用 `git branch -d` 安全删除 |

## 未删除对象的原因

两个旧 MESH 分支是通过 cherry-pick 进入本轮集成树的，内容由 `git cherry main <branch>` 的 `-` 结果证明已等价包含，但提交身份不是 `main` 的祖先。按要求不使用 `git branch -D`，因此不以“看起来已合并”强行删除。当前 DataRoot 和 Ground 是明确并行任务，必须保留。

