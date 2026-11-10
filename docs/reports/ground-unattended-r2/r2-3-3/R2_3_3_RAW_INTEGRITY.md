# R2.3.3 Raw 完整性与 Parser 正确性

## Raw 完整性

本轮保持 Raw 优先：Raw Writer 成功写入和 registry 登记是压缩恢复的依据；压缩队列满只延迟 gzip，不删除原始内容。短突发结果为 `202 received / 202 written / 202 parsed / 0 dropped`，100 个 Raw 文件、202 条记录、gzip 全部可读。

Raw queue-full 专项验证了压缩队列容量 1 时仍可从关闭的 Raw registry 重新发现任务，恢复计数增长，原始行未丢失。

## Parser

测试命令及退出码见 `R2_3_3_QUEUE_BOUNDARY.md`，该定向集合 `43 passed`；另外 Renderer 相关 Ground 行为测试 `36 passed`，Electron 全量 `38 files / 306 tests passed`。

位置规则保持：

- 有效事件按事件时间处理；重复事件保留原始 Raw 和历史，但不重复切换 Current。
- 旧事件不能覆盖更新位置；不完整事件不清空已有位置。
- 未识别 AP 不强行关联，解析失败不删除 Raw。

结论：`RAW_INTEGRITY=PASS`，`PARSER_CORRECTNESS=PASS_WITH_EVIDENCE_CAVEATS`。真实 UDP 丢包、设备停机和 Backend 故障仍属于现场/故障场景，不能由 loopback 测试代替。
