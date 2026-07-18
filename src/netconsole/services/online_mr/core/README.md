# Online MR 核心模型

本目录定义在线 MR 实时事件、状态、缓存和解析模型，供采集、查询和 Web 控制共享。它不负责 SSH 连接、Job 调度或数据库提交。

主要入口为 `event_model.py`、`realtime_model.py`、`realtime_parser.py` 和缓存模块。修改事件字段、窗口或时间语义时运行 Online MR parser/realtime 测试。
