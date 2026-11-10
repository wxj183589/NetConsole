# Data Integrity Report

## Authority 与运行路径

- Production：`D:\NetConsoleData`，未用于普通破坏性测试。
- Dev Authority：`D:\NetConsoleData-dev`，运行时未作为 backend data root。
- Runtime snapshot：`D:\study\NetConsole-Workspace\test-data\NetConsole\mesh-phase11-8-run-001`。
- 运行过程没有复制整站或整库；只读使用既有隔离快照。

## 目标文件指纹

主目标会话文件前后 size/SHA 相同：

- `.../列车01-MR-CW/mesh.sqlite`：249,856 bytes，SHA `7d45597929601c48848ba65471f0270eaca5489cd6cd662b2af74d45cdd3a191`。
- `.../列车01-MR-CW/parsed/列车01-MR-CW-2026_10_20_2meshlog.mesh.sqlite`：156,786,688 bytes，SHA `2630d9cf03cd5ac3146e11d449db5964dd8e7dd97666136d56eb09aa40b77271`。
- raw gzip：2,892,510 bytes，SHA `f53990d5448f297ea8cbc6901d87132fcf3f616c61149feaa4e875829a3b0fc7`。
- 目标 `mesh.sqlite-shm` 为 32,768 bytes，SHA 前后相同；没有删除 SHM，也没有恢复 mtime。

## 发现的副作用

隔离快照的 `mr_raw_mesh/catalog.sqlite` size 保持 110,592 bytes，但 SHA 从
`a3bcdf09cd569577965faaf484ce40eac50fc52f978bd6c4de70547b5f22f60d`
变为
`2439055a500142296ff4904eaaae11f26f2259437a13c8a8ebf245a56deff0e9`。

这表示真实运行更新了快照 catalog/index metadata；没有把该变更恢复或覆盖到 Dev Authority。source-root 对照中 scoped target 文件 SHA/size 未发生变化。

## mtime 边界

本次 Node probe 没有以 bigint 方式读取 `mtime_ns`，证据 JSON 中该字段为 `null`。因此不能宣称 mtime 未变；该项为 `UNATTRIBUTED/UNRECORDED`。按要求没有恢复 mtime、删除 SHM 或回写 Production/Dev 数据。

## 结论

输入 raw/parsed/target session 数据内容未变，隔离 catalog 有可见 metadata 变更，文件时间证据不完整；数据完整性 gate 为 `PARTIAL`。

