# R3 Syslog Pipeline 报告

现有链路为 UDP Receiver -> Raw Writer/Spool -> Parser Queue -> Repository。Raw 文件先登记、落盘和校验，解析延迟或失败不会删除 Raw；队列容量、丢弃、压缩和解析状态已有健康字段。本轮没有改变 Syslog schema 或接收线程，避免把心跳关键路径与日志解析绑定。

需要后续补充的证据包括非法编码、磁盘写失败、Parser 崩溃重启和长时间突发输入的实际隔离测试。
