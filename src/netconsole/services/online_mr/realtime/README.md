# Online MR 实时缓冲

本目录实现实时滑动窗口、会话适配和事件协作所需的轻量缓存结构，供在线图表和诊断查询使用。它不持久化正式结果，也不启动采集进程。

主要入口为 `sliding_window_buffer.py`；窗口大小、丢弃和排序语义应可测试。修改后运行 Online MR realtime、Web preview 和状态测试。
