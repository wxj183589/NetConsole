# 宁波地铁 6 号线 MESH AP Identity 真实数据调查

- 调查日期：2026-08-04
- 调查性质：只读取证，不连接 AC、MR 或现场设备，不修改业务代码
- 结论置信度：高（真实数据快照、当前 Resolver、任务记录、页面查询和一次性副本实验相互印证）

## 1. 结论

宁波地铁 6 号线的 FIT-AP、AP Identity entity/alias 和 Resolver 均正常。故障发生在历史 MESH parsed DB 的 identity-only remap 持久化阶段：

- 历史 `mesh_links.peer_mac_normalized` 使用 12 位紧凑键，例如 `083be9eca2ff`；
- `MeshMrRepository.replace_peer_identity_mappings()` 在写 `mesh_peer_mapping.peer_mac_normalized` 和 `mesh_peer_resolve_cache.peer_mac` 时调用 `normalize_mac()`，写成冒号格式，例如 `08:3b:e9:ec:a2:ff`；
- 随后的 SQL 通过 `pm.peer_mac_normalized = mesh_links.peer_mac_normalized` 做严格字符串等值关联，两个键集合的原始字符串交集为 0；
- mapping 表虽然包含正确的 `matched` 结果，`mesh_links` 和 `active_points` 身份投影却零命中，仍保持 `unresolved`；
- remap 完成判定只检查 Identity revision 大于 0 和链路行数未变化，没有验证 matched 结果是否真正写回，因此错误发布 `identity_mapping_status=ready`；
- 页面/API 按设计读取 `mesh_links` 身份投影，所以继续显示未关联。

根因分类：

1. `mesh_identity_remap_not_persisted`：直接根因；
2. `frontend_or_query_reads_stale_projection`：直接用户影响，查询读取的是未被 remap 更新的 parsed 投影；
3. `other`：remap 零持久化命中仍被错误标记为 `ready`。

不属于 `wrong_site_database`、`identity_index_not_built`、`identity_index_stale`、`h3c_alias_not_generated`、`ac_vendor_not_normalized`、`duplicate_exact_alias` 或 `trackside_role_filtered`。

## 2. 环境与真实路径

| 项目 | 实际值 |
| --- | --- |
| 产品运行版本 | `v1.4.7` |
| 当前运行/问题复现 commit | `97a0ac43593808da712cb578e9f26e2ac3509305` |
| 调查开始时仓库业务基线 | `97a0ac43593808da712cb578e9f26e2ac3509305` |
| 报告生成时工作分支 HEAD | `13d46fd6db1b32e6fc9610192a2b855892b89b37`；其相对 `97a0ac43` 的变更仅涉及 Artifact/Task Center，不涉及 AP Identity 或 MESH |
| Python | `3.13.9` |
| 数据根来源 | `HKLM\Software\NetConsole\DataRoot` |
| 数据根 | `D:\NetConsoleData` |
| 当前运行配置 | `current_site=宁波地铁6号线` |
| Registry 稳定 site_id | `legacy-0d1a8935839e` |
| display_name / 物理目录名 | `宁波地铁6号线` |
| `site_meta.site_uuid` | `site-022c17e1-ec95-43f1-9443-7feb3172d5a5` |

运行代码当前以中文物理目录名作为 PathResolver 的局点参数。Identity 表内的 `site_id='current'` 是单局点数据库内部固定作用域，不是 Registry 稳定 site_id。

实际文件映射：

| 用途 | 绝对路径 |
| --- | --- |
| FIT-AP / AP Identity DB | `D:\NetConsoleData\sites\宁波地铁6号线\db\devices.db` |
| MESH remap 实际读取 DB | `D:\NetConsoleData\sites\宁波地铁6号线\db\devices.db` |
| Task Center DB | `D:\NetConsoleData\sites\宁波地铁6号线\db\tasks.db` |
| MESH catalog | `D:\NetConsoleData\sites\宁波地铁6号线\files\rail_transit\mr_raw_mesh\catalog.sqlite` |
| Profile | `D:\NetConsoleData\sites\宁波地铁6号线\files\rail_transit\mr_raw_mesh\列车24-MR-CT` |
| Profile source index | `D:\NetConsoleData\sites\宁波地铁6号线\files\rail_transit\mr_raw_mesh\列车24-MR-CT\mesh.sqlite` |
| 2026-07-08 parsed detail | `D:\NetConsoleData\sites\宁波地铁6号线\files\rail_transit\mr_raw_mesh\列车24-MR-CT\parsed\meshlog.mesh.sqlite` |
| 2026-07-08 raw | `D:\NetConsoleData\sites\宁波地铁6号线\files\rail_transit\mr_raw_mesh\列车24-MR-CT\raw\2026\07\meshlog.log` |

FIT-AP 与 MESH remap 打开的是同一个 `devices.db`，路径和 SHA-256 均相同，不存在跨局点串库。目标 Profile 的 `mr_id` 为 `f660abbf-956e-492a-9ac0-b5be030bc0ae`；2026-07-08 来源的 `source_file_id=1`，页面 `session_id=f660abbf-956e-492a-9ac0-b5be030bc0ae:1`。

## 3. 数据安全与快照

调查时 Electron、Python Backend 和 Vite/Node 进程均在运行。没有连接 AC/MR，没有调用 FIT-AP 刷新，没有重新导入日志，也没有对真实 DB 执行 checkpoint、VACUUM、REINDEX、迁移或重建。

所有查询使用仓库外目录：

`D:\NetConsoleDiagnostic\mesh-ap-identity-20260804`

SQLite 快照均由只读 URI 源连接和 Backup API 制作：

```python
source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
target = sqlite3.connect(snapshot_path)
source.backup(target)
```

一次性 Identity 重建和 remap 实验只在 `devices_db.disposable_rebuild.sqlite`、`source_1_remap_disposable.sqlite` 执行。

### 3.1 调查前后源文件核验

| 真实源文件 | 大小 | 调查前 SHA-256 | 调查后 SHA-256 | WAL/SHM | 结论 |
| --- | ---: | --- | --- | --- | --- |
| `devices.db` | 18,059,264 | `93f73d973aa16f25a635c18c8eefbfcf243c064c0c19049e52ca612463356aac` | `77531603def2c34ebc14dd9d0c047c35e9f9bc58d3d389ec1e5aa18033c9a0fa` | WAL 0 B / SHM 32,768 B | 文件级哈希在应用运行期间变化；前后 Backup 快照的全部业务表行数和逐行内容指纹完全一致，无业务数据差异 |
| `tasks.db` | 4,669,440 | `41b815090b60c3df4aa0236a99e3ce120f63fcdbf787177fc74afea3e5872ace` | 同前 | WAL 0 B / SHM 32,768 B | 未变 |
| `catalog.sqlite` | 94,208 | `3efb953d8ad0cb12e0d9736aadfa5823fe4d2cbc55b25bce50ae45afd25f0399` | 同前 | WAL 61,832 B / SHM 32,768 B | 未变 |
| Profile `mesh.sqlite` | 348,160 | `7fcea4c26e3456da929d3368da3b009871f3240a898db89d9e65d08f931f8ab6` | 同前 | WAL 0 B / SHM 32,768 B | 未变 |
| source 1 parsed DB | 100,265,984 | `94a31d68f1dcc9ab4b6c663a868522aaeae095bfafa61cac1777b8af33247518` | 同前 | WAL 0 B / SHM 32,768 B | 未变 |
| source 1 raw log | 14,623,111 | `3e5d5af8d2ff70c5b83e24b4d5da6ed255dfd05ab8edfdde7d628309b7133ffc` | 同前 | 无 | 未变 |

`devices.db` 的文件级哈希例外不能被表述为“字节未变”。为排除调查写入，在最终时点再次从真实源制作 Backup 快照，并与调查前快照逐表比较：所有非 SQLite 内部表的行数和按完整行计算的 SHA-256 指纹均相同。调查工具本身只创建只读源连接；该文件级变化发生时正式应用仍持有数据库连接，证据只能支持“业务表内容未变、调查未发出写操作”，不能断言活跃 SQLite 文件从未发生非语义性写入。

## 4. FIT-AP 与 AP Identity

真实快照统计：

| 指标 | 数量 |
| --- | ---: |
| FIT-AP 资源 | 602 |
| 基础 AP | 776 |
| Identity entities | 777 |
| aliases | 4,211 |
| derived aliases | 2,406 |
| ambiguous aliases | 0 |
| 实采 Radio/BSSID/BBSSID aliases | 0 |

Identity index 状态：`revision=1`、`source_revision=776`、source state revision `776`、`build_reason=mesh_peer_mapping_refresh`、`built_at=2026-08-04T02:34:04.693239+00:00`。索引存在、健康且与来源 revision 一致。

两个目标 AP 的 AC 厂商均规范化为 `H3C`。每个物理 MAC 只有一条 FIT-AP 资源、一个稳定 AP UUID，没有资源重复。对应的替代物理候选 `10b6-5e92-bed0` 与 `083b-e9ec-a2f0` 均不存在。

全库有一条与本故障无关的 legacy/base alias 冲突：`94a7482c14c0` 指向两个 entity。它不涉及两个样本，也不影响本次 549 个 MESH Peer 的 Resolver 结果。

## 5. 两个重点样本

### 5.1 `10b6-5e92-beef`

| 层级 | 真实结果 |
| --- | --- |
| FIT-AP | 唯一物理 AP `10b6-5e92-bee0`，名称 `AP-CLD_40`，站点 `35高桥南车辆段` |
| Identity entity | `ac:476c5e7b-44b3-4680-813c-1a9014b22e1f`，`matched` |
| Alias | AC/Base 各一条 `h3c_r1_derived`，均指向同一 entity |
| Resolver，无 role | `matched`，rule=`h3c_physical_mac_to_r1_exact_v1`，confidence=95，radio_id=1 |
| Resolver，trackside | 与无 role 完全相同 |
| 历史 MESH | source 2 出现 7,236 行，parsed 投影全部 `unresolved` |
| mapping | 存在正确 `matched` 行，但 key 为冒号格式，未写回紧凑格式的历史投影 |

诊断：H3C R1 派生、Identity 和角色筛选均正确；失败只发生在 MESH identity remap 的等值关联。

### 5.2 `083b-e9ec-a2ff`

| 层级 | 真实结果 |
| --- | --- |
| FIT-AP | 唯一物理 AP `083b-e9ec-a2e0`，名称 `AP-X_1906`，站点 `20翠柏里站` |
| Identity entity | `ac:f85fa7b6-cae8-43f3-b254-7ac3654ba3db`，区间 `望春桥站-翠柏里站` |
| Alias | AC/Base 各一条 `h3c_r2_derived`，均指向同一 entity |
| Resolver，无 role | `matched`，rule=`h3c_physical_mac_to_r2_exact_v1`，confidence=95，radio_id=2 |
| Resolver，trackside | 与无 role 完全相同 |
| source 1 mapping | 正确映射到 `AP-X_1906`，但 key 为 `08:3b:e9:ec:a2:ff` |
| source 1 `mesh_links` | key 为 `083be9eca2ff`；782 行全部 `unresolved/exact_alias_not_found`，AP 名称、物理 MAC、站点、区间为空 |
| 页面 API | saved revision=1、current revision=1、status=`ready`、无 stale warning，但仍返回上述 unresolved 投影 |

诊断：H3C R2 派生、Identity 和角色筛选均正确；页面显示忠实反映了未更新的 `mesh_links`，不是前端重新计算错误。

## 6. 全量覆盖统计

### 6.1 列车24-MR-CT，2026-07-08 来源

| 指标 | 结果 |
| --- | ---: |
| distinct Peer | 254 |
| Resolver matched | 254 |
| Resolver unresolved / ambiguous / invalid | 0 / 0 / 0 |
| identity_index_missing / stale | 0 / 0 |
| exact_alias_not_collected / not_found | 0 / 0（Resolver 层） |
| duplicate_exact_alias / physical_ap_missing | 0 / 0 |
| role 结果不同 | 0 |
| mapping 行 / matched | 254 / 254 |
| 规范化后的 mapping/link key 交集 | 254 |
| 原始字符串 mapping/link key 交集 | 0 |
| parsed `mesh_links` | 77,182 行、254 个 Peer，全部 `unresolved/exact_alias_not_found` |

分类结果：254/254 均为“Identity 正常，但 MESH 投影未更新”。脱敏 CSV 位于：

`D:\NetConsoleDiagnostic\mesh-ap-identity-20260804\source_1_peer_coverage_redacted.csv`

CSV 仅包含要求的 Peer、候选数量、alias/Resolver 结果和匹配后的 AP/站点/区间字段，不包含账号、密码、设备 IP、序列号或原始日志内容。

### 6.2 列车24-MR-CT 全部 6 个来源

| source | 日期 | 行数 | distinct Peer | Resolver/mapping | parsed 投影 |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | 2026-07-08 | 77,182 | 254 | 254 matched | 77,182 unresolved |
| 2 | 2026-07-24 | 7,423 | 3 | 3 matched | 7,423 unresolved |
| 3 | 2026-07-24 | 40,543 | 3 | 3 matched | 40,543 unresolved |
| 4 | 2026-07-25 | 6,473 | 2 | 2 matched | 6,473 unresolved |
| 5 | 2026-07-25 | 14,371 | 51 | 51 matched | 14,371 unresolved |
| 6 | 2026-07-26 | 240 | 1 | 1 matched | 240 unresolved |

6 个来源合并后有 272 个唯一 Peer，Resolver 272/272 matched；全部 146,232 条 parsed 链路仍 unresolved。每个来源都满足“原始字符串交集 0、规范化交集等于 distinct Peer 数”。

### 6.3 宁波 6 号线全部有效 parsed 来源

当前 catalog 中发现 3 个 Profile，其中 8 个来源具有有效 parsed path，涉及列车24-MR-CT 和列车24-MR-CW：

- 总链路：208,216；
- 唯一 Peer：549；
- 当前 Resolver：549 matched，其他状态均为 0；
- parsed 投影：208,216 行全部 unresolved。

因此不是单个 MAC、单个日期、车辆段角色或单个 Profile 的问题，而是所有历史 parsed 来源共同经过的 remap key 契约错误。

## 7. 一次性副本实验

### 7.1 强制重建 Identity

仅在 `devices_db.disposable_rebuild.sqlite` 执行 `rebuild_index("diagnostic_disposable_rebuild")`：

| 指标 | 重建前 | 重建后 |
| --- | ---: | ---: |
| revision | 1 | 2 |
| source_revision | 776 | 776 |
| entities | 777 | 777 |
| aliases | 4,211 | 4,211 |
| derived aliases | 2,406 | 2,406 |
| ambiguous aliases | 0 | 0 |
| 两目标 Resolver | matched | matched |

重建没有改变 entity/alias 或解析结果，排除“旧索引错误复用导致 alias 缺失”。

### 7.2 只修正 remap key

仅在 `source_1_remap_disposable.sqlite` 中把 mapping/cache key 从冒号格式规范成 12 位紧凑格式，再复用现有严格等值 refresh：

| 指标 | 修正前 | 修正后 |
| --- | ---: | ---: |
| `mesh_links` 行数 | 77,182 | 77,182 |
| distinct Peer | 254 | 254 |
| identity 状态 | 77,182 unresolved | 77,182 matched |
| 原始 MESH 事实指纹 | `6d65b90975487ef48ed364ae9b522b43916f5f532d68aa15910a6368d2f27117` | 同前 |

`083b-e9ec-a2ff` 的 782 行全部恢复为 `AP-X_1906 / 083b-e9ec-a2e0 / 20翠柏里站 / Radio 2`。该实验只改变身份投影，不改变 raw、链路数、ACTIVE/STANDBY 或切换事实，直接验证了根因。

## 8. “重新解析当前日志”为何无效

健康 detail DB 的服务路径在 `src/netconsole/services/mesh_source_rebuild_service.py:58` 明确优先执行 identity-only remap，不重新解析 raw。source 1 任务：

- task_id：`rail-web-983fe11b943542d2b43e415987040582`；
- status：`COMPLETED`；
- recovery_source：`identity_only_remap`；
- before：matched 0 / unresolved 77,182；
- after：matched 0 / unresolved 77,182；
- mapping_count：254；
- identity revision：1；
- 仍发布 `identity_mapping_status=ready`。

当前运行 commit 产生的 source 5 任务 `rail-web-7e6161ec8e484ad88e0a694778efdaa3` 也得到 before/after matched 0、unresolved 14,371、mapping_count 51，并错误标记 `ready`，证明问题仍存在于 `97a0ac43`，不是旧任务遗留。

代码链路：

1. `src/netconsole/services/mesh_peer_mapping_service.py:105` 调用 `ensure_index()`；当前索引健康，revision 保持 1；
2. `src/netconsole/services/mesh_peer_mapping_service.py:107` 生成正确 mapping 并调用 repository remap；
3. `src/netconsole/repositories/mesh_mr_repository.py:2661` 用 `normalize_mac()` 把 persisted key 变成冒号格式；
4. `src/netconsole/repositories/mesh_mr_repository.py:2724` 起用未归一化的严格字符串等值关联更新投影，零命中；
5. `src/netconsole/services/mesh_peer_mapping_service.py:111` 仅以 revision 大于 0 决定 `ready`；
6. `src/netconsole/services/mesh_source_rebuild_service.py:84` 只断言 remap 没改变链路行数，没有断言 mapped/unresolved 结果；
7. 页面查询继续读取 `mesh_links`，所以即使 revision 显示一致，也仍得到旧 unresolved 投影。

## 9. 最小修复建议

### 9.1 代码修复

1. 在 `src/netconsole/repositories/mesh_mr_repository.py` 的 `MeshMrRepository.replace_peer_identity_mappings()` 中，将 `mesh_peer_mapping.peer_mac_normalized` 和 `mesh_peer_resolve_cache.peer_mac` 的持久化/join key 统一为 `normalize_mac_key()` 返回的 12 位紧凑格式；显示字段仍可保留现有格式。
2. 兼容历史 compact/colon 数据。固定后的 remap 应覆盖 mapping/cache；必要时在同一事务内规范化临时关联键或在 SQL 两侧使用等价的完整 48 位 MAC 规范化，不能改写 `mesh_links.peer_mac_normalized` 所承载的历史事实。
3. 在事务提交前校验：mapping key 与 link key 的规范化覆盖数、mapping 状态计数、after matched/unresolved/ambiguous 必须与 Resolver summary 一致。预期有 matched mapping 而持久化命中为 0 时必须失败，不能发布 `ready`。
4. `MeshSourceRebuildService` 只有在上述验证通过后，才更新 detail metadata、source index revision/status 并 checkpoint；失败时保留旧投影并返回明确错误。
5. 页面/API 不需要另建 Resolver 旁路。修好投影并对历史来源执行 identity-only remap 后，现有查询即可读取正确结果。

### 9.2 Schema 与历史数据

- `devices.db` 不需要 schema 变更；
- parsed DB 预计不需要 schema 变更，只需修正值规范和完成条件；
- 不需要重解析、删除或重新导入 raw；
- 固定代码部署后，对历史 MESH 来源批量执行一次幂等 identity-only remap；
- 不修改链路数、ACTIVE/STANDBY、切换事件、时间戳、RSSI 或原始行定位。

### 9.3 自动测试

至少覆盖：

1. 历史紧凑 `mesh_links` + 新 mapping 输入的冒号/短横线/紧凑 MAC 均可原子回填；
2. `10b6-5e92-bee0 -> 10b6-5e92-beef` 与 `083b-e9ec-a2e0 -> 083b-e9ec-a2ff`；
3. source revision 相同且 Identity 已健康时仍能正确 remap 历史投影；
4. raw 事实指纹、链路数和 ACTIVE/STANDBY 不变；
5. mapping matched 但投影零命中时任务失败且不得标 `ready`；
6. 正线与车辆段 trackside Resolver 结果；
7. alias 冲突必须 `ambiguous`，不得取第一条；
8. GET 查询不写数据库；
9. 不同局点不得串库。

## 10. 是否进入修复阶段

建议进入修复阶段。证据已将问题收敛到一个可重复、可在 disposable 副本上 100% 修复的 key 规范契约错误，不需要继续连接现场设备或猜测 Identity builder。

修复应在基于最新 `main` 的独立 worktree/分支完成，并保留对运行版本 `97a0ac43` 生成的历史 compact parsed DB 的兼容。推荐分支 `fix/ningbo-line6-mesh-ap-identity`，推荐 worktree `D:\study\NetConsole-worktrees\fix-ningbo-line6-mesh-ap-identity`。
