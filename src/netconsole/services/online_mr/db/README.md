# Online MR 数据库写入

本目录把在线 MR 事件和会话结果安全写入局点任务/会话数据库，处理 writer 与持久化边界。数据库连接由调用方按线程/进程创建，不能跨线程共享。

主要入口为 `event_db_writer.py` 与 `event_writer.py`；原始会话路径由 collection paths 管理。修改 schema、批量写入或恢复时运行 Online MR session/database 测试。
