# 终端规则资源

控制台高危命令和关键字高亮规则的只读资源。

这两份 JSON 是设置页的默认规则和导入示例。冻结 Backend 使用
`netconsole/resources/terminal_rules/` 作为默认规则位置，DataRoot 中的
`config/terminal/` 保存用户规则。

规则文件接受 `schema_version: 1` 的带 `rules` 文档和历史裸规则数组。
支持 UTF-8（含 BOM）、UTF-16（含 BOM）和 GB18030。设置页导入后先显示有效规则，
保存后才替换对应配置，损坏配置的原字节会保存在同目录的 `*.invalid-*.json`。
