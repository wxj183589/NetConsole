# H3C AC/FIT-AP 解析器

本目录解析 AC 上 FIT-AP、射频、邻居、光模块和未认证 AP 等命令回显，输出 AC/FIT-AP 查询与身份 shadow 使用的结构。

主要入口为 `wlan_ap*`、`fit_ap_*` 和 `state_mapper.py`；字段变化要同步 AC Service、Repository 和 API。使用脱敏 H3C fixture 运行定向 parser/AC 测试。
