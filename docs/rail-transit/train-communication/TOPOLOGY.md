# 固定拓扑

```text
TC1-MR -> TC1-SW -> TC1-SRV
              |
           VRRP / 跨 TC
              |
TC2-MR -> TC2-SW -> TC2-SRV
```

拓扑节点从点表映射到设备名称、设备 ID 和地址。页面不根据节点名称猜测设备，也不把“有设备管理 IP”当作点表配置完成。

节点状态由后端返回：

| 状态 | 含义 |
| --- | --- |
| `not_configured` | 点表缺失、节点缺失或没有可用端点 |
| `not_detected` | 点表完整，但还没有最近检测结果 |
| `checking` | 检测任务运行中 |
| `normal` | 最近检测通过 |
| `abnormal` | 最近检测失败或异常 |
| `stale` | 最近结果超过有效期 |

点表缺失或不完整时，VRRP 和跨 TC 状态统一返回 `not_configured`。点表完整但尚未执行检测时，才返回 `not_detected`。
