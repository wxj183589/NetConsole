# 回归测试记录

日期：2026-11-08；Branch：`codex-A/mesh-analysis-performance-optimization`。
所有自动化和基准使用 Workspace 隔离 fixture，没有访问 Production 或长期真实开发数据。

## 专项自动化

|检查|实际结果|
|---|---|
|Python Mesh business/report/query/web/contract 五文件|PASS：192 passed，3条第三方 deprecation warning，66.50s|
|Renderer policy/summary/view behavior/view/API 五文件|PASS：90 passed，0 failed/skip|
|Web parity export API 契约|PASS：7 passed；默认business、显式diagnostic及任务参数覆盖|
|全部 Mesh 领域 Python（`-k mesh`，修复后）|PASS：513 passed / 5052 deselected，175.55s|
|导出身份/Worker 原有契约（修复后）|PASS：14 passed，1.56s|
|Feature/Profile/Edition 消费者（修复后）|PASS：74 passed，3.67s；两份Profile显式登记新能力|
|架构与存储登记（修复后）|PASS：23 passed，71.50s；精确登记四个SQL来源和两个存储消费者|
|Mesh Chromium组件矩阵|PASS：24 cases；四档数据×full/自动策略×三个视口|
|Renderer完整测试（修正导出契约断言后）|PASS：200 files / 1409 tests|
|Renderer typecheck / Vite build|PASS；build保留既有大chunk warning|
|Electron完整测试 / typecheck / build:main|PASS：38 files / 306 tests；类型与构建通过|
|完整Ruff、文档Guard（修复后）|PASS；文档22 passed，固定报告路径精确例外|
|修改范围Ruff、Workspace layout、diff check|PASS|

Python复现：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_mesh_business_statistics.py tests/test_mesh_analysis_report.py tests/test_mesh_analysis_query_service.py tests/test_mesh_analysis_web_api.py tests/test_mesh_web_contract.py -q --tb=short
```

Renderer定向在`apps/desktop_renderer`：

```powershell
pnpm exec vitest run src/components/mesh-analysis/meshLoadingPolicy.test.ts src/components/mesh-analysis/MeshBusinessSummary.test.ts src/views/rail-transit/MeshAnalysisView.behavior.test.ts src/views/rail-transit/MeshAnalysisView.test.ts src/api/meshAnalysis.test.ts
pnpm exec playwright test tests/visual/e2e/mesh-business.visual.spec.ts --project="1920x1080@100%" --project="2560x1440@100%" --project="1920x1080@125%" --workers=1 --reporter=json
```

浏览器真实渲染当前Summary、共享表格及ECharts，业务API使用mock、曲线使用四档真实查询DTO。断言点击前无明细请求、点击触发RECOGNIZED分页、无横向页面溢出、无pageerror及深色样式。已人工查看三个视口中的摘要/弹窗截图；表格横向滚动保留完整字段。夹具补齐基础CSS及dark主题后重跑24例，早期缺样式结果不用于交付。deviceScaleFactor=1.25不是Windows原生DPI。

共享图表仍有既有 ECharts console.error：`Component title is used but not imported`（共享 option 携带 title）；没有 pageerror。本专项未修改共享图表实现，不能声称浏览器 console 完全无错误。

## 覆盖矩阵

|领域|证据与边界|
|---|---|
|原算法一致|四档Parser/完整quality digest前后一致（仅排除报告生成时间）；定向非零切换、NO_BACKUP/乒乓、多Radio保持原语义|
|物理AP身份|同物理多Radio、重复出现、同名不同设备、无物理MAC、Alias/历史投影冲突、未识别Peer独立证据|
|RSSI|仅唯一ACTIVE的MR侧，STANDBY排除；空/0/非法/非有限值不入样本；精确P10、弱样本、数据不足、阈值变化|
|单链路|无STANDBY、弱STANDBY、缺RSSI、可用备链、LinkCnt=2正常三角；按来源/Radio/AP/风险类型/缺口拆分；源行追溯|
|参数/兼容|任务>Site>规则资源；partial DTO继承；组合错误422；历史optional列和metrics_json只读；没有schema迁移|
|缓存|实际SQLite WAL写入、阈值和身份snapshot变化均重算；单session有界，风险>=10k不缓存|
|XLSX|业务/诊断、空数据、完整行数、中文表头、样式/筛选/冻结/百分比、取消、身份证据；百万当前明细完整100万行，ZIP64降低阈值回归|
|图表/页面|首开full/overview边界、局部high与显式full、原窗口/取消/generation/缓存/LOD测试；摘要懒明细、服务端分页、失败保留、跨session拒旧响应|

四档基准的输入为合成raw和独立等规模parsed SQLite，不是raw→完整Electron→原生保存端到端。性能fixture无风险区段，风险/异常由小fixture回归；不能把其内存结论推广至最坏输入。详见02。

## L4 Full Gate

已执行`.venv/Scripts/python.exe -m scripts.quality.local_gate --mode full`。原始 Python 全量结果为5554 passed、9 failed、2 skipped、35 warnings，1702.29s；这9个失败节点修复后集中复验9 passed，90.89s。没有把初次失败日志改写为PASS，也没有把定向复验称为完整Python重新通过。

本次Gate于2026-11-08 22:40:08至23:10:51（北京时间）执行，最终退出码1、RESULT=FAIL。10个suite中8个PASS，renderer-full和python-full保留FAIL：Renderer原始1408 passed / 1 failed，修正断言后完整重跑1409 passed。其余root/workspace layout、Electron（306 tests/typecheck/build）、架构（12/12 checks）、主线12条contract smoke、Ruff、文档（22 tests）与diff均PASS；无NOT RUN suite。原始`.local-reports/local-gate.json`记录运行开始时HEAD，且执行了工作区dirty组合；最终暂存路径重新判级仍为L4（另含storage registry带来的data/history消费者），不存在降低等级的豁免。

没有在修复后再跑完整Full Gate；最终TEST_STATUS保持PARTIAL。本轮修复的9个Python失败点、所属消费者套件、完整Renderer均有独立复验；未来合并main须按最终集成commit重新执行完整L4门禁。
首次Renderer阶段发现旧API断言未包含新增默认`export_mode=business`；已更新契约并补显式diagnostic断言，完整Renderer重跑1409/1409通过。保留首次失败记录，不将其原日志改写为PASS。

Python初次运行期间发现并修复：SQL/存储登记、原导出测试默认模式与真实只读SQLite fixture、Full/Customer Profile遗漏，以及用户固定报告文件名与文档通用守卫冲突。相关独立复验见上表；不把旧缓存中已不存在的测试名认定为本次失败。

## 未执行的验收

- 真实脱敏大日志或真实历史数据库、`D:\NetConsoleData-dev`只读验收。
- 完整Electron用户操作、原生Windows125%DPI、Excel/WPS GUI打开/保存。
- 正式安装制品、现场设备、长稳或多轮冷缓存性能统计。

上述缺口保留PARTIAL；自动化结构可读与浏览器组件通过不能替代原生/真实验收。未来合并main时，在最终集成commit重跑L4消费者门禁。
