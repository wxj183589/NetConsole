# 站点模板 fixture 指纹测试调查

- 最终状态：`LOCAL_PASS_DATABASE_VERIFIED`
- 目标测试：`tests/test_rail_transit_base_data_web_api.py::test_station_template_download_preview_and_export_are_structured_xlsx`
- 测试文件 SHA-256：`f5d982605b1275542d6c83506be806faa5f23188ff1db48917742475456c66f1`
- Fixture helper：`tests/support/rail_transit_base_data_fixture.py`
- Fixture helper SHA-256：`8ddce4a50f34ba7aff3b71f11b402aff00a204b6c21b6e3da6408358894dc6e9`

## 失败位置

- `_fingerprint()` 位于测试文件第33行，返回 `(sha256(path.read_bytes()), path.stat().st_mtime_ns)`。
- 目标测试定义于第672行。
- 历史失败断言位于第708行：`assert _fingerprint(db_path) == before`。
- 工作区没有保存该次失败的完整 pytest traceback；上一轮交接只保留了“fixture 数据库 fingerprint 变化”的结果描述。

该测试使用 pytest `tmp_path` 生成临时数据库，不读取杭州地铁9号线真实数据库，也不存在一个需要核对的静态 `.db` fixture 文件。helper 在初始化后显式执行 `PRAGMA wal_checkpoint(TRUNCATE)`（第54行），因此其预期是用稳定的主文件指纹判断预览只读。

## 当前复现

严格只运行目标测试：

```text
1 passed, 1 warning in 4.45s
```

随后连续运行同一测试3次：

```text
RUN 1: 1 passed, 1 warning
RUN 2: 1 passed, 1 warning
RUN 3: 1 passed, 1 warning
```

因此该失败在当前 HEAD 上不可复现。没有证据证明模板内容、换行符、Excel 元数据、版本或路径差异是原因。最小可信结论是：上一轮是一次生成 fixture 数据库指纹变化的瞬态/环境敏感失败，具体触发条件因没有原始 traceback、before/after 两个指纹值而无法进一步归因。

## 影响范围

- 不影响正式站点管理功能：目标测试当前通过，且它使用独立 `tmp_path` fixture。
- 不影响轨旁 AP 导入导出：本轮17条 AP 直接相关测试全部通过；轨旁 AP 使用的真实 `hzdt-09` 数据库也独立完成了只读统计。
- 未修改产品代码、测试断言、fixture 阈值或测试跳过规则。
