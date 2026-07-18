# Online MR 事件解析器

本目录将 Online MR 原始行/事件解析为统一事件模型，处理字段容错、时间和状态映射。解析器不连接 SSH、不写数据库、不展示页面。

主要入口为 `event_parser_engine.py`；编码和原始文本保留遵守项目规则。修改 parser 时运行脱敏 fixture、事件流和 Web 状态测试。
