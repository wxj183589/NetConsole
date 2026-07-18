# 功能特性配置

本目录提供 `customer.json`、`full.json` 等脱敏 Feature profile，供启动/构建配置选择默认能力。文件只包含功能开关和允许的配置字段。

修改后需核对 `src/netconsole/core/feature_registry.py` 的 key 与默认值，并运行相关 Python/Web 测试；不要把真实局点配置复制到这里。
