# `.ncsite` 局点包格式

`.ncsite` 是 ZIP 容器，至少包含：

```text
manifest.json
site/site_meta.json
site/db/...
site/files/...
checksums.json
README.txt
```

`manifest.json` 包含 `format`、`format_version`、应用版本、`site_id`、显示名称、时间、数据库/Artifact 摘要、SHA-256 和 `contains_credentials=false`。

导出会清洗 `devices` 表中的 password、SSH/Telnet 密码、SNMP community 和隧道密码；同时排除 Token、bootstrap、锁、缓存、临时文件和下载中的包。导入先检查 manifest、checksum、路径穿越、UNC/驱动器路径、符号链接、单文件/总解压大小和 SQLite 完整性，再写入 staging。新建导入不覆盖旧局点；替换导入必须先备份。
