# 测试基线

NetConsole 测试按风险等级、共享契约和消费者选择，不按历史 Bug 数量增长。详细风险与 Consumer Matrix 见 [Change Impact Framework](../development/CHANGE_IMPACT_FRAMEWORK.md)。测试资产只有在生产入口、消费者、CI、共享 fixture 与独有断言均确认被替代后才能删除。

## 永久原则

- 测试描述当前仍存在的产品、长期业务契约和必要旧数据兼容，不永久保存已退役实现细节。
- 修改共享契约时验证消费者；修改行数和目标页面不能替代风险判断。
- 开发分支先跑定向测试，L3/L4 在最终合并 commit 上重新验证。
- 自动化证据、Electron GUI、真实设备、正式安装包和长时运行分别报告，不能互相替代。
- 默认 PR 离线运行，不连接真实设备、不要求 Windows GUI、不读取正式数据根。
- 本地 `scripts.quality.local_gate` 是主要开发验证入口；GitHub Actions 只提供可选远端复核。

## 测试层级

| 层级 | 职责 | 典型内容 |
| --- | --- | --- |
| Unit | 单一函数、Parser、Domain/Service、Repository 边界 | 归一化、状态机、映射、SQL 查询、展示模型 |
| Integration | 多层真实组合但使用隔离数据/Fake 外部系统 | Application Service + Repository、FastAPI Router、Worker 协议 |
| Contract | 稳定跨模块或跨进程协议 | API DTO、Task/Job、Export、Feature、AP Identity、IPC/Preload |
| Smoke | 证明关键入口可启动和最小 happy path 可用 | Desktop、Site、Devices、AC、Rail、Task、Export、Settings |
| Manual/Device | 自动环境不能可靠证明的行为 | 真实 H3C、Windows GUI、安装/升级、托盘、长时网络 |

测试目录可以逐步收敛为 `unit/`、`integration/`、`contract/`、`smoke/`，但不得为了目录美观一次移动所有活跃测试。历史平铺文件只有在 owner 和消费者契约明确后才移动或合并。

## 风险与验证层

### FAST

L1/L2 开发阶段最低执行：

1. 修改 Service/Repository/Parser/Router 的直接 pytest。
2. 修改页面/API/Store 的定向 Vitest。
3. Electron 代码的定向 test/typecheck。
4. 修改范围 Ruff、适用 Guard 和 `git diff --check`。

### CONSUMER

L3 必须先运行 Change Impact：

```powershell
.\.venv\Scripts\python.exe -m scripts.quality.check_change_impact --base-sha <base> --head-sha <head>
```

随后执行 Registry 输出的 consumer suites。不能只跑当前目标模块，也不应无差别连接现场设备或执行安装包人工验收。

推荐直接使用统一入口：

```powershell
.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode consumer
```

### FULL

L4、release 和新 main baseline 执行完整受支持组合：

1. 完整 pytest。
2. 完整 Renderer test/typecheck/build。
3. 完整 Electron test/typecheck/build。
4. Ruff、架构门、文档/路径检查。
5. Agent 受影响时执行 Go test/build check。
6. Packaging 受影响时执行对应 package contract/smoke。

统一入口：

```powershell
.\.venv\Scripts\python.exe -m scripts.quality.local_gate --mode full
```

## 数据隔离

- 自动测试必须显式使用 `RuntimeMode.TEST` 和唯一 `D:/study/NetConsole-Workspace/test-data/NetConsole/<run-id>`。
- pytest 在收集测试模块前建立隔离根；缺少显式测试根必须失败关闭。
- 禁止读取或写入 `D:/NetConsoleData`、机器级 DataRoot 指针、正式局点数据库、真实会话和报告。
- PyInstaller Backend、release contract 和 Electron Package Smoke 必须自行建立并清理唯一测试根，不复用系统 Temp 或构建机业务数据。
- 特定布局使用 `tmp_path`、fixture 或 Fake 服务；不依赖本机 Task、Session、设备数量或已安装工具。
- 独立 worktree 启动 Python 子进程时，若 `.venv` 未 editable install，显式设置 `PYTHONPATH=src`；不能把包路径错误误判为 Worker 业务失败。

## pytest Marker

以下 marker 用于逐步整理执行边界，不要求为减少文件数机械重写全部测试：

| Marker | 含义 | 默认 PR |
| --- | --- | --- |
| `unit` | 纯单元、无外部 IO | 运行 |
| `integration` | 隔离数据或本机进程组合 | 按受支持基线运行 |
| `slow` | 明显延长反馈的稳定自动测试 | Full/显式运行 |
| `network` | 需要本机网络栈或受控回环服务 | 显式运行 |
| `device` | 需要真实/仿真网络设备 | 不运行 |
| `windows` | 依赖 Windows 平台能力 | Windows gate/显式运行 |
| `packaging` | 依赖冻结或安装制品 | release/package gate |

不得给普通测试随意加 marker 来逃避 CI。新增 marker 时同步 `pytest.ini`、CI 和测试文档。

## Python

优先使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m pytest <target> -q
.\.venv\Scripts\python.exe -m ruff check <changed-python-paths>
```

收集门：

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
```

收集通过只证明 import/fixture 可建立，不等于测试执行通过。

## Desktop Renderer

在 `apps/desktop_renderer` 运行 package scripts：

```powershell
pnpm test
pnpm build
```

开发中可先定向运行 Vitest；受影响切片完成后执行 build。`apps/desktop_renderer` 是 Electron 唯一正式 Renderer，不能把当前 Vue/API/Store/FeatureGate 测试当作“旧 Web 测试”删除。Browser 只保留开发诊断所需最小 contract，不维护第二套产品级回归。

## Electron

在 `apps/desktop_electron` 运行：

```powershell
pnpm test
pnpm run typecheck
pnpm run build:main
```

触及 Main/Preload/IPC/Backend lifecycle 时必须验证 Electron 与 Renderer 两端；触及启动链时按现有脚本运行 `smoke:dev`，触及工作区/托盘时运行 `smoke:workspace-tray`，触及正式制品时运行 `smoke:package`。这些 smoke 不能替代真实安装、签名、升级和 Windows 交互验收。

## Agent

修改 `apps/agent` 时运行受影响包的 Go tests；API、fping/iPerf、MR sidecar、配置/targets、任务事件和采集包按 `netconsole-agent-skill` 选择定向验证。真实远端 Agent、长时流量和多 Controller 不进入默认 PR。

## 主线 Smoke

主线至少持续验证以下入口契约：

```text
Desktop startup -> Site/DataRoot -> Devices -> AC/FIT-AP
-> Rail Base -> Trackside AP -> MESH -> Online MR -> Ground
-> Task Center -> Export -> System Settings
```

每个入口只保留一个稳定 happy-path/contract，具体当前证据见 Change Impact Framework。Smoke 用于发现模块整体失效，不替代领域边界、异常和数据安全测试。

## PR 与合并后验证

- Pull Request 可运行 Change Impact Audit、快速质量门和当前完整自动基线；本地 Gate 是主要开发事实源，GitHub Actions 作为可选远端复核。
- `python-full-regression.yml` 继续在 PR、`main` push、手动和定时任务运行完整 pytest。
- L3/L4 的分支结果在合并后失效；最终 `main` commit 必须重新运行 Registry 指定 consumer suites。
- L4 还必须执行完整支持基线和适用 platform/package gate，并记录 GUI/设备/安装包缺口。
- Workflow 只能提供检查结果，不能替代 Branch protection，也不能把未启动或因额度跳过写成通过。

## 架构门

统一入口：

```powershell
.\.venv\Scripts\python.exe scripts\architecture\run_all.py
```

开发阶段运行直接相关单门，最终 L4 组合运行全部公开门。启发式命中必须人工分类，不得通过目录级忽略、删除测试或无到期例外换取通过。

## 人工与真实设备边界

以下项目始终单独记录为 `PASS/FAIL/PENDING/NOT RUN`：

- 真实 H3C/Comware SSH、SFTP、SNMP、AC/FIT-AP、MR 和长时 fping/iPerf；
- Electron 多窗口、托盘、缩放、主题、通知、任务栏和标题栏交互；
- NSIS 安装/卸载、升级/修复、签名、数据根选择和跨电脑迁移；
- 正式 Full/Customer 制品与现场局点数据；
- 长时间运行、进程残留、网络中断和设备异常恢复。

自动测试通过不能提升 `REAL_DEVICE_PENDING`、`IMPLEMENTED_UNVERIFIED` 或正式包人工状态。

## 测试资产压缩

- 先标记 `KEEP_CORE`、`KEEP_CONSUMER_CONTRACT`、`MERGE_CANDIDATE`、`DELETE_LEGACY`、`DELETE_DUPLICATE`、`DELETE_DEAD`，再实施删除。
- 一次 Bug 一个文件的有效断言并入长期领域/consumer contract；只验证退役实现细节的删除。
- 删除前检查生产 import/call、Router/Service/Renderer/handler、CI/docs/fixture 和重复覆盖。
- 不确定项保留为 `MERGE_CANDIDATE`，不能根据 `web`、`legacy`、`phase` 或 `shadow` 文件名盲删。
- 合并后的文件保持单一职责，不为减少文件数制造超大测试文件。

## 结果报告

每次交付列出实际命令、结果数量、未运行项和剩余风险。L3/L4 额外报告 risk、contracts、consumers、并行修改和合并后复验。未执行的验证只能写 `NOT RUN` 或 `PENDING`，不得引用旧分支结果声称当前 main 通过。
