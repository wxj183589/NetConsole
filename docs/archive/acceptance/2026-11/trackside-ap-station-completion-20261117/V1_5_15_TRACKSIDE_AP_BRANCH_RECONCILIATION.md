# NetConsole v1.5.15 轨旁 AP 分支对账

- 审计对象：`codex-A/trackside-ap-template-station-closure-20261116`
- 审计 HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- GitHub main：`eb160480f994a465cc1240e04547eea3b33a583a`
- 对账日期：2026-11-17
- 当前结论：`LOCAL_PARTIAL_UNMERGED_PRODUCT_CODE`
- 集成分支：`codex-A/trackside-ap-main-integration-20261117`

## Git 结果

`github/main` 是当前分支的祖先。`git log --left-right --cherry-pick github/main...HEAD` 和 `git cherry -v github/main HEAD` 均显示以下5个提交为当前分支独有：

| Commit | 内容 | 对 main 的判断 |
|---|---|---|
| `0d8e4608` | 七列模板、正式站点精确匹配、导出模型重构 | `GENUINELY_MISSING` |
| `47b6e421` | 字段说明页过滤和七列重导入回归 | `GENUINELY_MISSING` |
| `5597d11e` | 非正线位置允许空 station_id 的校验修复 | `GENUINELY_MISSING` |
| `4ad43b13` | GUI 验收报告 | `REPORT_ONLY` |
| `3f110cf8` | 非正线导出重导入和站点/位置回归 | `GENUINELY_MISSING` |

## main 既有合并

PR #118 `精简轨旁 AP 基础资料并闭环站点台账` 已合并，merge commit 为 `eb160480`，包含 `08da6185` 和 `d094d26f` 的实现。它提供了早期基础资料界面、站点匹配和导入框架，但没有包含当前分支后续的七列基础模板闭环及非正线修复。

当前分支提交没有被 `git cherry` 识别为已合并或 patch-id 等价提交；同时 `github/main..HEAD` 的源码差异包含18个文件、970 additions / 151 deletions，不能按分支名称或功能相似直接认定已合并。

## 集成结果

已从最新 `github/main` 建立集成分支，并按最小范围 cherry-pick 产品提交：

| 集成 Commit | 来源 |
|---|---|
| `6c4b4c84` | `0d8e4608` |
| `d9e1d08b` | `47b6e421` |
| `d751976e` | `5597d11e` |
| `945b9f60` | `3f110cf8` |

集成后直接相关回归为 `17 passed, 1 warning`。产品代码现在位于独立集成分支，尚未进入 `github/main`，因此最终仍需正常 PR、Required Checks 和 Review。

## 结论

main 已包含 PR #118 的基础实现；当前分支的后续导入模板和保存校验修复是有效产品差异，已移植到独立集成分支。当前不直接修改 main，不使用无条件 merge、ours 策略或 force push。
