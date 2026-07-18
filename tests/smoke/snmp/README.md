# 设备管理 SNMP v1/v2c 真实设备烟测

该目录只提供手工启用的真实设备烟测框架，普通 pytest 不连接设备。

1. 复制 `smoke_devices.example.yaml` 到工作区外的私有文件。
2. 填写测试设备地址和 v1/v2c 只读参数；团体字通过环境变量提供，不写入 YAML。
3. 设置 `NETCONSOLE_SNMP_SMOKE_CONFIG` 为私有 YAML 的绝对路径。
4. 运行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\smoke\snmp
```

烟测只调用固定基础识别流程；配置文件不能传入 OID 或操作类型，不提供 SNMPv3、SET、通用 OID 查询或批量采集。
