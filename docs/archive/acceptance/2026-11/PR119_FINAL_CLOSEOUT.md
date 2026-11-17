# PR #119 最终收口记录

## 范围

- 产品：NetConsole 旧版 v1.5.15
- PR：[#119](https://github.com/wxj183589/NetConsole/pull/119)
- 分支：`codex-A/trackside-ap-main-integration-20261117`
- 原始 PR HEAD：`e5227f0c`
- 修复后 PR HEAD：`afe29922`
- 基线：`github/main=eb160480`
- 本轮目标：修复 PR #119 的 CI 门禁和代码审查问题，归档验收证据，并安全收口本地分支。

## 原始失败与修复

PR #119 首次检查运行 `44015127665` 时有两类失败：

1. `Docs, path, and diff guards`：验收报告提交在仓库根 `reports/`，不符合仓库报告路径规则。
2. `Python regression without baseline debt`：目录 README 门禁报告缺少 `reports/README.md` 和 `reports/tests/README.md`。

修复方式：

- 将验收证据从根 `reports/tests/trackside-ap-station-completion-20261117/` 迁移到 `docs/archive/acceptance/2026-11/trackside-ap-station-completion-20261117/`。
- 新增 2026-11 归档 README，并更新验收归档索引；根 `reports/` 不再保留本次提交产生的目录。
- 保留报告原文和证据内容，不放宽路径白名单，不修改测试阈值。

## 代码审查修复

已处理上一轮 Codex review 的三个未解决发现：

- P1：轨旁 AP 导入预览的十项统计标签统一通过 `t()` 和 Renderer locale 词条提供，英文界面不再显示硬编码中文。
- P2：七列导出在站点名称为空时保留区间名称；重导入时对当前 Site 做精确区间匹配，区间归属 AP 可以闭环往返。
- P2：非正线 AP 允许空 `station_id`，但所有非空 `station_id` 仍必须存在于当前 Site 的正式站点集合，避免保存悬空关系。

对应回归覆盖了 i18n、区间 AP 七列导出重导入、车辆段/停车场空站点 ID，以及非正线有效和无效 `station_id`。

## 本地验证

- 交接记录中的 Python 扩展定向测试：`56 passed, 2 warnings`。
- Renderer i18n/source 定向测试：`9 passed`。
- Renderer 基础资料行为定向测试：`40 passed`。
- 本轮最终 Python 定向测试：`45 passed, 2 warnings`；另有目录 README 测试 `1 passed`。
- Ruff：通过；修改 Python 文件 `py_compile`：通过。
- Renderer locale/source：`9 passed`；基础资料行为：`40 passed`；Renderer build：通过。
- 仓库根目录布局和文件白名单：通过；`git diff --check`：通过。
- `python -m scripts.check_workspace_layout --repo-only`：被既有 Workspace 外部状态阻断；发现 `.tmp` 和历史 `temp/trackside-ap-*` 目录，未由本轮创建，按规则未删除。

未执行全量 Python、全量 Renderer、全量 Electron 或完整发布门禁；它们由 PR CI 负责最终复核。

## 数据与交付安全

本轮未访问或修改生产数据、真实开发数据库、用户工作簿、版本号、安装包或其他业务数据：

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
USER_WORKBOOKS_MODIFIED=0
DATABASES_DELETED=0
```

没有执行强制推送、合并 `main`、删除远程分支或回收其他 Worktree。当前 PR 分支在 PR #119 合并前保留。

## 最终状态

本报告对应修复提交 `afe29922`。PR #119 的新一轮 workflow `44030468507` 已通过全部 Required Checks（含 blocking gates）；PR 仍保持 OPEN，尚未合并 `main`。

## 分支回收

- 已安全删除本地 `codex-A/trackside-ap-base-ui-simplification-20261116`（`d094d26f`）。
- 已安全删除本地 `codex-A/trackside-ap-import-station-switch-fix-20261116`（`08da6185`）。
- 保留当前 PR 分支 `codex-A/trackside-ap-main-integration-20261117`，并保留仍含未合并后续提交的 `codex-A/trackside-ap-template-station-closure-20261116`。
- 未删除远程分支、未删除其他 Worktree、未强制回收任何引用。

最终状态：`PR119_REQUIRED_CHECKS_PASS_PENDING_MERGE`。
