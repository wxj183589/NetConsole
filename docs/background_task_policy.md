# 后台任务规范

本文定义 NetConsole 后台线程和后台任务的统一约束，是 [UI 线程全局规范](ui_thread_policy.md) 的配套文档。

核心规则：

```text
Worker 不操作 QWidget。
Worker 通过 signal 返回 progress / result / error。
UI 线程只接收 signal 并更新界面。
```

## 一、适用范围

适合使用 QThread / Worker 的任务：

```text
分页查询
普通数据库读取
轻量数据处理
UI 数据模型构建
短时间文件读取
页面异步加载
设备列表刷新
表格分页加载
普通设备状态刷新
```

不适合只用 QThread 的任务：

```text
所有导出类任务
大日志解析
大 Excel 写入
批量图表生成
大文件压缩 / 解压
大量 pandas/openpyxl 处理
CPU 密集任务
可能崩溃 native 扩展的任务
```

这些任务必须使用独立进程，详见 [导出进程规范](export_process_policy.md)。

## 二、标准信号

所有后台任务必须提供以下信号或等价机制：

```text
started
progress(stage, current, total, message)
finished(result)
failed(error_message, traceback)
cancelled
```

UI 必须显示：

```text
当前阶段
进度条或阶段提示
取消按钮（任务支持时）
完成状态
失败提示
```

禁止后台任务无提示运行，导致用户以为软件卡死。

## 三、Worker 规则

必须：

- Worker 只处理业务逻辑、IO、数据库读取、数据转换。
- Worker 中创建自己的数据库连接、服务实例和临时状态。
- Worker 通过 signal 发送进度、结果、错误和取消状态。
- Worker 支持取消时，必须定期检查取消标志。
- Worker 异常必须发送 `failed(error_message, traceback)`，不得静默吞掉。

禁止：

- Worker 访问 QWidget、QTableWidget、QLabel、QPushButton、FigureCanvas 或 QFluentWidgets 控件。
- Worker 复用 UI 线程创建的 SQLite connection。
- Worker 复用未声明线程安全的 repository 实例。
- Worker 直接弹 QMessageBox。
- Worker 中使用 `time.sleep()` 模拟等待 UI。

## 四、UI 线程 slot 规则

UI 线程 slot 负责：

```text
启用/禁用按钮
更新进度条
更新状态标签
填充表格
显示错误
显示完成提示
清理 worker 引用
```

必须：

- 任务开始后禁用会重复启动同一任务的按钮。
- 任务完成、失败或取消后恢复按钮状态。
- 页面关闭、局点切换或应用退出时停止或解绑后台任务。
- 避免旧任务结果覆盖当前页面状态。

禁止：

- 在 slot 中继续执行大查询、大解析、大导出。
- 在 slot 中逐行执行昂贵布局刷新。
- 因页面切换导致后台采集、检测、导出状态丢失。

## 五、批量任务

批量任务必须支持：

```text
并发限制
超时
取消
进度
失败汇总
部分成功
日志记录
```

适用场景：

```text
批量设备连接测试
批量配置采集
批量文件下载 / 上传
批量 SNMP 查询
批量 AC / FIT-AP 更新
批量轨旁 AP 业务更新
```

禁止一个设备失败后无条件中断整个批量任务；应记录错误并继续可继续的任务，除非该失败会破坏全局一致性。

## 六、统一管理器

推荐新增或复用统一后台任务管理器：

```python
BackgroundTaskManager
```

能力：

```text
启动任务
取消任务
显示进度
防止重复启动
任务完成回调
任务失败回调
日志记录
页面关闭时解绑或停止任务
应用退出时统一清理
```

所有页面尽量复用统一管理器，不要每个页面单独写一套线程生命周期逻辑。

## 七、日志要求

所有后台任务必须写日志中心事件：

```text
TASK_STARTED
TASK_PROGRESS
TASK_COMPLETED
TASK_FAILED
TASK_CANCELLED
```

具体业务可增加：

```text
MESH_PARSE_STARTED
TRACKSIDE_AP_FULL_UPDATE_STARTED
DEVICE_BATCH_TEST_STARTED
SNMP_COLLECT_STARTED
```

日志详情必须包含：

```text
任务类型
耗时
处理数量
失败数量
错误摘要
```

## 八、用户体验

凡是耗时超过 300ms 的任务，都应该给用户反馈。

凡是耗时超过 1s 的任务，必须显示：

```text
加载中 / 执行中
进度或阶段
取消按钮（可行时）
```

禁止软件界面无响应或按钮无反馈。

## 九、交付说明

涉及后台任务的改动，交付时必须说明：

1. 使用 QThread / Worker 还是独立进程。
2. Worker 是否访问 QWidget。
3. 数据库连接是否在线程内创建。
4. 是否支持取消、失败提示、进度和日志。
5. 页面关闭、局点切换、应用退出时如何清理任务。
6. 是否可能有旧任务结果覆盖当前页面状态。
