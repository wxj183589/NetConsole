# MR/Mesh 日志分析规则

## 1. 适用范围

本文描述 MR 原始 MESH 日志的导入、解析、链路区段、切换/乒乓、质量规则、页面和 Excel 报表。原始日志是事实来源；目录库、单文件 parsed SQLite、缓存、图表和报表都是可重建产物。

解析兼容性以实际行格式为准，不按“Comware V5/V7/V9”名称做无条件保证。没有 Peer Name 时仍可依据合法 Peer MAC 解析；名称、物理 AP 或站点归属无法解析时必须保留空值/未解析状态，不能猜测。

## 2. 导入与存储

- 原始文件归档到当前数据根的局点 MESH MR `raw/` 目录，重名使用防冲突归档名；路径由 `PathResolver` 解析，不写死仓库或历史 `.local` 位置。
- `catalog.sqlite` 和目录型 `mesh.sqlite` 管理文件目录与入口；明细数据可能在 `source_files.parsed_db_path` 指向的单文件 parsed SQLite。
- `raw/` 永不因解析失败而删除；`parsed/` 和 `outputs/` 可重建。
- 解析保留源文件、源行号和必要原始证据，便于从报表回溯。
- 当前派生库 schema/parser 版本为 `meshlog_compact_v3_tagged_samples`。同一毫秒内日志携带的 `(2)`、`(4)` 等 `timestamp_tag` 属于采样身份的一部分，解析、唯一键、链路分组、质量分析和报告不得把它们合并。
- 正式启动和查询不兼容旧派生 schema，也不自动移动、删除或清空用户数据。检测到旧版或损坏的 `mesh.sqlite` 时返回需要重建的明确错误；维护人员只能在 NetConsole 完全退出后，通过 `scripts/maintenance/rebuild_mesh_parsed_data.py` 先 dry-run，再显式 `--apply` 从受保护 raw 重建。工具只归档派生数据库和 `parsed/`，不移动或删除 `raw/`、`outputs/` 与 catalog，失败时恢复旧派生数据。
- 正式资产来源是当前局点基础资料/设备管理中的车载 MR。打开导入时由显式 ApplicationService POST 按 `linked_device_id → device_uuid → 规范化名称` 幂等准备内部 Profile；设备改名只更新显示名，稳定 `safe_folder_name` 和已有数据目录不变，普通 GET 不隐式写库。
- ZIP、单个/多个 LOG/GZ 和文件夹统一为“安全预览 → 自动确认唯一列车号/CT-CW/正式 MR 映射 → `mesh_bundle_import` Job → 隔离 Profile/SQLite 导入 → 路径复验 → 原子目录提交 → 成功 manifest”。非 ZIP 上传只在运行时缓存封装为受保护 ZIP 后复用同一链。Preview 使用有 TTL/总容量限制的随机 ID，Renderer 不接收绝对路径；检查成员数、单文件/总解压量、压缩比、加密、符号链接、路径穿越、重复显示名和扩展名。整批成功前不得发布成功 manifest，失败或取消恢复原 Profile/catalog。
- `source_files` 保存 `raw_relative_path`、`parsed_relative_path`、bundle/archive SHA 与成员 ID/SHA。读取优先使用当前 MR 相对路径，其次安全文件名、SHA、bundle 归档，最后才读旧绝对路径。当前来源重建走 `mesh_source_rebuild`，只恢复/替换一个 detail SQLite；`mesh_schema_rebuild` 是高级 Profile 全量重建，两者不能混用。
- 同一 ZIP SHA 默认幂等。真实 12 文件包已在系统临时数据根验证：6 列车/12 MR、353,035 条解析记录、0 个解析问题；最终 353,033 条链路中 ACTIVE 129,524、STANDBY 223,509。重复导入同一 SHA 返回 12 个 duplicate，不重复写入；manifest 不含临时根/staging 路径，退出后无 staging/backup 残留。该结果证明当前样本闭环，不等同于所有 H3C 版本现场兼容。
- 2026-07-20 使用同一真实包复验统一入口与来源恢复：12/12 自动匹配，raw/parsed 各 12 份；移走一个 raw 后从 bundle 恢复并重解析 39,160 条，SHA 一致。宁波地铁 1 号线既有 06/34 四个 missing 来源使用现存 raw 原位修复为 ready，合计解析 189,468 条；未移动或删除 raw，也未重建同 MR 其他来源。

## 3. 解析模型

解析器按时间和 Radio 识别 ACTIVE/STANDBY/DOWN 等链路记录，规范化 MAC、RSSI、Tx/Rx Busy、链路计数、建立时间和持续时间。缺失指标写空值/N/A；RSSI 最小值、分位数或抖动只从真实有效样本计算，禁止用 0 或默认值补齐。

相邻同一物理 AP 的双 Radio 可按参数合并。默认参数：

| 参数 | 默认值 |
| --- | --- |
| 主链路切换基准 | 2500 ms |
| 短区段容差 | 500 ms |
| 乒乓临界容差 | 500 ms |
| 同物理 AP 双 Radio 合并 | 是 |
| 边界区段纳入异常 | 否 |
| PIS 返回窗口下限 | 10000 ms |
| 其他业务返回窗口下限 | 8000 ms |

返回窗口若未显式配置，取业务下限与 `3 × (切换基准 + 容差)` 的较大值。短区段阈值为 `max(切换基准 - 短区段容差, 0)`。

区段持续时间根据首末样本并结合采样间隔计算；跨大间隙不得硬连为连续区段。

## 4. 切换与乒乓

- 相邻主链路从 A 到 B 形成切换事件。
- A-B-A 且返回在窗口内形成 AP return/乒乓候选。
- 若 B 的驻留时间小于 `切换基准 - 容差`，判为异常乒乓；落在基准附近的临界区间单独标记；更长驻留为常规返回。
- 同一物理 AP 的 Radio 切换归类为 `same_ap_radio_switch`，不直接计为异常 AP 乒乓。
- 事件严重度必须附诊断原因和证据 ID，不只输出一个布尔值。

## 5. 质量规则

规则源为 `resources/mesh_quality_rules.json`。当前主要 profile：

| Profile | RSSI 优/良/警告/差 | Busy 警告/差 | 无备链 | 差链持续 | fping 丢包警告/差/严重 |
| --- | --- | --- | --- | --- | --- |
| `PIS_WIFI6_40_80_STANDARD` | 42/32/26/20 | 60/75 | 5 s | 3 s | 1%/3%/10% |
| `DCS_WIFI6_DOT11A_20_REMOTE` | 35/28/22/18 | 55/70 | 15 s | 5 s | 0.5%/2%/5% |

RSSI 数值按规则文件既定口径比较。两套 profile 当前 fping 平均延迟阈值为 50/100/200 ms，jitter 警告/差阈值为 20/50 ms。规则变更必须同时更新 JSON、规则加载测试、诊断说明和本文，不能只改 UI 标签。

## 6. 大数据与图表

- 页面按源文件解析到实际的 compact v3 tagged samples 明细库，直接读取版本化标量列；不在正式查询路径回退旧 JSON 指标列。
- 图表只绘制可见窗口或下采样结果，并保留切换点、异常点、锚点等重要样本；不得一次性渲染全部采样。
- Rate 图直接读取 `mesh_links.local_rate_raw/peer_rate_raw` 并明确标注原始值，不猜单位。Retry/Error 图由 Python Query Service 使用同 source、Radio、session/peer 的采样顺序计算非负增量；首样本、缺值和计数器回退/重置返回空值，Vue 不重算。切换 RSSI 复用正式 `switch_events.before_rssi/after_rssi` 事件事实，只展示前后散点，不伪装为连续趋势。
- MR/源文件切换使用防抖、懒加载和 repository 缓存，避免重复解析和重复查询。
- 表格分页/按需读取，详情导出在独立进程中流式/分批查询完整数据；屏幕行数上限不能被误当成导出上限。

## 7. Excel 报表

正式报表走 Export Process，先写临时文件再原子替换。标准工作簿包含：报告总览、质量评分、原始文件清单、采样点质量统计、Active 主链路区段、Peer 质量排名、切换事件分析、异常事件分析、无备份链路风险、空口繁忙度分析、链路重建计数异常、原始证据片段、解析问题。按选项可追加全部链路明细。

宽列、原始行、诊断和建议使用受控列宽与换行，兼顾 Microsoft Excel/WPS。目标文件被占用时给出可操作提示；取消或失败不得保留伪完整 workbook。

Mesh 链路明细导出可在结果 metadata 中附加只读 `export_identity_diagnostics`，但不得改变 workbook 表头、原有列值、筛选、冻结窗格或业务统计。

## 8. 验证清单

- UTF-8、GB18030/GBK 输入与 gzip/普通日志；
- 缺 Peer Name、未知 MAC、重复样本、乱序、跨大间隙和截断日志；
- 单/双 Radio、同物理 AP 切换、A-B-A 临界与异常乒乓；
- 缺失 RSSI/Busy 时不伪造统计；
- 目录库到 `parsed_db_path` 的正确解析；
- compact v3 `timestamp_tag` 唯一键、同毫秒多块顺序和旧派生 schema 显式重建；
- ZIP 路径/压缩安全、预览 TTL、人工映射、隔离提交补偿、manifest 时机、SHA 幂等和绝对路径脱敏；
- Rate 原始值、Retry/Error 回退空值、切换前后 RSSI 事件散点以及图表卸载资源释放；
- 可见窗口、全量下采样、关键点保留和重复加载防抖；
- 大表导出取消、WPS/Excel 占用、临时文件清理和源证据回溯。
