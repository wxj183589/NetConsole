# VRRP 静态配置语义

当前车内通信诊断没有执行 VRRP 协议状态或主备角色检测。点表中的 `vrrp_ip` 是有效静态配置，拓扑卡片只在该值存在时展示“虚拟 IP：xxx”；没有值时只显示标题“VRRP”，不显示占位文字。

`TrainCommunicationVrrpDTO` 为兼容既有 API 暂时保留以下字段：

- `status`
- `master_side`
- `virtual_ip`
- `master_device`
- `backup_device`
- `message`
- `updated_at`

除 `virtual_ip` 外，其余字段没有正式检测来源，不参与当前拓扑 UI、颜色、动画或诊断结论。后端兼容结果不得根据节点状态、服务器或交换机 Ping、跨 TC Ping 推断 VRRP 正常、异常或 Master/Backup。
