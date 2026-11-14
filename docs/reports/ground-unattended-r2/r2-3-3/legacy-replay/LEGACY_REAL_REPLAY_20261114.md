# v1.5.13 Ground Syslog 真实历史数据回放专项验收

## 1. 环境与输入

| 项目 | 实际结果 |
| --- | --- |
| 代码仓库 | `D:\study\NetConsole-Workspace\NetConsole` |
| Branch / HEAD | `main` / `7d8d695f730439512b48e094f8067c256045efab` |
| 版本 | `v1.5.13` |
| 回放程序 | `scripts/dev/ground_unattended_legacy_replay.py` |
| 实际命令 | `.venv\Scripts\python.exe scripts/dev/ground_unattended_legacy_replay.py --archive C:\Users\18358\Desktop\2026-11-09_ground_unattended.zip --output-dir D:\study\NetConsole-Workspace\test-data\NetConsole\ground-syslog-real-replay-20261114 --site-id hzl10 --run-id ground_20261109_fe484f124afe` |
| 实际输入 | `C:\Users\18358\Desktop\2026-11-09_ground_unattended.zip` |
| 输入 SHA-256 | `19519d67f395ee18fc45b178bb36a1868946c716284c152441055464e0b59c41` |
| 隔离输出 | `D:\study\NetConsole-Workspace\test-data\NetConsole\ground-syslog-real-replay-20261114` |
| 真实数据候选 | `D:\NetConsoleData-dev\sites\hzl10` 已检查；本次未将其作为回放输出或写入目标 |

回放程序直接流式读取 ZIP，不解压覆盖原始归档，不连接设备，不启动正式无人值守服务。归档 SHA-256 前后相同；未修改 `D:\NetConsoleData-dev`、`D:\NetConsoleData` 或现场设备。

## 2. 归档完整性与解析统计

| 指标 | R2.3.3 基线 | 当前 main 实测 |
| --- | ---: | ---: |
| ZIP 文件成员 | 780 | 780 |
| 非目录成员 | 467 | 467 |
| manifest 成员校验 | 466 登记 | 466/466 通过 |
| 原始 Syslog | 40,290 | 40,290 |
| 结构化事件 | 40,120 | 40,120 |
| WMESH 事件 | 39,827 | 39,827 |
| 回放 MR 状态 | 35 | 35 |
| 原始重复行 | 0 | 0 |
| 语义重复组 / 重复记录 | 49 / 49 | 49 / 49 |
| JSON/编码/ZIP 错误 | 0 | 0 / 0 / 0 |

当前 Parser 统计：170 行解析失败，全部命中归档中已知的重启、命令或非 WMESH IFNET 标记；没有形成回放失败。事件数量为：

- `MESH_LINKUP`: 14,276
- `MESH_LINKDOWN`: 14,228
- `MESH_ACTIVELINK_SWITCH`: 11,323
- `CFGMAN_CFGCHANGED`: 262
- `IFNET_PHY_UPDOWN`: 31

扩展身份回放保留完整 39,827 条 WMESH 历史；接收序重复事件 36 条、乱序事件 52 条；按有效事件时间排序时乱序为 0。严格身份源未信任未确认的 Syslog 源 IP，扩展身份回放没有发现源 IP 冲突或歧义端点。

## 3. Current / Previous 与主用链路切换

与 R2.3.3 scheduler 投影可比较的结果：

| 对照项 | 基线 | 当前 main |
| --- | ---: | ---: |
| Current AP | 26/26 | 26/26，100% |
| Previous AP | 22/22 | 22/22，100% |
| Current 差异 | 0 | 0 |
| 位置历史 | 39,827 | 39,827 条完整 WMESH 投影 |

样本级检查使用当前 `PositionEngine` 的事件应用前后状态，真实序列包括：

| MR | 切换时间 | 旧 AP → 新 AP | 后续旧 AP LINKDOWN | 结果 |
| --- | --- | --- | --- | --- |
| `03cae92f...` | 16:27:28 | `74:ad:cb:a8:dc:60` → `74:ad:cb:a8:db:40` | 同秒，旧 AP | Current 保持 `...db:40`，Previous 保持 `...dc:60` |
| `92a061c1...` | 16:27:28 | `74:ad:cb:a9:07:c0` → `74:ad:cb:a8:db:60` | 同秒，旧 AP | Current 保持 `...db:60`，Previous 保持 `...07:c0` |
| `92a061c1...` | 16:27:28 | `74:ad:cb:a8:db:60` → `74:ad:cb:a8:d5:80` | 同秒，旧 AP | Current 保持 `...d5:80` |
| `92a061c1...` | 16:27:33 | `74:ad:cb:a8:d5:80` → `74:ad:cb:a8:cd:c0` | 同秒，旧 AP | Current 保持 `...cd:c0` |
| `03cae92f...` | 16:27:40 | `74:ad:cb:a8:d5:80` → `74:ad:cb:a9:07:c0` | 同秒，旧 AP | Current 保持 `...07:c0` |

全量样本结果：11,486 条“LINKDOWN 到达时其 AP 已不是 Current”的旧链路断开事件中，11,486 条均未改变 Current、Previous、有效位置时间锚点；未发现未保护样本。`MESH_ACTIVELINK_SWITCH` 中有 5,025 条引起位置状态变化，其余为重复/同 Current/时序边界等不改变 Current 的观察，未被误计为日志丢失。

结论：

```text
ACTIVE_SWITCH_CORRECTNESS=PASS
OLD_LINKDOWN_PROTECTION=PASS (11486/11486)
CURRENT_PREVIOUS_COMPARISON=PASS (26/26, 22/22)
```

## 4. 未识别事件保护

当前 PositionEngine 复放得到 2,481 条 `POSITION_RETAINED_UNRESOLVED` 事件；其中：

- 未解析事件创建新 Current：0；
- 未解析事件推进 Current/Previous：0；
- 未解析事件推进 `last_event_time` 或 `last_switch_time`：0；
- 解析身份不完整时保留最后有效位置，不进行 AP 猜测；
- 当前归档扩展身份统计的 `UNRESOLVED` 事件为 2,467 条，严格身份回放为 3,572 条，属于身份源范围差异，不是回放失败。

```text
UNRESOLVED_EVENT_PROTECTION=PASS
REPLAY_FAILURES=0
```

## 5. AC、Heartbeat 与其他通道边界

归档包含 389 个 AC 快照、37,511 行快照记录；387 个快照接受、2 个拒绝。AC 对账分类为 29 个 `AC_NEWER`、6 个 `STALE`（仅按排序边界观察时 35 个 `AC_NEWER`）。Syslog Current 与 AC 可比较项为 26 个，AC 匹配 0 个、差异 26 个；这些差异被保留为独立参考，不覆盖 Syslog Current、Previous 或 Syslog 切换时间。

归档回放入口不把 Heartbeat/Ping 作为位置事实源。另运行了当前 main 的定向测试：

```text
pytest tests/test_ground_unattended_position_engine.py \
       tests/test_ground_unattended_heartbeat_state.py \
       tests/test_ground_unattended_heartbeat_resident.py \
       tests/test_ground_unattended_ac_reconciliation.py
53 passed, 1 warning
```

这些测试覆盖旧 AP LINKDOWN、未解析事件锚点、AC 延迟不替换 Syslog、Heartbeat 独立配置/生命周期/故障恢复及读 API 不写入位置状态。归档本身未提供现场 Heartbeat 实时流，因此不将离线回放写成现场 Heartbeat 验收。

```text
AC_REFERENCE_ONLY=PASS
HEARTBEAT_INDEPENDENT=PASS (定向测试；现场实时流未验证)
```

Ping 历史保留原有归档质量限制：工具结果为 `PING_HISTORY=REVIEW`，不影响本次 Syslog 位置回放结论。

## 6. 最终结论

```text
NETCONSOLE_SYSLOG_REAL_REPLAY=PASS

MAIN_HEAD=7d8d695f730439512b48e094f8067c256045efab
REAL_ARCHIVE_FOUND=PASS
REAL_ARCHIVE_INTEGRITY=PASS

RAW_SYSLOG_COUNT=40290
STRUCTURED_EVENT_COUNT=40120
WMESH_EVENT_COUNT=39827

MESH_LINKUP_COUNT=14276
MESH_LINKDOWN_COUNT=14228
MESH_ACTIVE_SWITCH_COUNT=11323
ACTIVE_SWITCH_COUNT=11323

MR_IDENTITY_MAPPING=PASS_WITH_LIMITATION
AP_IDENTITY_MAPPING=PASS_WITH_LIMITATION

CURRENT_AP_COMPARISON=26/26
PREVIOUS_AP_COMPARISON=22/22

ACTIVE_SWITCH_CORRECTNESS=PASS
OLD_LINKDOWN_PROTECTION=PASS
UNRESOLVED_EVENT_PROTECTION=PASS
AC_REFERENCE_ONLY=PASS
HEARTBEAT_INDEPENDENT=PASS_WITH_REAL_STREAM_PENDING

POSITION_ENGINE=PASS
REPLAY_FAILURES=0
REAL_DATA_UNCHANGED=PASS
WORKTREE_CLEAN=PASS_BEFORE_REPORT_COMMIT

OVERALL_STATUS=PASS_WITH_LIMITATION
FINAL_STATUS=PASS_WITH_LIMITATION
```

本结论是杭州地铁 10 号线真实历史归档的离线回放结论，不代表现场设备、实时无人值守服务、线上 Syslog→UI 延迟或正式发布验收。原始阶段时间缺失，因此不从本次回放推导 P95/P99 实时延迟。

机器可读结果：`D:\study\NetConsole-Workspace\test-data\NetConsole\ground-syslog-real-replay-20261114\legacy_replay_summary.json`。

```text
PRODUCTION_DATA_MODIFIED=0
DATABASES_REMOVED=0/0
MAINTENANCE_AUTHORIZED=NO
```
