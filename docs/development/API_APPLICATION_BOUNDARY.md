# API / Application 边界

FastAPI 是 Electron Renderer 与 Python Core 之间的传输层，不是第二套业务层。当前调用链统一为：

```text
Vue / Electron
  -> FastAPI Router
  -> Application Service / Query Service
  -> Repository / Infrastructure / Device Adapter
```

## Router 职责

Router 可以负责：

- DTO、Query、上传大小和输入格式校验；
- 鉴权、Feature Gate、loopback/Desktop session 等信任边界；
- 从 `request.app.state` 获取组合根注入的 Application/Query Service；
- 调用公开用例并映射稳定响应或错误；
- WebSocket 连接、游标、心跳和事件转发；
- 在 Service 已完成路径解析、白名单和权限校验后返回 `FileResponse`。

Router 禁止：

- 直接连接 SQLite、执行 SQL 或访问 Repository；
- 直接读写、复制、压缩、解析业务文件；
- 直接连接设备或调用 SSH、Telnet、SNMP、Agent HTTP；
- 调用 Parser、计算领域规则或维护第二套 Task/Session 状态机；
- 在 Router 内构造业务 Service，或跨 Router 导入私有 helper；
- 捕获存储实现异常来表达业务语义。

## 组合根与共享契约

`src/netconsole/backend/api/main.py` 的 `create_app()` 是 API 唯一组合根。Task、Agent、Traffic、Online MR、配置采集、网络工具等 Service 由组合根创建或注入；Router 不建立第二套容器和生命周期。

存储与受控 I/O 异常通过 `src/netconsole/backend/api/error_mapping.py` 映射。Traffic 与 Network Tools 等共享响应结构使用 presentation helper，不从相邻 Router 复用私有函数。REST 响应、WebSocket 事件、任务状态和错误码属于公共契约，修改时按 Change Impact Framework 评估消费者。

## 文件与流式响应

路径解析、数据根约束、授权、白名单、文件存在性和业务所有权必须在 Application Service 中完成。Router 只能返回 Service 已核准的受控资源。用户最终文件保存还必须遵守 [用户文件交互契约](../export/USER_FILE_INTERACTION.md)；设备 SFTP 下载使用独立受管契约，不伪装成通用 Artifact。

WebSocket 和 StreamingResponse 属于允许的传输行为，但连接管理不能复制领域状态机。断线、游标、取消和终态仍由对应 Application Service、Task/Job 或领域 Service 定义。

## 验证

新增或修改 Router 时至少检查：

1. 没有 Repository、Parser、SQLite、设备连接或业务文件 I/O 旁路。
2. Service 从组合根注入，状态和错误映射保持稳定。
3. API DTO、REST/WebSocket 消费者和 Renderer 调用通过定向测试。
4. 文件响应通过 Service 白名单，用户保存入口遵守统一文件契约。
5. L3/L4 公共契约运行 [Change Impact Framework](./CHANGE_IMPACT_FRAMEWORK.md) 指定的消费者回归。

历史 Router 数量、整改波次和阶段矩阵由 Git 历史保存，不作为当前规则维护。
