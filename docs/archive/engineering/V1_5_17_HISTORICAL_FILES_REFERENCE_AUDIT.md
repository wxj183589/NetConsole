# v1.5.17 Historical Files Reference Audit

日期：2026-11-23

## 审计边界

- 候选分支：`codex-A/release-v1.5.18-20261123`
- 审计基线：`abd6ed8956bdb566c690cbfa4d5855e40d8e5c05`
- 远端候选：`github/codex-A/release-v1.5.18-20261123`，与本地基线一致
- 正式主线：`github/main` = `9e463778f0ece54fb16cb31c877da86ff8bce438`
- 本阶段只读检查两个历史文件；未移动、删除或修改它们，也未修改 Root Layout 白名单。

## 文件事实

| 文件 | Git 状态 | 创建提交 | 字节 / 行 | SHA-256 | Git blob |
| --- | --- | --- | --- | --- | --- |
| `NETCONSOLE_V1_5_17_RELEASE_NOTES.md` | 已跟踪 | `23e82b7d6e0ee2e5b5953a57422c87a416343480` | 1150 / 18 | `9D514DC7DDE9CF426D378516A2335C1146CF4AD782BEAF4A46CC3B3D9B2B297A` | `a9f805cd2b267da22ba88d701b70cac5719c36d1` |
| `V1_5_17_CHANGELOG.md` | 已跟踪 | `23e82b7d6e0ee2e5b5953a57422c87a416343480` | 825 / 19 | `4DB4CAD104D7D9E32ED789FBD7151B05BA3101AEDE21ED83970A385398A7C711` | `2a77f8345a612b5c113cc88673ba7667cbcadf99` |

两个文件均为 UTF-8（无 BOM）、CRLF 行尾。`git log --follow` 和 `git blame` 显示所有内容均来自同一创建提交，之后没有内容修改或路径迁移。创建提交同时新增了 `docs/investigations/netconsole-v1.5.17-code-audit-20261121/` 下的构建、交接、包清单和分支回收报告，因此它们属于同一批 v1.5.17 发布审计资料。

## 内容与用途

- Release Notes 记录 v1.5.17 本地 Full 候选、构建提交、验证边界和 Portable 使用注意事项。
- Changelog 记录 v1.5.17 复审修复、Installer/Portable 文件名及未完成的真实环境验收。
- 两者均声明该版本当时未 Push、未 Tag、未创建 GitHub Release，属于历史候选证据，不是当前产品版本 Authority。
- 当前正式 CHANGELOG 事实源是 `docs/CHANGELOG.md`，运行时同步目标是 `src/netconsole/docs/changelog.md`；版本 Authority 是 `src/netconsole/core/version.py`。这两个根文件不参与上述契约。

## 仓库内引用

以下统计基于审计基线 HEAD，不包含本审计报告和迁移方案自身。每个历史文件各有 4 处文本提及；没有 Markdown 链接、代码调用、路径读取或存在性断言。

| 引用文件 | 行 | 性质 | 迁移影响 |
| --- | ---: | --- | --- |
| `docs/archive/engineering/NETCONSOLE_V1_5_18_GATE_GOVERNANCE.md` | 57-60 | 记录当时 Root Layout 发现和创建提交 | 历史事实，不是消费者；保留原文更准确 |
| `docs/archive/engineering/NETCONSOLE_V1_5_18_RELEASE.md` | 35 | 记录当时 main 根目录阻断 | 历史事实，不是消费者；保留原文更准确 |
| `docs/archive/engineering/FINAL_REPORT.md` | 22 | 记录 Ping 迁移阶段 Root Layout 阻断 | 阶段性历史结论；后续由最终 Gate 报告给出新状态 |
| `docs/archive/engineering/TEST_REPORT.md` | 28 | 记录 Ping 迁移阶段测试结果 | 阶段性历史结论；后续由 Root Layout 验收报告给出新状态 |

`git grep`、大小写不敏感搜索和全仓 `rg` 的结果一致。两个文件没有互相引用，也不包含相对 Markdown 链接，因此内容不变的路径迁移不会破坏文件内部链接。

## 动态路径与发布链审计

已检查 Python、PowerShell、BAT/CMD、Electron Main/Preload/Renderer、JavaScript/TypeScript、YAML/JSON/TOML、GitHub Actions、NSIS、测试和构建脚本中的直接文件名、`glob/rglob`、目录遍历和 Markdown 路径构造。

- `scripts/build/build_config.py`、`scripts/build/sync_runtime_changelog.py` 和 `scripts/build/clean_build_spec.py` 只读取 `docs/CHANGELOG.md`。
- `tests/test_changelog_sync.py`、`tests/test_release_system.py` 和打包 smoke 只验证 canonical/runtime changelog，不读取两个历史根文件。
- `.github/workflows/engineering-hardening.yml`、Electron package 脚本、NSIS 配置和 Windows 发布脚本没有引用这两个文件。
- Root Layout 检查器只按根文件 allowlist 枚举文件；它不要求这两个文件存在，移动后会恢复正常检测。
- 未发现按 `v1.5.17` 名称动态拼接这两个文件路径的代码。

结论：仓库内运行、构建、CI、CHANGELOG 同步和发布流程对两个文件均为 `NO_DEPENDENCY`。

## Workspace 外围检查

- `NetConsole-DevStatus`、`release`、`archives`、`backups`、`diagnostic`：无文件名引用。
- `reports/build/.../local-gate-full.log` 有两份既有日志记录 Root Layout 失败文件名；它们是不可变测试证据，不是消费者，无需修改。
- 未发现受控 Workspace 内的外部工具依赖。仓库和 Workspace 之外的私人书签、脚本或 GitHub branch-path URL 无法由本地审计穷尽；旧提交的永久链接仍可访问，但指向分支根路径的外部链接在迁移后可能失效。

## 风险结论

| 风险 | 等级 | 处置 |
| --- | --- | --- |
| 构建、CI、安装器或 CHANGELOG 同步中断 | 低 | 无执行消费者；迁移后运行相关门禁 |
| 历史内容被改写 | 低 | 使用 `git mv`，迁移前后校验 SHA-256 和 Git blob |
| 历史报告语义失真 | 低 | 不回写当时的 Root Layout 失败记录；新增当前验收报告 |
| 外部 branch-path 链接失效 | 中低 | 最终报告记录旧/新路径和创建提交；永久 commit URL 保持可追溯 |
| 新归档目录触发 README 门禁 | 中 | 若采用新目录方案，必须同时添加目录 README 并运行 Docs Path Guards |

## 审计结论

两个文件可以安全迁移，前提是内容保持不变、使用 Git 原生 rename、迁移后执行哈希和完整发布门禁。当前没有需要同步修改的有效代码或构建引用；4 处仓库内提及均是历史事实记录，不应为制造“零旧名称”而改写。

## 执行补录

用户已于 2026-11-23 明确批准方案 B。两个文件已使用 `git mv` 迁入 `docs/investigations/netconsole-v1.5.17-code-audit-20261121/`；迁移后的 SHA-256、Git blob、字节数和行数均与迁移前一致，Git 识别为两个 rename。Root Layout、Workspace Layout、专项文档/Release 测试和完整 Local Quality Gate 均已通过。

```text
MIGRATION_AUTHORIZED=YES
MIGRATION_COMPLETED=YES
HISTORICAL_FILE_INTEGRITY=PASS
```
