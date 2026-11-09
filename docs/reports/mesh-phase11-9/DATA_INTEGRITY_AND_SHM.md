# 真实数据完整性与 SQLite SHM 证据

日期：2026-11-10  
Authority：只读 `D:\NetConsoleData-dev`，站点“宁波地铁12号线”。

本轮真实查询前后内容证据：

| 文件 | Size | SHA256 | mtime 结论 |
|---|---:|---|---|
| `catalog.sqlite` | 110592 | `48b64eabb5047bea2a0aac932c6a26068fd03d13c65c1683f14d4d4fd009ccfd` | 未变 |
| `列车03-MR-CW\mesh.sqlite` | 249856 | `b89146547fa0577fd2643660347de942b2aef7493736e1f586a0b94225e73cb0` | 未变 |
| parsed 主 DB | 158621696 | `27efefb951be073e9f43d22c8bbd583ca7a86ded225f8a8ad9d7a5e2551524fc` | 未变 |
| parsed `-wal` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 未变 |
| parsed `-shm` | 32768 | `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb` | 内容 SHA 未变；mtime 从约 `2026-11-09T18:05:37Z` 漂移到 `2026-11-09T19:20:14.3223749Z` |
| raw `.log.gz` | 2953314 | `282e2166cc7abf15a8e20794db7a5f83174768fabe807ae2b74da3c639a3d2bc` | 未变 |

主 DB、catalog、WAL、raw gzip 的 size/SHA 均保持一致；parsed SHM 的内容 SHA 保持一致，但 mtime 发生漂移。这个现象被保留为 SQLite 只读访问期间的文件系统元数据风险证据：本轮可以声称“内容级未发现变化”，不能声称“所有文件元数据零变化”或“任何 runtime 写入绝对不可能”。

本轮没有执行迁移、VACUUM、导入、删除、更新、设备命令或 Production 访问；临时 raw JSON、隔离 Electron root 已退役。
