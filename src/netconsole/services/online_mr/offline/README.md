# Online MR 离线回放

本目录提供 Online MR 原始事件的离线 replay engine，用于复现实时状态和诊断逻辑。它不执行设备连接、不修改原始日志，也不替代 MESH 离线分析。

主要入口为 `replay_engine.py`；输入来自脱敏会话目录，输出应位于测试临时目录或运行数据根。修改回放顺序、时间或状态时运行 Online MR 测试。
