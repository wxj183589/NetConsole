# Phase 7 Windows 离线包验收

## 范围与构建前审计

本轮目标为当前 v1.5.19 Full NSIS Installer。Canonical 文档明确 Customer/both 入口已退役。正式候选遵守 clean、HEAD 已推送且 upstream 一致的规则，构建期间冻结提交与工作树，最终 Gate 再次核验。

Release Packaging Skill 与 `docs/release/BUILD_AND_RELEASE.md`、`FULL_AND_CUSTOMER_PACKAGING.md`、`PACKAGED_FEATURE_MATRIX.md` 已核对。构建入口采用 `apps/desktop_electron` 中的 `pnpm run package:full`，通过现有 `NETCONSOLE_PYTHON` 指向主仓库项目虚拟环境。工作树无需另建虚拟环境。

本项属于 L4 发布验证，当前未修改打包业务代码。消费者包括 Renderer 构建标识、PyInstaller Backend 入口及服务子进程、Electron Main/Preload/Native Bridge、Full Feature Profile、NSIS 数据根策略、离线客户机依赖、许可证与 SBOM、安装包元数据和 package smoke。源码与 Backend/Frontend/Installer 提交必须一致，自动化包级结果与真实 GUI 安装/升级/卸载分别记录。

本轮并行源码修改由主任务 checkpoint 后统一冻结。产品提交和 DevStatus 由主任务管理。本报告在构建结束后补充实际制品与结果。

## 已执行的定向验证

| 检查 | 结果 |
| --- | --- |
| 构建依赖完整闭包与 constraints | PASS，77 distributions |
| pip check | PASS |
| 项目 Workspace 只读检查 | PASS，REPOSITORY_ONLY |
| installer/edition/artifact inventory/license/SBOM/backend diagnostics | PASS，61 tests |
| 机器可读 Notice | PASS，31 项，assets/docs 副本逐字节一致 |
| 构建前 CycloneDX 1.5 SBOM 生成和独立交叉校验 | PASS |
| Node / Go / pnpm / 完整 7-Zip | 已发现可用工具 |
| 构建盘可用空间 | 413.18 GiB |

Python 定向验证命令如下。

```powershell
python -m pytest -q tests/test_installer_build.py tests/test_prepare_electron_edition.py tests/test_pyinstaller_artifact_inventory.py tests/test_license_sbom.py tests/test_installer_backend_diagnostics.py --basetemp D:/study/NetConsole-Workspace/test-data/NetConsole/phase7-packaging-contracts
```

构建前 SBOM 位于 `D:/study/NetConsole-Workspace/reports/tests/phase7-large-file-20261125/prebuild-sbom.cdx.json`，仅作为依赖审计证据。最终制品使用正常构建生成的包内 SBOM。

## 正式包构建与隔离 smoke

在 clean、已推送 HEAD `a66455b251bf220ca418da01547102c684030246` 上，通过仓库正式 `pnpm run package:full` 构建 Full NSIS。Backend、Frontend、Installer 的包内 commit 均与该 HEAD 一致，`PACKAGED_DIRTY=false`，build identity 为 `v1.5.19+a66455b251bf220ca418da01547102c684030246`。

| 验收 | 结果 |
| --- | --- |
| Full NSIS 构建 | PASS |
| Electron packaged smoke | PASS，冻结 Worker 中文协议、设备数据库迁移/list HTTP 200、无人值守 status HTTP 200、MESH 导入上下文幂等、重复 basename 归档、Qt residue、NOTICE/SBOM/artifact inventory、正常关闭 |
| 独立安装包 verifier | PASS，commit、build identity 与策略哈希匹配 |
| 实际文件路径 | `D:/study/NetConsole-Workspace/worktrees/organization-task-network-services-phase6/dist/electron/NetConsole-Full-1.5.19.0-a66455b2-x64-setup.exe` |
| 文件大小 | 159,505,594 bytes |
| SHA-256 | `048067404813DA700B035558101A361FD96C9B34F5FAB72CDC8D8B21FAC16495` |
| 构建日志 | `D:/study/NetConsole-Workspace/reports/build/phase7-full-installer-a66455b2/package-full-final.log` |

自动化与包级 smoke 结论为 PASS。运行 `python -m scripts.build.build_installer --verify <exe>` 后，`REAL_WINDOWS_INSTALL_STATUS=PENDING`。

## Windows GUI 安装与外部验收

真实干净机器或 VM 的 GUI 安装、升级、卸载和跨电脑验收为 NOT VERIFIED，本环境没有可用的干净 Windows VM 验收实例。自动化仅使用显式 TEST 数据根，没有变更主机全局服务、安装状态、防火墙或数据根指针。

## 数据影响

```text
PRODUCTION_DATA_MODIFIED=0
DEV_REAL_DATA_MODIFIED=0
DATABASES_REMOVED=0
GLOBAL_SERVICES_MODIFIED=0
FIREWALL_MODIFIED=0
```
