# Git 恢复引用安全审计（2026-07-25）

## 范围与边界

本记录只审计 `main@e8d8091e` 本地仓库中的两个 stash、`wip/b787-architecture-before-5b4a-split` 标签和 `refs/codex/snapshots/*`。审计仅使用路径、对象类型、提交拓扑和 patch-id；未恢复、删除或推送任何引用，也未执行 reflog expire 或 GC。

凭据轮换不属于仓库内可自行完成的操作。本次仅确认敏感字段是否存在非空值，不记录、不输出原值。任何引用清理都必须等待凭据完成轮换、有效代码完成移植并复核其他恢复点。

状态词：

- `敏感-禁止恢复`：含运行凭据，只能在完成轮换后按引用清理流程处置。
- `禁止恢复`：临时说明、运行配置、构建产物或不符合当前目录规范的文件。
- `主线精确存在`：stash blob 与当前映射路径 blob 一致。
- `主题已吸收并演进`：现行路径已有对应功能且后续提交继续修改，不表示 stash patch 逐字等价。
- `尚未合入`：已复现主线缺少该行为，需要手工移植。
- `可删除候选`：拓扑或 patch-id 已证明主线包含，不代表本轮授权删除。
- `保留待审计`：仍有主线无法匹配的 patch，不能删除。

## 2026-07-13 stash

- 对象：`b2a27a5e`，基线 `c807eb8e`。
- 规模：29 个已跟踪路径、17 个未跟踪路径，共 46 个路径。
- 结论：必须保留，禁止整体 `apply` 或 `pop`。其中存在非空凭据，也有主线尚缺的接口归一化行为。

### 敏感与禁止恢复

| 状态 | 路径 | 结论 |
| --- | --- | --- |
| 敏感-禁止恢复 | `agent/config.json` | 存在非空 Agent token 和 Web 登录密码；必须先轮换。 |
| 敏感-禁止恢复 | `agent/targets.json` | 两个目标记录存在非空设备密码；必须先轮换。 |
| 禁止恢复 | `agent/tools/windows-x64/mr_collector/netconsole-mr-collector.exe` | 未跟踪构建产物，当前目录规范禁止恢复到源码树。 |
| 禁止恢复 | `agent/tools/windows-x64/mr_collector/README.md` | 属于已退出的 `agent/tools` 布局，不恢复旧运行时工具来源。 |
| 禁止恢复 | `agent/CHANGES_SIDE_CAR.md`、`agent/CHANGES_SIDE_CAR_V2.md`、`agent/README_ENCODING_FIX_V5.md` | 临时过程说明，当前正式 Agent 文档和提交历史已承载相关事实。 |

### 尚未合入

| 路径 | 证据 | 处置 |
| --- | --- | --- |
| `netconsole/utils/interface_normalize.py` | stash 使用接口类型与编号间的空白压缩；当前 `src/netconsole/utils/interface_normalize.py` 对 `GigabitEthernet 2/0/16` 仍返回带空格形式。 | 只手工移植最小规则，不恢复整个文件。 |
| `tests/test_interface_normalize.py` | 当前主线无该独立测试，stash 用例可稳定复现上述缺陷。 | 在现行 `tests/` 下重写并扩充，不直接导出 stash 补丁。 |

### 主线精确存在

- `agent/go.mod` -> `apps/agent/go.mod`
- `agent/go.sum` -> `apps/agent/go.sum`

### 主题已吸收并演进

以下路径已迁入现行目录并继续演进。Agent sidecar、托盘、防休眠和采集器主题由 `0e2c3828` 接入，目录由 `1e905b94` 收口，后续继续由 Agent、Online MR 和发布提交维护；不得用旧 stash 覆盖当前实现。

- `agent/README.md`
- `agent/cmd/netconsole-agent/main.go`
- `agent/internal/api/server.go`
- `agent/internal/config/config.go`
- `agent/internal/core/task.go`
- `agent/internal/mr/collector.go`
- `agent/internal/mr/collector_test.go`
- `agent/internal/mr/sidecar.go`
- `agent/internal/mr/sidecar_process_other.go`
- `agent/internal/mr/sidecar_process_windows.go`
- `agent/internal/mr/templates.go`
- `agent/internal/packagex/package.go`
- `agent/internal/packagex/package_test.go`
- `agent/internal/power/manager.go`
- `agent/internal/power/power_other.go`
- `agent/internal/power/power_windows.go`
- `agent/internal/toolmanager/manager.go`
- `agent/internal/tray/tray_other.go`
- `agent/internal/tray/tray_windows.go`
- `agent/mr_collector_py/README.md`
- `agent/mr_collector_py/build_windows.bat`
- `agent/mr_collector_py/collector_cli.py`
- `agent/scripts/build_windows.bat`
- `agent/web/app.js`
- `agent/web/index.html`
- `agent/web/style.css`
- `README.md`
- `docs/AGENT.md`
- `docs/BUILD_AND_RELEASE.md`

下列 Python 主题已由后续光衰、轨旁、任务中心和导出提交继续修复，包括 `c143f2b4`、`24222e76`、`24324b02`、`be7aa6a1` 和 `b441d6ff`。现行文件与 stash blob 不同，结论只到“主题已吸收并演进”，如需删除 stash 仍应做最终语义抽查。

- `netconsole/services/ac/ac_optical_service.py`
- `netconsole/services/export/common_exporters.py`
- `netconsole/services/job_center/task_application_service.py`
- `netconsole/services/trackside_ap_business.py`
- `tests/test_ac_management.py`
- `tests/test_task_center.py`

## 2026-06-22 stash

- 对象：`abc0d122`。
- 唯一变更：删除 `netconsole.zip`。
- 主线证据：提交 `1320912b` 对同一路径执行删除，当前主线不再跟踪该构建压缩包。
- 分类：`可删除候选`。本轮不删除；待其他恢复引用审计完成后，可单独删除此 stash。

## WIP 标签

- 标签：`wip/b787-architecture-before-5b4a-split`，提交 `b787ed6b`。
- `git cherry main`：1 个主线无 patch 等价项。
- 涉及架构文档、Job Center adapter 和架构/文档测试，共 15 个路径。
- 分类：`保留待审计`。当前主线架构 Guard 已重建且状态不同，不能仅凭主题相似删除该标签。

## Codex snapshot refs

共 29 个 snapshot refs：9 个是 `main` 祖先，5 个非祖先但全部 patch 等价，15 个仍含主线无法匹配的 patch。patch-id 只能证明文本 patch 等价，不能替代语义评审。

### 可删除候选：main 祖先

- `11aa456a2061e16cfb4aa57035a25720c09c668a`
- `1bc6b58d81d8d3a640fb7f16bebcd78cf169a36a`
- `200ed91aea22bb6ef141f5638f9b127f4cbda301`
- `22138e45d768ef19e3139e496acd30c9288983ca`
- `4546b5306e66a08991b7d7630c5203fd771c6f74`
- `c500be1722fbecfda704e2ee62d3d5734ae16d06`
- `c5726d04cdc20125a565e44b6e9d64885bced45c`
- `c91a164fe7ae0fb3de3c432651022dcf4a5234a8`
- `cbf46fca4e2d056600f93458726d3a3d88da5052`

### 已吸收候选：patch 等价

- `17f3ce684352d6b174731d11c3ebd5c75d948532`
- `2a3662917687ec268e890b563a09c148a4256e60`
- `5c043cdc62ffbe2913cdef2a5780170d5e0829ee`
- `8e7b288348ba779478d439264988e02953ec269c`
- `ee2c969695fff3d6a54b68143bf848e59687680d`

### 保留待审计：存在 unmatched patch

- `0181f3ee385960a92cb03ba4445a2850f6d6df4e`
- `171fe0b9763be1b99f0640d6d4522b2dfde5514a`
- `3cd97b49793f984a1717c25f53610093f1fad044`
- `627087b24f493765cbef7f84ba74eb391f740aba`
- `679c0ee072cdb4f942d0ae7d7ebf5809d1f98216`
- `83d6e220883fb4e5a19d081a8f6054cc8ea816e8`
- `a6a264831d36132d1b633278b2715b9abf29f559`
- `a984794fcb096e8f47b50169fce8877e1543cbd7`
- `bbefed792b7b44b89c8ab47478e91fec7224786c`
- `c313fae25499ad8898faaf07abbe68545bc4b298`
- `c978f013dd0b191318e365a4d43bade39b4cdca4`
- `d4ec1c993bb7f86f0b60c984f234825b2c8ca0c3`
- `dc632cbded8cfbe8edf8f8dc61ff970f17e33b82`
- `dffbc5e47b5df82c59014a27b6e359a089535934`
- `e14fdfa772130fa80449869e5ccfb29dae7778ca`

## 后续安全顺序

1. 在 Agent 和设备侧轮换已识别的 token、Web 登录密码和设备密码，并记录完成事实但不记录旧值。
2. 手工移植并验证接口归一化代码与测试；对其他“主题已吸收并演进”路径做最终语义抽查。
3. 单独复核 WIP 标签和 15 个 unmatched snapshot refs，形成明确保留/删除决定。
4. 先删除确认无用的引用，再单独删除两个 stash；不要把引用删除与代码提交混合。
5. 最后在已确认无需恢复且凭据已轮换的前提下，单独审批 reflog expire 和 GC。执行前后都要记录对象可达性；未实际执行前不得声称凭据对象已清除。
