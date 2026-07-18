# H3C 适配器

本目录封装 H3C/Comware 命令 profile、接口、LLDP、光模块和通用回显适配。它负责把设备文本转成稳定的领域结构，不直接写数据库或渲染页面。

主要入口为 `h3c_parser.py`、`h3c_interface_parser.py`、`h3c_lldp_parser.py` 和 `h3c_optical_parser.py`。使用相关 parser/设备测试验证 UTF-8/GB18030 回显兼容。
