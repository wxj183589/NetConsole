# maintenance

## 用途

本目录保存可审计、可重复运行的本机维护脚本，包括历史运行数据迁移、测试垃圾清理、构建产物回收和专项诊断。

## 边界

- 清理、迁移和修复脚本默认只读或只生成计划，必须显式传入 `--apply`、`--repair` 等对应变更参数才能改动文件。
- 所有可删除路径必须使用固定白名单、解析绝对路径并拒绝链接越界。
- 不得在本目录实现设备业务、数据库 Repository 或发布入口。

## 主要入口

- `migrate_legacy_runtime_data.py`：无覆盖迁移仓库历史运行数据。
- `clean_test_artifacts.py`：清理明确白名单内的历史测试临时项。
- `clean_generated_artifacts.py`：回收明确白名单内、可重新生成的构建产物。
- `check_desktop_bootstrap.py`：只读检查 Electron bootstrap；`--repair` 先备份并原子修复临时/失效的数据根和局点引用，不移动业务数据。
- `rebuild_mesh_parsed_data.py`：在 schema 变更后从受保护 raw 日志重建 MESH 派生 SQLite；默认仅输出计划，`--apply` 必须在 NetConsole 完全退出后执行。

## 数据与状态

脚本不得把业务数据写回仓库。迁移或清理清单应写入用户指定路径或系统应用数据目录，正式数据必须先校验再回收源文件。

## 测试

清理测试只在 pytest 临时目录构造目标，禁止对真实 `data/`、`.local/` 或 `%LOCALAPPDATA%\NetConsole` 做破坏性测试。

## 修改规则

新增可写动作时必须补充白名单、路径逃逸/链接拒绝、dry-run 与 apply 测试，并同步数据布局或构建发布文档。

## 生成与清理

本目录源码需要长期保留；`__pycache__` 等运行缓存可安全回收且不得提交。

## 相关文档

- `docs/DATA_LAYOUT.md`
- `docs/BUILD_AND_RELEASE.md`
- `docs/development/repository-layout.md`
