# v1.5.17 Historical Files Migration Plan

日期：2026-11-23

## 审批状态

用户已明确批准方案 B，迁移已按本计划执行。两个历史文件已进入既有同源调查目录，仓库根目录不再保留重复副本。

```text
MIGRATION_AUTHORIZED=YES
MIGRATION_COMPLETED=YES
ROOT_LAYOUT_GATE=PASS
RELEASE_STATUS=PARTIAL
```

## 路径方案比较

### 方案 A：版本化发布归档目录

目标：`docs/archive/releases/v1.5.17/`

优点：发布记录按版本聚合，长期检索语义清晰，符合仓库规范允许历史证据进入 `docs/archive/` 的原则。

代价：当前不存在 `docs/archive/releases/`。目录 README Guard 会把 `docs/archive/releases` 和 `docs/archive/releases/v1.5.17` 视为新的受维护目录，因此需要同时增加两级 `README.md`，迁移范围从 2 个 rename 扩大为 4 个新增/迁移文件。

### 方案 B：既有同源调查目录

目标：`docs/investigations/netconsole-v1.5.17-code-audit-20261121/`

优点：创建提交 `23e82b7d` 已把同批 v1.5.17 构建报告、最终交接、包清单和分支回收报告放在此处；无需创建新目录或 README，变更范围最小。`docs/investigations` 也是现有文档 Guard 明确保护的历史材料边界。

代价：路径表达的是代码审计批次，而不是统一的版本化 release archive；未来若建立 `docs/archive/releases/`，可能需要二次治理。

## 推荐方案

推荐 **方案 B**：迁移到现有同源目录。理由是原始提交的资料归属最明确、无需新增目录治理文件、Git diff 最小，也不会把一次 Root Layout 修复扩大为新的文档分类建设。

建议目标：

| 文件 | 当前路径 | 建议路径 | 基线引用数 | 执行消费者 |
| --- | --- | --- | ---: | ---: |
| Release Notes | `NETCONSOLE_V1_5_17_RELEASE_NOTES.md` | `docs/investigations/netconsole-v1.5.17-code-audit-20261121/NETCONSOLE_V1_5_17_RELEASE_NOTES.md` | 4 | 0 |
| Changelog | `V1_5_17_CHANGELOG.md` | `docs/investigations/netconsole-v1.5.17-code-audit-20261121/V1_5_17_CHANGELOG.md` | 4 | 0 |

若用户更重视长期版本化目录，可以明确批准方案 A；届时必须把两级 README 纳入同一迁移提交，不能通过放宽目录检查器规避。

## 内容完整性

| 文件 | 迁移前 SHA-256 | 迁移后预期 SHA-256 |
| --- | --- | --- |
| Release Notes | `9D514DC7DDE9CF426D378516A2335C1146CF4AD782BEAF4A46CC3B3D9B2B297A` | 相同 |
| Changelog | `4DB4CAD104D7D9E32ED789FBD7151B05BA3101AEDE21ED83970A385398A7C711` | 相同 |

两个文件没有内部相对链接。计划不修改内容、编码或 CRLF 行尾；`git diff --summary` 应显示 100% rename，Git blob 应保持 `a9f805cd...` 和 `2a77f834...`。

## 批准后的执行步骤

1. Fetch `github/main` 和远端候选分支，确认本地候选 ahead/behind 为 `0/0`，工作树除本阶段两份文档外没有未知修改。
2. 按用户批准的方案，用 `git mv` 迁移两个文件；不复制、不创建软链接、不保留根目录重复副本。
3. 重新计算 SHA-256、Git blob、字节数、行数和换行格式；任何变化都停止并调查。
4. 保留 4 份阶段性报告中的历史事实文字，不把当时的 FAIL 改写成 PASS；在新的 Root Layout/Final Gate 报告中记录当前结果和新路径。
5. 再次运行精确文件名、大小写不敏感和动态路径搜索，确认没有有效消费者仍依赖旧路径。
6. 执行 Root Layout、Docs Path Guards、目录 README、CHANGELOG 同步、release tests 和 `git diff --check`。
7. 只有迁移专项验证通过后才进入用户要求的完整发布 Gate；任一必要 Gate 失败则停止合并和正式打包。

## 迁移专项验收命令

```powershell
git diff --summary
git status --short
Get-FileHash <new-release-notes-path>,<new-changelog-path> -Algorithm SHA256
git hash-object -- <new-release-notes-path> <new-changelog-path>
python -m scripts.quality.check_repository_root_layout
python -m scripts.check_workspace_layout --repo-root . --workspace-root D:\study\NetConsole-Workspace
python -m pytest -q tests/quality/test_repository_root_layout.py tests/quality/test_directory_readmes.py tests/test_project_docs_layout.py tests/test_changelog_sync.py tests/test_release_system.py
python -m scripts.build.sync_runtime_changelog --check
git diff --check
```

实际执行时使用项目可用虚拟环境，并保留完整退出码。若命令参数与当前脚本帮助不一致，以仓库 canonical 文档和 `--help` 为准，不伪造通过。

## 回滚方法

迁移尚未提交时：使用 `git mv` 将两个文件从新路径移回原根路径；若采用方案 A，仅在确认两级 README 由本任务新建且没有其他内容依赖时移除这些 README 和空目录。

迁移已经提交但尚未合并时：创建一个普通回滚提交，将两个文件 `git mv` 回原路径；不使用 reset、checkout、clean 或历史重写。

迁移已经合并时：通过 PR 提交反向 rename，恢复旧路径并重新运行 Root Layout 和完整发布 Gate。由于旧根路径本身违反现行 allowlist，该回滚会重新产生已知 Root Layout 阻断，只用于发现真实消费者或内容完整性异常时的紧急恢复。

## 执行结果

- 采用方案 B；未创建方案 A 的归档目录或 README。
- 两个文件均由 Git 识别为 rename，内容与 SHA-256 不变。
- Root Layout、Workspace Layout、Docs Path Guards、CHANGELOG sync、Release contract 和完整 Local Quality Gate 已通过。
- `RELEASE_STATUS` 在 main 合并、正式包构建和人工安装/启动验收完成前保持 `PARTIAL`。
