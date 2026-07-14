# Qt WebHost

## 当前状态

阶段 5C-0 在普通 Qt 主程序中增加可复用 WebHost。它复用既有 FastAPI、Vue、Task Center、Agent Controller、Traffic Service、Online MR Query/Application Service，不建立第二套 Python Core，也不通过 QWebChannel 暴露业务方法。

主程序托盘和 Fluent 顶部“更多”菜单均可打开完整 Web 控制台。WebHost 按需启动，因此仅运行原生 Qt 页面时不会监听 HTTP 端口，也不会要求 FastAPI 服务提前启动。

## 运行结构

```text
Qt Main Window / System Tray
        |
        v
WebConsoleHost
        |
        +-- QWebEngineView（可用时）
        |
        +-- 系统默认浏览器（fallback）
        |
        v
127.0.0.1 随机端口
        |
        v
Existing FastAPI + Vue + Python Core
```

本地服务只绑定 `127.0.0.1`。桌面 WebHost 每次进程启动生成新的临时会话令牌；令牌通过 `POST /__desktop_session` 建立 HttpOnly、SameSite Cookie，不进入 URL。HTTP 和 WebSocket 在会话建立前均拒绝访问。

外部浏览器 fallback 会在 `runtime/cache/` 创建临时自提交页面，令牌只存在于 POST 表单正文，文件在 60 秒后或主程序退出时删除。该令牌只保护主程序本地 WebHost，不替代 Agent 的 `X-Agent-Token`，也不会写入任务、数据库或业务日志。

## 生命周期

- 第一次打开 Web 控制台时才创建 FastAPI 服务并启动 Uvicorn 线程；
- 关闭 Web 窗口只关闭显示窗口，主程序和本地服务继续存活，可从托盘重新打开；
- 主程序明确退出时先卸载 Web 页面，再停止 Uvicorn；
- QWebEngine 不可用时主程序仍可正常启动，并自动提供外部浏览器入口；
- 普通 `python main.py` 不会在未打开 Web 控制台时监听端口。

## 构建

`scripts/build/build_release.py` 在 Python 打包前执行 `apps/web` 的 `pnpm build`，并把忽略提交的 `apps/web/dist` 作为 `netconsole/assets/web` 内部资源打入 PyInstaller/Nuitka 发布包。构建机需先完成：

```powershell
cd apps/web
pnpm install --frozen-lockfile
cd ../..
```

缺少 pnpm、`node_modules` 或 `dist/index.html` 时，发布构建明确失败，不生成缺少完整 Web 页面的桌面包。

## 当前边界

- 当前 Web 页面包含 Dashboard、只读任务中心、Agent 管理、AC FIT-AP 资源、AC Mesh-Link 在线监控、Traffic、只读 Online MR 实时展示、轨道交通基础资料、在线列车通信检测、Mesh 原始日志分析和轨道交通无线综合看板；任务中心通过 GET-only `/api/job-center` 查询任务快照、结构化事件和 Online MR 映射，不提供 stop、force-stop、delete 或 retry；Mesh-Link 页面可跳转查看其刷新任务；
- 任务列表按运行状态动态使用 2 秒或 5 秒轮询，连续失败后降为 10 秒；详情每 2 秒刷新，日志展开后每秒读取最后 300 条，页面隐藏或关闭后停止全部轮询；
- Job Center 查询以 SQLite `mode=ro` 和 `query_only` 打开当前局点 `tasks.db`，不初始化 schema、不修复状态，也不返回任务结果中的完整业务 payload；
- Online MR 在 `ONLINE_MR_WEB_CONTROL_ENABLED=1` 时提供 LOCAL start 和 normal stop；控制路由额外要求 Desktop 模式、严格 `127.0.0.1` 与已认证短期 Cookie。5B-13A 的 Agent executor 是独立、默认关闭的 Application Service 能力，WebHost 没有 Agent 启停、强停、解析、报告、删除、重试或命令 API；
- Online MR Web 仅读取当前局点的 Session metadata、Task/Mapping、`view/*.json` 和 raw 白名单；页面隐藏或关闭后停止轮询；
- AC 管理通过 GET-only `/api/ac-management` 和 SQLite `mode=ro + query_only` 展示现有 AC/FIT-AP、Radio 1/2、LLDP、光衰及配置快照；不连接设备、不采集、不下发命令，配置文件仅通过受控 snapshot ID 分块读取；
- AC Mesh-Link 查询仍使用 GET-only 接口并按 30 秒 fresh/5 分钟 stale 边界保守展示 MR 状态；唯一 `POST /api/ac-management/mesh-links/refresh` 只接受 AC 标识和 switch-history 布尔开关，通过 Task Center Worker 执行固定只读命令。WebHost 不持有设备凭据、不接受命令文本；旧采集没有 raw 时明确显示不可用；
- 轨道交通基础资料通过 SQLite `mode=ro + query_only` 展示站点/区间派生视图、AP 点位、列车/MR、关联状态和按实体分组的质量问题；导入预览不保存上传原文件。5C-6B 的 apply/审计/rollback API 受 `web.rail_transit_base_data_write`、环境开关、局点范围、预览有效期和数据库哈希共同保护，默认配置不显示应用按钮，真实局点写入仍未授权；
- 在线列车通信检测按列车分开显示 MR-CT/MR-TC，并聚合 Mesh-Link、Online MR、fping/iPerf、Task 和采集包；聚合与 raw tail 保持只读，MR 详情的独立控制区只向 `OnlineMrApplicationService` 提交严格业务 DTO。页面隐藏或卸载只停止轮询，不停止采集；
- Mesh 原始日志分析以 `mode=ro + query_only` 读取既有单来源分析数据库，后端分页链路、降采样 RSSI/空口、复用正式短时/乒乓规则并列出现有报告；不创建 Task、不调用 parser 写入模式、不生成或删除报告，文件访问不接受路径参数；
- 轨道交通无线综合看板通过既有 Query Service 聚合基础设施、列车通信、任务、Agent 缓存和 Mesh 分析摘要；全部接口为 GET-only，告警不增加业务阈值，页面只跳转到已有详情入口；
- WebHost 不开放 Agent 远程 MR start/stop、`executor=AGENT`、远端包删除和 Agent 配置修改；Application Service 的单 Agent 执行闭环见 [Online MR Agent 远程执行器](ONLINE_MR_AGENT_EXECUTOR.md)；
- Agent Web 当前生产认证仍是可选 `X-Agent-Token`。示例配置虽保留 `web_username/web_password` 字段，但尚未实现用户名密码登录流程，不能把 `admin/admin` 描述为已生效认证；
- SNMP Center 和无线勘测继续保持 `DISABLED`。
