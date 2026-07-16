# 设备管理

设备管理以现有设备主库为唯一持久化事实源。Electron 正式桌面入口通过共享 Python Application Service 和 FastAPI 使用同一 Repository；Qt 在迁移验收完成前继续作为事实源与回退入口，不维护第二套设备业务逻辑或数据库。

当前真实能力包括：

- 搜索、厂商/类型/分组/连接状态筛选、排序、分页和当前页多选；
- 新增、编辑、复制、单删/批删、设备分组，以及凭据保持/替换/显式清除三态；
- 已保存设备的 SSH/Telnet/SNMP 连接测试；未保存表单测试入口等待共享 Job Runtime 非序列化 bootstrap；
- 详情、接口、光模块、LLDP、轨旁 AP 业务、历史分页和批量详情采集；
- CSV 上传预览、错误/重复策略、确认、单事务导入和审计；
- CSV（含/不含凭据）、导入模板、SecureCRT 会话、OmniPeek 名称表和诊断 ZIP Artifact；
- SecureCRT、Xshell、PuTTY 白名单配置与受控启动。

秘密字段不会由详情或写入响应回显。未保存表单测试已删除回环 token/端口方案；当前 Feature 默认关闭，服务端在共享 Job Runtime 未提供 `runtime_bootstrap` 时拒绝创建 Task。模块侧契约要求凭据只经受控 stdin/匿名管道进入 worker，单次读取后清零，Task 参数、磁盘 Job JSON、Task DTO/事件/日志和数据库均不得保存秘密。导出和诊断文件先在受控目录生成并记录 SHA-256/大小，再由 Electron 受管下载选择保存位置；只有 Native Bridge 为本次桌面会话返回的 `capabilityId` 可用于打开或定位目录。

完整 Qt 事实源、入口矩阵、自动化证据、共享任务窗口依赖和人工/真实设备边界见 `docs/development/parity/device-management.md`。
