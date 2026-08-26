# Legacy HistoryStore Retirement Report

## 状态

`db/history` 对本轮四类工程态已在 DEV 完成退役：Before `748,883,968` bytes，After `0` bytes；事件行 Before `1,319,693`，After `0`。生产目录没有读取、写入、复制、删除或迁移。

## 防再生

- `HistoryStore.record_event()` 在 `engineering_history_authority=retired` 时返回 `False`，不创建 outbox 或历史 shard。
- DEV 9 个迁移目标 marker 均为 `retired`。
- Trackside page/export 不调用资源历史、AP 光衰历史、AP LLDP 历史或设备光模块历史的全量读取；导出使用 Current snapshot，且释放数据库读取后再渲染 XLSX。
- 真实 DEV 两局点在 monkeypatch 拦截 Legacy HistoryStore/query_events/count_events 后，页面和导出均完整返回：PASS。

## 未做的事

MESH/MR raw、Syslog、PCAP、导入文件、MESH catalog/parsed DB 和未认证/站点在线摘要等 own history 没有被强行归入四类，也没有删除。它们已在 `ENGINEERING_STATE_STORAGE_AUDIT.md` 中分类，后续需单独决定，不在本提交现场扩展范围。
