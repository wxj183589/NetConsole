# Mesh Phase 11.2–11.4 真实数据与 Electron 验证

日期：2026-11-09。已完成真实三点离线源码和当前Service只读核验；当前源码的真实 Electron GUI 验收受启动策略阻塞。

## 验证边界

- 唯一真实数据 Authority：`D:/NetConsoleData-dev`，SQLite 以 URI `mode=ro` 与 `PRAGMA query_only=ON` 读取。
- 未复制数据库、Site 或数据根；未修改 Production；未启动或关闭进程。
- 仅在仓库生成核验脚本、JSON 和本报告，不将运行密钥写入报告或控制台。
- 分支：`codex-A/mesh-analysis-scope-ui-optimization`；验收准备时 HEAD：`ec174410dc3b491bcb3d3a29fc8df25012fee8f6`。

## 历史真实 Electron 路径与当前阻塞

| 项目 | 实际观测 |
| --- | --- |
| Electron PID | 56400 |
| Renderer CDP | 127.0.0.1:9333 |
| Main CDP | 127.0.0.1:9334 |
| 页面 | `http://127.0.0.1:5183/rail-transit/mesh-analysis` |
| API | `http://127.0.0.1:18781` |
| 页面尺寸 | 1920 × 1080，devicePixelRatio=1 |

以上为本轮前段实际观测，不能代表最终源码已完成 GUI 验收。再次准备取证时，PID56400 已不存在，9333/9334/18781 均无监听，CDP 返回连接拒绝。父任务尝试启动本任务 runtime 被自动审批以 `blocked by policy` 拒绝，未提供更具体范围。本验收未换方式启动相同 runtime，未注入 CDP，也未制造截图。当前源码的1920×1080/DPR1截图、滚轮/选择交互JSON、列设置网络行为和Tooltip视觉验收均未执行。

## 真实连续三点 counter 手算

执行：`.venv/Scripts/python.exe .local/phase11_counter_real_check.py`。

数据：宁波地铁12号线，列车01-MR-CW，Radio1，AP `bc:5a:34:57:62:c0`，ACTIVE；窗口 `2026-10-20 18:38:42.000` 至 `18:38:44.999`。三点的同一链路身份经过 source/radio/peer/establish/peer-radio 一致性检查。

| 采样时间 | 本端 Tx 累计 | 本端增量 | 间隔秒 | 本端次数/秒 | 对端 Tx 累计 | 对端增量 | 对端次数/秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 18:38:42.656 | 11054 | 无前值 | 无前值 | 无前值 | 1564 | 无前值 | 无前值 |
| 18:38:42.690 | 11331 | 277 | 0.034 | 8147.058823529411 | 1579 | 15 | 441.17647058823525 |
| 18:38:43.656 | 12388 | 1057 | 0.966 | 1094.2028985507247 | 1771 | 192 | 198.75776397515529 |

公式：增量＝本次累计－上次累计；每秒值＝增量÷实际采样间隔。首点没有基线，不显示零增量或伪造速率。脚本独立计算 Tx/Rx、Retry/Err、GARP/MulJoin 共12个 counter 字段，并逐项比较 API。三条对应归档原始日志行均读取成功。

首次实跑：HTTP200，3点，`all_delta_checks_match=true`，`fingerprints_unchanged=true`。数据库与原始 gzip 的 size/mtime/SHA256 前后相同。完整证据在 [real-counter-three-points.json](real-counter-three-points.json)。

当前限制：运行后端尚未返回 `counter_samples`，`counter_metadata_available=false`。本次只确认已有 delta 结果，不能据此宣称 API 的 current/previous/interval/per_second 或 UI Tooltip 已通过。实现更新且本任务后端重启后，须重新执行脚本核验全部元数据。脚本已包含实际间隔与速率的数值比较。

### 当前源码离线复核

执行：`.venv/Scripts/python.exe .local/phase11_counter_real_check.py --offline --output docs/reports/mesh-phase11-2/real-counter-three-points-offline.json`。

此模式直接导入当前 `mesh_monitor_sampling.py` 的实际纯计算函数，对真实SQLite中只读提取的同一三点进行处理；独立手算逐项比较12项counter的 current、previous、delta、interval_seconds、per_second。没有启动 Backend/Electron，也不等同于 API/GUI 验收。

实跑结果：3点、12字段，`counter_metadata_available=true`，`all_delta_checks_match=true`；两段实际间隔0.034秒和0.966秒均一致。数据库与原始gzip size/mtime/SHA256前后相同，`fingerprints_unchanged=true`。证据见 [real-counter-three-points-offline.json](real-counter-three-points-offline.json)。数据库SHA256仍为 `2b8bf5b5c7fdf350f2cb105eb1512d6f93b292354b5739942d2c49e6f78da61d`，原始gzip SHA256仍为 `f53990d5448f297ea8cbc6901d87132fcf3f616c61149feaa4e875829a3b0fc7`，与首次API核验记录相同。

通过范围仅为上述同一物理链路的三点正常counter；AP切换、重置、缺失、长间隔等由定向自动测试覆盖，不能用本三点宣称这些场景已通过真实日志GUI验收。

## 当前Service真实查询与性能

证据：[real-service-query-validation.json](real-service-query-validation.json)。未启动Backend或Electron；只将Service上下文绑定到既有source_files行与实际AP身份快照，SQL、sampler、DTO均使用当前源码，未mock计算或查询。位置目录解析不属于此次验证范围。所有连接mode=ro且query_only=ON。

- 窄窗口有4条记录（包括18:38:42.690），实际查询2.50ms。抽查18:38:42.656、18:38:43.656、18:38:44.656三个目标，nearest均返回同一真实record；12字段current/previous/delta/interval/per_second与独立计算及普通counter查询完全一致。18:38:43.656的前值确为42.690，间隔0.966秒，不能跳过中间记录使用1秒。
- nearest三次耗时6.09/690.73/2.68ms，中间一次包含首次原始gzip零链路扫描；不能将其归为纯SQL耗时。
- 默认末尾五分钟18:37:06.381～18:42:06.381，Radio1、ACTIVE、不限AP：465条原始记录，降采样返回240条。首次2190.47ms，重复2306.04ms；真实执行新增角色/切换上下文相关子查询，无超时。两次测量不是稳定SLA，也不能推导全历史查询性能。
- DB/raw的SHA256、大小及mtime_ns前后完全一致，与上次离线核验一致。未复制数据库、未修改业务数据。

此结果补齐当前Service真实查询和计算，不等于运行HTTP API序列化、Electron或GUI验收。

## 可执行截图与交互清单

以下均为待执行场景，只有实际截图与交互证据落盘后才改为通过。

### Phase 11.2

保存到 `docs/reports/mesh-phase11-2/screenshots/`：

1. 列设置中连续勾选多项、尚未应用：截图草稿；记录请求数保持不变。
2. 单次应用后表格结果：仅必要查询；纯列显隐复用已有数据。
3. 中文链路明细表、统一建立顺序表。
4. RSSI、CPU/内存、TxBusy/RxBusy、Rate/Noise 的两端曲线。
5. Tx/Rx、Retry/Err、GARP/MulJoin 每秒曲线；真实 counter Tooltip 的本次/上次/增量/间隔/每秒值。
6. AP 或 Peer/Radio 切换后的基线断开，无跨链路相减。

### Phase 11.3

保存到 `docs/reports/mesh-phase11-3/screenshots/`：

1. 单行导航：分析概览、链路明细、RSSI分析、AP情况、主链路监控、切换事件、报告与来源。
2. 概览、链路明细、RSSI、AP情况、主链路监控完整布局。
3. 右侧中文两端详情。
4. 图表上普通滚轮前后：页面 scrollY 变化、时间窗口不变。
5. Shift+滚轮前后：共享时间窗口同步变化、页面无意外滚动。
6. 时间轴拖动与图表指针同步。

### Phase 11.4

保存到 `docs/reports/mesh-phase11-4/screenshots/`：

1. 右侧详情可读字号和布局；实测 computed font-size、溢出和截断。
2. RSSI、CPU、Tx、Retry/Err、GARP/MulJoin 真实悬浮 Tooltip。
3. Shift+左键任意横坐标：选取最近有效 ACTIVE 毫秒采样，固定指针与 AP 详情一致。
4. 指针移出图表后固定选择保留。
5. Ctrl+横向移动：详情随采样更新、各图指针同步、不触发全历史请求。
6. Ctrl 时间轴拖动或窗口排除当前选点：选择窗口内最近有效 ACTIVE 采样。
7. Esc 清除固定选择并恢复普通悬浮。
8. 多图时间戳与共享窗口一致。

## 待验收项

- 当前源码离线三点counter元数据、真实间隔、每秒值已通过；运行API端到端仍未复核。
- UI 完成后执行上述真实 Electron 截图，记录交互前后窗口/选点/请求数证据。
- 单 AP、时间窗口、Radio 切换后的 counter 断点和缓存行为。
- 当前Service实跑已完成；未执行项如上，不以计划替代成功证据。
