# Job Center 页面

本目录展示后台 Job 列表、详情、事件日志和取消状态。任务执行仍由 Python Job Center/Worker 负责，页面不得阻塞等待长任务或直接启动进程。

主要入口为 `JobCenterView.vue`；数据通过 Task API 获取。修改状态、游标或取消交互时运行页面测试并检查 Job 契约。
