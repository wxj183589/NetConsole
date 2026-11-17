# NetConsole v1.5.15 轨旁 AP Git 状态

## 审计基线

- 审计来源分支：`codex-A/trackside-ap-template-station-closure-20261116`
- 当前集成分支：`codex-A/trackside-ap-main-integration-20261117`
- 审计 HEAD：`3f110cf85ec289b8b4d986c8dee40fe646de9d44`
- `github/main`：`eb160480f994a465cc1240e04547eea3b33a583a`
- merge-base：`eb160480f994a465cc1240e04547eea3b33a583a`
- 当前工作树：产品源码无 dirty 修改；验收报告目录为未跟踪内容
- Worktree：仅当前产品 Worktree，无其他 NetConsole Worktree
- Stash：空

## 对账结果

PR #118 已合并到 main，但当前分支的四个产品修复提交 `0d8e4608`、`47b6e421`、`5597d11e`、`3f110cf8` 仍未进入 main。它们涉及七列模板识别、字段说明页过滤、正式 station_id 站点匹配、非正线分类校验和导出重导入；不能删除或假设已合并。

已完成从最新 `github/main` 创建独立集成分支并逐个 cherry-pick 四个产品提交：`6c4b4c84`、`d9e1d08b`、`d751976e`、`945b9f60`。直接相关定向测试为 `17 passed, 1 warning`。验收报告待作为独立文档提交；集成分支待推送并通过正常 PR 处理。原任务分支保留。

## 安全边界

- 不执行 reset、clean、stash、force push、分支删除或 Worktree 强制回收。
- 不触碰 `D:\NetConsoleData`、`D:\NetConsoleData-dev`、`G:\NetConsoleData`。
- 不关闭已有 Node/Vite/NetConsole 进程。
- 不把数据库、原始 Excel、日志、安装包或临时文件加入 Git。
