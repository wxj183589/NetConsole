# Web 类型契约

本目录保存 API、Store、组件和视图共享的 TypeScript 类型，按业务域映射后端 DTO。类型文件不应包含网络、副作用或业务计算。

主要入口为各域 `*.ts`；字段改动要与 FastAPI DTO、API 客户端和测试一起核对。保持可空性、枚举和时间格式与服务端一致。

## 设备详情类型

`deviceManagement.ts` 映射 Python `src/netconsole/models/api/device_detail.py` 中的 overview、platform facts、capability、command profile、接口、光模块、LLDP、配置快照、任务、关联业务、历史和刷新任务 DTO。设备详情不定义独立 Health DTO，CPU/内存只属于 overview 基础摘要。前端类型只表达传输契约，不推断：

- 厂商、软件版本或设备角色；
- capability 与可见页签；
- Command Profile 是否可执行；
- 光功率、温度等阈值和告警；
- FIT-AP、轨旁 AP 或 Online MR 的业务关联。

上述事实全部由 Python DTO 返回。可选或未知数据保持 `null`/可选字段，展示层统一显示“—”；数值 `0`、布尔 `false` 和空分页不能被误当作缺失值。不得把密码、community、Token、服务端绝对路径或未列入 DTO 的任意对象扩展进共享类型。

LLDP 公开类型不包含邻居 `capabilities`、`model`；只映射本地接口、归一化本地接口、邻居系统名/MAC/接口/IP、关联设备 UUID、关联状态和采集时间。底层历史表是否仍有同名旧字段不改变前端白名单。设备 overview 的 `model`、光模块的 `module_model` 和 FIT-AP 业务对象的 `model` 是不同契约，不得连带删除。

接口公开类型不包含入/出速率、入/出错误、CRC 错误、错误总数或最后变化；光模块公开类型不包含采集 `status` 或内部阈值来源。底层 Repository/数据库兼容字段不因此删除。光模块严重性原因兼容精确中文展示，接收功率颜色只消费后端 `severity`，不得在 TypeScript 中按数值重算阈值。

修改设备详情字段时必须同时核对 [API DTO 模型](../../../../src/netconsole/models/api/README.md)、[Web API 客户端](../api/README.md)和[设备详情组件](../components/device-detail/README.md)。当前低 CPU 限制下优先运行受影响的类型/API/组件定向测试；全量验证和生产构建延后到用户解除限制后。
