# Electron-only E2 历史构建产物回收归档

## 结论

2026-07-18 按用户明确授权回收仓库内已另行导出的 Qt 临时终版 `dist/v1.3.8/`。本次只处理可重新生成的历史构建产物，没有修改源码业务数据、当前 Electron v1.3.9 构建、用户应用数据或 Git stash。

## 安全边界

- 新增 `scripts/maintenance/clean_generated_artifacts.py`，目标只能从代码内固定白名单选择。
- 默认仅输出 dry-run 计划；只有显式 `--apply` 才执行。
- 执行前验证 NetConsole 仓库根、解析后的绝对路径、仓库内边界和符号链接。
- 清理 manifest 写入 `%LOCALAPPDATA%\NetConsole\MigrationReports\generated-cleanup-v1.3.8-20260718.json`，不把本机绝对路径提交仓库。
- `data/`、`.local/`、`dist/v1.3.9/`、`dist/electron/` 和两个历史 stash 不在本目标白名单内。

## 实际结果

```text
目标：dist/v1.3.8
文件数：9804
总字节：2629590604
结果：removed
```

## 验证

- 回收脚本单元测试：3 passed。
- Ruff：通过。
- Python 编译检查：通过。
- 回收后 `dist/v1.3.8` 不存在，Git 跟踪状态没有业务文件删除。

## 后续边界

当前 `dist/_build`、`dist/electron` 和 `dist/v1.3.9` 仍用于最终 HEAD 构建与验收，须在验证完成后再按独立白名单回收。仓库历史 `.local/` 和根 `data/` 是业务迁移源，不能使用本脚本清理。
