# Ground Unattended V2 R3.2 最终集成稳定性验收

日期：2026-11-08。Branch：`codex-A/ground-unattended-v2-20261107`。
基线 HEAD：`7063d85dfe09c3f436c30b19ce8c03a241998062`。

## 结论

本轮结论：**PARTIAL**。没有发现需要新增源码修复的集成缺陷；已有 R3/R3.1/R3.1.1 实现及此前回归证据仍适用。本轮重新执行了 Ground 定向、Renderer 定向与全量、Electron 全量测试，并完成 3600 秒隔离 Electron/Backend/fping/UDP 连续负载。负载阶段按时长跑满且数据完整性检查通过，但 harness 在最后 Electron 优雅退出时触发 30 秒超时并将运行标记为 `FAILED`；其后已清理所有自有进程。AP/站点切换与丢包快照未纳入长稳 harness，完整的页面交互和三尺寸布局人工检查仍有覆盖缺口，因此不能标记最终 PASS。

没有切换分支、提交、推送、合并或发布。没有访问真实设备、`D:\NetConsoleData` 或 `D:\NetConsoleData-dev`。原始 R3 增量及既有 dirty 修改均保留。

## 工作区与基线

开始时分支及 HEAD 与任务指定一致；`git status` 有 29 个 tracked 修改和 18 个 untracked 文件，主要为 R3 心跳、库存、API、调度与测试增量。开始快照和校验文件位于 Workspace 的 `reports/tests/ground-r3.2-final-20261108/initial-git-status.txt`、`initial-diff.patch`、`initial-diff-stat.txt`、`initial-diff.sha256.txt`。初始 tracked diff 为 29 个文件、1241 insertions / 135 deletions。该差异作为基线保留；本轮没有编辑这些源码或测试文件。

唯一新增仓库文件是本报告。执行 `scripts.check_workspace_layout` 与 `git diff --check` 均通过（仅 Git LF/CRLF 提示）。本轮结束后仍须以最终 Git 状态复核报告新增不影响原有 dirty 修改。

本轮 Electron 心跳页实际运行截图位于 `D:\study\NetConsole-Workspace\reports\tests\ground-r3.2-final-20261108\`：

- 1920×1080：`heartbeat-main-1920.png`
- 2048×1091：`heartbeat-main-2048.png`
- 1672×941：`heartbeat-main-1672.png`
- 详情抽屉：`heartbeat-detail-drawer.png`
- 同轮 Electron 其他页面运行截图：`electron-1920.png`、`electron-2048.png`、`electron-1672.png`

以上截图来自隔离 Electron 窗口，不是静态 HTML。已核验文件像素尺寸分别为 1920×1080、2048×1091、1672×941，并保留了详情抽屉截图。它们证明页面已在三尺寸渲染；截图本身不能证明所有交互均验收通过。

R3.1.1 实际 Electron 截图位于 Workspace `reports/tests/ground-r311-20261108/`：

- 修改前：`before-1920.png`、`before-2048.png`、`before-1672.png`
- 修改后：`after-1920.png`、`after-2048.png`、`after-1672.png`

这些截图来自真实 Electron 窗口，是 R3.1.1 验收证据，本轮未将其冒充为 R3.2 截图。R3.1.1 报告记录四列布局、整车状态去重、详情入口和三种分辨率检查结果。R3.2 已另行保存本轮心跳页面与详情抽屉截图；但长稳压力 harness 只确认 Renderer 就绪，没有在压力运行中覆盖导航、暂停/恢复及重启恢复交互。

## 自动化回归

证据根：`D:\study\NetConsole-Workspace\reports\tests\ground-r3.2-final-20261108\`。

| 范围 | 本轮结果 | 证据 / 说明 |
| --- | --- | --- |
| Ground 定向 | **150 passed, 1 warning** | `python-ground-targeted.log`；FastAPI/Starlette httpx 弃用警告 |
| Ground 核心集复跑 | **98 passed, 1 warning** | `python-ground-r3.2-rerun.log`；覆盖 API、库存、状态、保留、丢包追踪和 Syslog |
| Ground 全模块复跑 | **395 passed, 1 skipped, 1 warning** | `python-ground-full-r3.2.log`；全部 `test_ground_unattended*.py`，跳过项为显式 opt-in 的 500k scale gate |
| Renderer 定向 | **4 files / 70 passed** | `renderer-ground-targeted.log` |
| Heartbeat/车辆 Renderer 复跑 | **2 files / 52 passed** | `renderer-ground-r3.2-rerun.log` |
| Renderer 全量 | **198 files / 1398 passed** | 本轮全量运行通过；复跑日志 `reports/tests/ground-r3.2-final-20261108/renderer-full-r3.2-rerun.log`。测试过程中有既有回环 `localhost:3000` ECONNREFUSED 输出，未影响 Vitest 结果或退出码 |
| Electron 全量 | **38 files / 306 passed** | 本轮全量运行通过；运行输出未单独落盘为 R3.2 日志 |
| Electron 全量复跑 | **38 files / 306 passed** | `electron-full-r3.2-rerun.log` |
| Renderer 类型检查与构建 | PASS | 接力上下文记录已完成；本轮未重复执行 |
| Renderer 类型检查与生产构建复跑 | PASS | `renderer-build-r3.2.log`；有 Vite 大 chunk 提示，不影响构建成功 |
| Ruff / `py_compile` | PASS | `ruff-ground.log` 为空错误输出；`py_compile` 结果来自接力上下文，本轮未重复执行 |
| Ruff / `py_compile` 复跑 | PASS | `ruff-r3.2-rerun.log`、`py_compile-r3.2.log` |
| Workspace layout / diff 检查 | PASS | `scripts.check_workspace_layout` PASS；最终 `git diff --check` PASS |
| R3.1.1 Ground 聚合及生命周期回归 | **398 passed, 1 skipped** | 前轮 `reports/tests/ground-r3.1-final-20261108/ground-after-loss-restore-final.log`；作为既有证据引用，不计作本轮重跑 |

Ground 全模块复跑及核心集复跑是当前工作树上的自动化回归；R3.1.1 的 Electron 生命周期交互、清空边界、AP/站点和丢包快照实际运行证据仍作为前轮集成证据引用，本轮没有重复执行这些真实 Electron 交互场景。相关覆盖说明见 `docs/archive/ground-unattended-v2-r3.1-final-integration-audit.md`。

## 隔离 Electron 连续运行

正式 3600 秒证据根：`D:\study\NetConsole-Workspace\test-data\NetConsole\ground-r3.2-final-20261108-3600\`。
日志：`reports/tests/ground-r3.2-final-20261108/electron-ground-r3.2-3600.log`；逐次运行指标：`test-data/NetConsole/ground-r3.2-final-20261108-3600/metrics.ndjson`。
Harness 使用真实 Electron Renderer/Main、Python Backend、随包 fping、本机 UDP loopback 和隔离 SQLite；没有 SSH/AC 连接。另有 600 秒成功短跑证据根 `test-data/NetConsole/ground-r3.2-final-20261108-retry1/` 和日志 `electron-ground-r3.2-retry1.log`，作为独立预跑保留。

- Fixture：60 辆车、120 MR、200 个 loopback Ping 地址（80 个双地址 MR、40 个单地址 MR）；同步结果为 60 完整 CT/CW 配对、120 个新增端点。该规模超过任务要求的 21 辆车/42 MR。
- Electron Renderer 到达 `ready=complete`；Backend 在隔离测试模式就绪。
- 连续负载：`3600.0003` 秒（达到请求的 3600 秒）。最后一个运行采样时 200 个 Ping 目标正常、120/120 MR 在线、整车 60/60 双端在线；逐点记录见 `metrics.ndjson`。
- Quick Ping：8 个 loopback 目标，停止状态 `CANCELLED`（harness 正常收尾）。
- UDP：最后采样计数接收/写入/数据库保存均为 `358160`，harness 发送 `359020`；`dropped=0`、收尾前队列为 0。发送计数和服务端收到数不完全一致，不能声称每个 UDP datagram 都已送达；接收记录均已写入。
- 资源观测：最后采样的 UDP/Parser 队列为 0、database pending 为 20；Python Backend 峰值 RSS 约 278,622,208 bytes。没有项目既定性能阈值，不据此宣称性能预算通过。
- 停止后：Ping 目标数为 0、UDP listener 为 false；7 个 SQLite 文件全部 `integrity_check=ok`；GZIP 文件校验均为 CRC PASS 且 SHA256 已记录。自有进程最终清理列表为空。
- 收尾限制：Electron graceful exit 在 30 秒内未完成，`electron_graceful_exit_timeout=true`，harness 最终状态为 `FAILED`。进程树随后被 harness 对已验证的自有进程清理，故长稳负载完成，但完整长稳门禁不通过。日志仅有 RUNNING/FAILED 状态行；详细收尾证据见运行根 `summary.json`。

日志与明细：`summary.json`、`metrics.ndjson`、隔离 `devices.db`、`index.sqlite` 和相关 Raw/压缩文件均在该运行根。

## 未覆盖项与风险

- **长稳负载跑满，但 harness 最终失败**：3600 秒负载循环达到时长；失败点是 Electron 优雅退出 30 秒超时。资源最终被清理、SQLite/GZIP 校验通过，但退出超时仍属未解决的生命周期风险。
- **压力场景不完整**：Harness 没有在运行中切换 AP/站点，也没有验证丢包事件发生时的 AP/站点不可变快照。Syslog UDP 行最终归类到 `_unidentified`；不能将其当作完成业务身份解析或真实站点链路验证。
- **Electron 视觉/交互验收部分完成**：本轮保存并核验了心跳页面三尺寸截图及详情抽屉截图，见上述证据路径；没有完成所有详情、刷新、暂停、恢复、停止和重启恢复的人工交互验收。R3.1.1 的生命周期截图另作为前轮证据保留。
- **实时生命周期交互未全量重演**：当前工作树的 Ground 全模块自动化 395 passed、1 skipped；Electron/Renderer 自动化亦通过。AP/站点切换和丢包快照有 R3.1.1 隔离 Electron 证据，但本轮没有在新的 3600 秒长稳运行期间重复该场景。
- 最初曾使用系统 Python 启动验收脚本，因无法导入 `netconsole` 失败；失败日志 `electron-ground-r3.2.log` 和失败隔离根均保留。随后切换仓库 `.venv` 重跑并成功，失败记录未覆盖。

## 数据影响与最终状态

仅创建并写入 Workspace 下的隔离测试根与测试/验收证据。没有修改真实业务数据或真实设备，没有创建真实 AP/站点关联。首次运行失败根和失败日志保留供审计，未清理未确认文件。

最终核验时分支仍为 `codex-A/ground-unattended-v2-20261107`，HEAD 为 `7063d85d`。原有 29 个 tracked 修改与 18 个 untracked 文件仍在；本轮只新增本报告，没有编辑已有源码或测试。隔离测试和截图写入 Workspace 的 `reports/tests`、`test-data`。发现一组 05:00 启动的日常开发 Electron/Backend 进程使用 `D:\NetConsoleData-dev`，不是本轮隔离验收进程；为遵守真实数据边界，未与其交互或关闭。压力 harness 的自有进程清理记录见运行根 `summary.json`。本轮没有 commit/push/merge/release。最终状态维持 **PARTIAL**：长稳 harness graceful exit 超时仍未解决，完整实时生命周期交互也未在本轮重演。
