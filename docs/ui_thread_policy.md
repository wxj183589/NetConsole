# UI 线程全局规范

本文是 NetConsole 全局强制工程规范，适用于所有现有模块和未来新增功能。

核心规则：

```text
UI 线程只负责 UI。
耗时任务、网络任务、数据库大任务、解析任务、导出任务，必须使用后台线程或独立进程。
所有导出类任务必须使用独立进程。
```

现有模块在维护、修复或新增功能时必须按本文整改；如果当前改动范围内发现按钮回调或页面初始化存在明显违规，应一并修复或在交付说明中列为待整改风险。

## 一、项目环境

NetConsole 当前是 Windows 桌面端网络设备采集工具，技术栈和业务形态包括：

- Python 3.13.9。
- Qt6 / PySide6。
- QFluentWidgets。
- SQLite 本地数据库。
- SSH / Telnet / SNMP / SFTP / RESTful / iperf / fping。
- MR 原始 MESH 日志、车载 MR 在线日志、配置 diff、MIB 树、Excel/CSV/PDF/图表导出。

这些任务会产生网络等待、磁盘 IO、数据库等待、CPU 密集计算或 native 扩展开销，不能阻塞 Qt UI 主线程。

## 二、UI 线程允许做什么

UI 线程只允许：

```text
创建 QWidget / QFluentWidgets 控件
更新控件状态
响应用户点击
启动后台任务
接收后台任务信号
显示进度
显示结果
显示错误
切换页面
轻量数据绑定
```

UI 线程中的数据处理必须是轻量级、可预测、不会让用户感知卡顿的操作。凡是可能超过 300ms 的任务，都应提供用户反馈；凡是可能超过 1s 的任务，必须进入后台任务模型。

## 三、UI 线程禁止做什么

以下操作禁止在 UI 线程直接执行：

```text
SSH / Telnet / Netmiko / Paramiko 连接设备
SNMP get / walk / bulk / set
RESTful API 请求
文件下载 / 上传
大文件读取
目录递归扫描
SQLite 大查询
SQLite 大量写入
数据库迁移 / VACUUM / ANALYZE
MR 原始 MESH 日志解析
车载 MR 在线日志解析
配置文件 diff
Excel / CSV / Word / PDF 导出
openpyxl / pandas / xlsxwriter 大量写入
matplotlib 大图生成 / savefig
压缩 / 解压 zip / gz
日志中心几十万记录加载
MIB 树全量加载
iperf / fping 执行和读取输出
批量设备测试连接
批量更新设备详情
AC FIT-AP 资源更新
FIT-AP 光衰更新
轨旁 AP 业务全量更新
任何 time.sleep()
任何长时间 for 循环
```

如果按钮回调、页面构造函数、`on_enter()`、Tab 切换、主题切换、刷新回调中直接执行这些操作，必须改为后台线程或独立进程。

## 四、线程和进程边界

中等耗时任务使用 QThread / Worker，详见 [后台任务规范](background_task_policy.md)。

适合 QThread / Worker 的任务：

```text
分页查询
普通数据库读取
轻量数据处理
UI 数据模型构建
短时间文件读取
页面异步加载
设备列表刷新
表格分页加载
```

重型任务必须使用独立进程，尤其是：

```text
所有导出类任务
MR 原始 MESH 大日志解析
车载 MR 收集分析强制重新解析
大 Excel 写入
图表图片批量生成
大文件压缩 / 解压
大量 pandas/openpyxl 处理
可能导致 Python GIL 卡顿的 CPU 密集任务
可能崩溃 native 扩展的 matplotlib 大图任务
```

导出类任务必须遵守 [导出进程规范](export_process_policy.md)。

## 五、QWidget 线程安全

任何 QWidget / QTableWidget / QLabel / QPushButton / FigureCanvas / QFluentWidgets 控件，只能在 UI 线程访问。

Worker 中禁止：

```python
self.table.setRowCount(...)
self.table.setItem(...)
self.label.setText(...)
self.button.setEnabled(...)
self.canvas.draw()
```

正确方式：

```python
worker.progress.emit(...)
worker.result.emit(rows)
```

然后在 UI 线程 slot 中更新控件。

## 六、数据库连接规则

数据库连接不能跨线程或跨进程共享。

必须：

```text
UI 线程、Worker 线程、导出进程各自创建自己的 SQLite 连接。
不要把 sqlite connection 对象传给线程或进程。
不要把 repository 实例跨线程复用，除非它内部明确是线程安全的。
```

导出进程和后台进程只通过 job 参数接收：

```text
database_path
site_name
filters
output_path
```

然后在自身线程或进程内打开数据库。

## 七、大表和大数据加载

所有大表必须分页、分批或懒加载。

大表包括但不限于：

```text
日志中心
MR 原始 MESH 链路明细
车载 MR 链路明细
信道繁忙度
接口速率
AP 资源大表
SNMP 查询结果
轨旁 AP 业务
```

禁止：

```python
rows = load_all()
for row in rows:
    table.setItem(...)
```

要求：

```text
默认分页
SQL LIMIT/OFFSET
后台加载
UI 批量填充
setUpdatesEnabled(False)
填充完成后再 setUpdatesEnabled(True)
不要逐行 resizeColumnsToContents
```

表格列宽、横向滚动、勾选列和 tooltip 还必须遵守 [UI 表格与全选框规范](ui_table_guidelines.md)。

## 八、网络和设备连接

任何网络设备连接都不能在 UI 线程执行，包括：

```text
SSH
Telnet
SFTP
SNMP
RESTful
iperf
fping
ping
端口探测
批量连接测试
```

批量任务必须支持：

```text
并发限制
超时
取消
进度
失败汇总
```

## 九、启动阶段

软件启动阶段只做最小初始化。

启动阶段禁止：

```text
全量扫描日志
全量扫描 MR 分析库
加载 MIB 树
加载 pandas/matplotlib/openpyxl
清理日志时阻塞启动
数据库全量迁移
VACUUM
加载日志中心全部记录
```

主窗口显示后，再后台执行：

```text
过期日志清理
缓存清理
模块延迟初始化
```

## 十、代码审查检查项

代码审查时重点搜索：

```text
button.clicked.connect(lambda: export...)
button.clicked.connect(self.export_report)
button.clicked.connect(self.parse_large_log)
button.clicked.connect(self.batch_connect)
time.sleep(
subprocess.run(
workbook.save(
df.to_excel(
pd.read_excel(
matplotlib.pyplot
netmiko.ConnectHandler
paramiko.SSHClient
pysnmp
os.walk
Path.rglob
sqlite execute 大查询
```

不是所有命中都违规，但按钮回调、页面初始化、Tab 切换、主题切换、启动流程中的命中必须重点检查。

## 十一、验收标准

新增或修改功能时必须说明：

1. 是否遵守 UI 线程只做 UI。
2. 是否存在耗时任务、网络任务、数据库大任务、解析任务、导出任务。
3. 中等耗时任务是否进入 QThread / Worker。
4. 导出和重型任务是否进入独立进程。
5. 数据库连接是否线程/进程内自建，没有跨线程共享。
6. 大表是否分页、分批或懒加载。
7. 后台任务是否有进度、失败提示、取消能力和日志。
8. 启动阶段是否避免阻塞 UI。
9. 是否影响数据库结构、导入导出模板或后台任务生命周期。
