# WMESH 事件与 scheduler_events 对照

## 对照结果

归档的 `scheduler_events.jsonl` 是有界调度投影，不是全部原始 WMESH 的绝对真值。使用 `global_receive_sequence` 对齐 497 条旧 WMESH 投影与 39,827 条当前 Parser WMESH 结果：

| 分类 | 数量 | 解释 |
|---|---:|---|
| MATCH | 496 | 事件类型、MR、AP 身份和时间在允许窗口内一致 |
| DUPLICATE_EVENT | 1 | 当前去重/位置引擎识别重复语义 |
| OLD_ONLY | 0 | 没有旧投影无法在原始事件中找到的记录 |
| NEW_ONLY | 39,330 | 原始 WMESH 相对有界 scheduler 投影的新增观察，不作为缺陷 |
| 其他类型差异 | 0 | 未见事件类型、MR 映射、AP 映射或时间差异分类 |

`NEW_ONLY` 的数量差来自投影范围：scheduler 只保留调度关注窗口/事件，而 raw Syslog 保存完整 WMESH 流。当前结果支持“旧投影可由原始证据回放”，不支持把旧投影当作完整历史。

