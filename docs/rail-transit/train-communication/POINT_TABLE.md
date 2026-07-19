# 检测点表

## 数据来源

历史 Qt 点表和检测流程通过 Git 历史审计确认，事实源文件包括：

- `src/netconsole/ui/pages/car_network_diagnostic_page.py`
- `src/netconsole/ui/car_network_diagnostic_worker.py`

当前实现不恢复 Qt UI，而是将点表读取、校验和 revision 保护收敛到 `TrainCommunicationPointTableService`。运行数据位于局点数据根的：

```text
files/rail_transit/car_network/parsed/point_table.json
```

## 必需节点

每列车必须包含且只能包含以下六个节点：

```text
TC1-MR  TC1-SW  TC1-SRV
TC2-MR  TC2-SW  TC2-SRV
```

节点必须能通过设备 ID 或地址字段定位检查端点。服务器允许只有 IP/SSH 地址而没有 `device_id`；这种节点是“已配置、未检测”，不是“未配置”。

## 校验状态

| 状态 | 含义 |
| --- | --- |
| `configured` | 六个节点存在且每个节点有设备或地址 |
| `missing` | 文件不存在，或当前列车没有对应点表行 |
| `invalid` | 节点缺失、重复、或节点没有可用设备/地址 |

点表保存使用 SHA-256 revision。客户端提交读取时的 revision，后端发现 revision 变化时返回 `TRAIN_COMMUNICATION_REVISION_CONFLICT`，不会覆盖其他修改。

## 维护入口

正式页面右上角的“点表管理”打开现有点表弹窗，支持查看、编辑、锁定、导入预览、生成预览和导出。保存和导出仍进入 Task Center；页面不建立第二套点表数据库或任务模型。
