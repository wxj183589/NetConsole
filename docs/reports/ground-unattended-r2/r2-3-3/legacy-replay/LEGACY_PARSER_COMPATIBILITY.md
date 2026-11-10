# 原版归档格式兼容性

## 已验证格式

- ZIP：CRC、SHA-256、manifest 成员 SHA 均通过。
- UTF-8 JSON / JSONL / NDJSON：0 解码错误、0 JSON 解析错误。
- GZIP NDJSON：145 个普通/GZIP 成对文件内容一致；未把 GZIP 与普通文件重复计入业务记录。
- JSON 数组/对象：`daily_by_mr.json`、`daily_by_train.json` 可读取。
- CSV：可读取，未发现编码错误。
- H3C Syslog：当前 Parser 识别 WMESH LinkUp、LinkDown、Active-Link Switch，以及 CFGMAN/IFNET 控制事件。

## Parser 分类

| 分类 | 数量 |
|---|---:|
| WMESH | 39,827 |
| CFGMAN | 262 |
| IFNET | 31 |
| 非业务未解析 | 170 |

170 条未解析行全部有非 WMESH 标记（SYSLOG_RESTART、SHELL_CMD、SHELL_CMD_EXECUTESUCCESS、IFNET/5/LINK_UPDOWN），不属于 WMESH Parser 漏解析。归档中的 `parse_status=PENDING` 是归档采集状态，不能直接解释为当前 Parser 失败；当前 Parser 已完成上述业务分类。

