# NetConsole 仓库目录规范

## 1. 文档目的

本规则固定 NetConsole 的源码、应用、配置、资源、测试、脚本和生成内容边界，避免新功能再次直接堆到仓库根目录。根目录只保留项目级入口和基础设施；运行数据、缓存、日志、数据库和构建产物与源码分离。

本文件与 `AGENTS.md` 是强制约束；README 只提供简明导航。目录职责不明确时先审计内容、Git 跟踪状态、代码引用、测试引用和构建引用，再决定位置。

## 2. 标准目录树

```text
NetConsole/
├─ .agents/                 # 项目 Skills 和规则，版本化
├─ .codex/                  # 本地 Codex 状态，允许存在但不提交
├─ apps/
│  ├─ agent/                # Windows Go Agent 及其 sidecar/静态页面
│  ├─ desktop/              # Qt Web Shell 宿主
│  └─ web/                  # Vue/TypeScript/Vite 前端
├─ src/
│  └─ netconsole/               # 可安装的共享 Python 包
├─ config/
│  └─ profiles/             # 版本化 feature profile 和配置模板
├─ docs/                    # 项目文档、架构和开发规则
├─ resources/               # 版本化只读资源、命令参考和 MIB 归档
├─ scripts/
│  ├─ build/                # 构建、打包、构建检查和发布脚本
│  ├─ dev/                  # 本地开发、基准和手工 smoke 脚本
│  └─ maintenance/          # 仓库维护、离线迁移和审计脚本
├─ tests/                   # 自动化测试和脱敏 fixtures
├─ tools/                   # 独立开发、诊断、维护和协议分析工具
├─ main.py                  # 轻量兼容入口
├─ pyproject.toml           # src 包发现和 editable 安装配置
├─ pytest.ini               # pytest 入口配置
├─ requirements.txt         # Python 运行依赖
├─ AGENTS.md
├─ README.md
└─ LICENSE
```

## 3. 顶层目录白名单

版本化顶层目录为：`.agents`、`apps`、`src`、`config`、`docs`、`resources`、`scripts`、`tests`、`tools`。`.codex`、`.venv`、`.local`、`.idea`、`.vs`、`.pytest_cache`、`.ruff_cache` 允许在本机存在，但必须被 `.gitignore` 忽略；`.git` 属于 Git 管理目录，不是业务目录。

`.agents/` 是已纳入 Git 的项目级 Skill 和规则目录；`.codex/` 只是本地 Codex 状态目录，不得误认为项目配置或版本化 Skill 来源。

允许的顶层文件仅包括项目级配置、说明、许可证、依赖清单、统一入口和 CI/Git 配置。新增顶层目录必须同时满足：

- 属于项目级基础设施，且无法合理归入现有目录；
- 只有一个清晰、唯一、长期稳定的职责；
- 在代码评审中说明原因；
- 同步更新本文件和必要的 README/AGENTS 说明。

## 4. 应用边界

- `apps/agent` 只放独立 Windows Go Agent、Python MR sidecar、Agent Web 静态文件、示例配置和 Agent 构建脚本；Agent 运行数据默认写入 `%LOCALAPPDATA%\NetConsole\Agent`，开发态可使用 `.local/agent/`。
- `apps/desktop` 只放 Qt Web Shell 宿主，不复制 Python Core 或业务服务。
- `apps/web` 只放 Vue/TypeScript/Vite 源码、前端配置和锁文件；`node_modules`、前端 `dist` 和 TypeScript 缓存不得提交。
- `src/netconsole` 放共享 Python 业务代码、模型、Repository、Service、Parser、UI 和包内静态资源；包名仍为 `netconsole`。
- 任何应用不得把数据库、日志、抓包、采集结果、缓存或正式报告写入源码目录。

### Agent 二级目录

`apps/agent/` 只保留源码和可审查模板：

```text
apps/agent/
├─ cmd/                         # Go 入口
├─ internal/                    # Agent 内部包
├─ mr_collector_py/             # Python MR sidecar 源码
├─ web/                         # 内嵌 Web 静态文件
├─ scripts/                     # Agent 构建、启动和运行维护脚本
├─ resources/config/            # config.example.json、targets.example.json
├─ go.mod、go.sum、README.md
└─ testdata/                    # 需要时放脱敏测试样本，不放运行数据
```

`bin/`、`data/`、`dist/`、`logs/`、`packages/`、`tmp/`、`apps/agent/tools/` 不得作为 Agent 源码子目录保留。Agent 开发运行数据使用 `.local/agent/{data,logs,tmp,runtime,packages}`，打包态使用 `%LOCALAPPDATA%\NetConsole\Agent\{data,logs,packages}`；构建产物统一写入 `dist/agent/`。运行时第三方工具的唯一源码来源是根 `resources/tools/`，Agent 交付包内才生成 `tools/windows-x64/{fping,iperf3}`，不在 `apps/agent/resources/tools/` 或 `apps/agent/tools/` 复制第二份。

## 5. 配置和资源规则

- `config` 放可审查、可版本化的配置模板和 feature profiles，不放真实账号、密码、Token、community、私钥或生产局点数据。
- `resources` 放随代码发布的只读资源、规则、命令参考和明确版本化的 MIB 归档；不得把用户导入的 MIB、编译索引或报告写回此目录。
- 所有文档中的源码文件路径使用 `src/netconsole/...`；Python import、模块或包名仍使用 `netconsole.*`，不得把 import 写成 `src.netconsole.*`。
- `resources/tools/` 是 fping/iPerf 运行工具的唯一源码来源；`tools/` 只用于开发、诊断、维护和协议分析。`tools/windows-x64/ipop/` 只保存 IPOP 外部工具说明，`IPOP.EXE` 不提交、不打包。
- `apps/agent/resources/config/` 只放 `config.example.json`、`targets.example.json` 等模板；真实 `config.json`、`targets.json` 放在 `.local/agent/` 或 `%LOCALAPPDATA%\NetConsole\Agent\`。Agent 启动脚本可在首次运行时从模板初始化缺失文件，但不得覆盖已有真实配置。
- `src/netconsole/assets`、`src/netconsole/resources` 是包内资源，必须通过资源 helper 定位并在打包配置中显式处理。
- 真实敏感配置只能由用户在本机应用数据目录配置，提交前必须脱敏。

## 6. 运行数据规则

开发态默认数据根为 `.local/`，通过 `PathResolver` 生成实际子目录：

- `.local/data`：SQLite、局点数据、原始采集、解析库和正式业务文件；
- `.local/runtime/logs`：应用日志；
- `.local/runtime/cache`：Job、Export 和查询缓存；
- `.local/tmp`：手工临时样本和一次性导出；
- 打包态优先使用 `%LOCALAPPDATA%\NetConsole\`，不依赖安装目录或当前工作目录。

正式报告写入用户选择的导出路径或业务 `outputs` 目录。原始日志、数据库、会话、备份和正式报告不得静默删除。现有根目录 `data`、`runtime`、`tmp`、`release` 内容本次只移动到 `.local`/`dist`，未删除。

## 7. 测试目录规则

- 单元测试和集成测试放在 `tests/`，测试样本放在 `tests/fixtures/`；不得把测试样本放入生产 `resources`。
- 大体积日志样本必须脱敏，不能包含真实密码、Token、community、私钥或生产敏感地址。
- 测试不得依赖开发者机器绝对路径；使用 `tmp_path`、显式 `PathResolver` 或项目根定位。
- 测试生成的数据库、日志、报告、缓存和临时文件必须位于 pytest 临时目录或 `.local`，不能写回源码树。

## 8. 脚本目录规则

- `scripts/build`：PyInstaller/Nuitka、版本发布、清理构建 spec、依赖检查和构建批处理。
- `scripts/dev`：基准测试、本地工具 smoke 和开发辅助操作。
- `scripts/maintenance`：命令审计、离线数据库升级和仓库维护。

脚本必须根据自身位置或统一项目根定位源码、资源和输出，不能默认依赖调用者的当前工作目录。Python 脚本应通过 `python -m scripts.<group>.<module>` 运行；不使用临时 `sys.path` 注入修复包结构。

## 9. 构建产物规则

`build/`、`dist/`、旧 `release/`、PyInstaller/Nuitka 临时目录、`*.spec`、安装包、ZIP、前端构建产物、Python/Go 缓存和本地 Agent 运行目录均不得提交。`resources/builtin_mibs` 中明确版本化的 MIB ZIP，以及 `resources/tools/windows-x64/{fping,iperf3}` 中已记录来源与许可证的运行依赖是已审计例外；构建后才复制为交付包内的 `tools/windows-x64/{fping,iperf3}`。根 `tools/` 只用于开发、诊断、维护和协议分析，`apps/agent/tools/` 禁止作为运行时工具来源；IPOP 始终不进入发布包。

## 10. 新增文件检查表

新增文件前逐项确认：

- 它是源码、应用、资源、配置、测试、工具还是生成文件？
- 是否已有唯一对应目录？
- 是否会污染根目录或把运行数据混入源码？
- 是否需要加入 `.gitignore`？
- 是否包含敏感信息或未经授权的第三方内容？
- 是否影响 Python 包发现、打包、前端工作目录、Agent 入口或资源路径？
- 是否需要补充测试和文档链接？
- 是否改变顶层职责，需要同步更新本规则？
- 文档中引用的相对链接、源码路径和交付包路径是否分别存在且语义正确？

## 11. 禁止事项

- 在根目录增加普通业务模块；
- 创建 `misc`、`temp`、`new`、`project` 等模糊目录；
- 将日志、数据库、抓包、采集结果、缓存或安装包提交到 Git；
- 使用当前工作目录定位源码、资源、配置或运行数据；
- 通过任意修改 `sys.path` 掩盖 src 包结构问题；
- 将测试样本放在生产资源目录；
- 将第三方二进制与无关源码混放；
- 将构建产物或未审计的发布压缩包提交到仓库；
- 未审计用途就删除或覆盖本机数据、原始日志、数据库、会话和正式报告。

## 12. 当前目录迁移映射

| 迁移前 | 迁移后 | 说明 |
| --- | --- | --- |
| `agent/` | `apps/agent/` | 独立 Go Agent |
| `desktop/` | `apps/desktop/` | Qt Web Shell |
| `frontend/` | `apps/web/` | Vue Web 前端 |
| `netconsole/` | `src/netconsole/` | 共享 Python 包，导入名仍是 `netconsole` |
| `profiles/` | `config/profiles/` | Feature profile 配置 |
| `project/build_*.py` | `scripts/build/` | 构建脚本 |
| `project/release.py` | `scripts/build/release.py` | 发布辅助脚本 |
| 根 `build_*.bat` | `scripts/build/` | Windows 构建入口 |
| 根 `clean_build_spec.py` | `scripts/build/clean_build_spec.py` | PyInstaller 构建检查 |
| 根 `data/` | `.local/data/` | 本机数据，保留内容不提交 |
| 根 `runtime/` | `.local/runtime/` | 本机运行状态，保留内容不提交 |
| 根 `tmp/` | `.local/tmp/` | 本机临时数据，保留内容不提交 |
| 根 `release/` | `dist/` | 构建产物，忽略且不提交 |
