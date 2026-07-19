# VRRP 语义

VRRP 状态来自检测结果中的 `vrrp` 结构，由后端映射为统一拓扑状态。页面不根据 TC1/TC2 是否存在、节点名称或地址自行推断 Master/Backup。

返回字段包括：

- `status`
- `master_side`
- `virtual_ip`
- `master_device`
- `backup_device`
- `message`
- `updated_at`

点表缺失或不完整时，VRRP 显示“未配置”；点表完整但尚未检测时显示“未检测”。只有检测结果明确返回正常或异常时，页面才显示对应状态。
