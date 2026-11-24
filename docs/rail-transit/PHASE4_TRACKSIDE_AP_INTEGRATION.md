# 轨旁 AP 工程上下文

现有共同快照构建层按switch UUID附加switch_engineering_context，按AP Identity entity ID唯一命中工程点位附加point_engineering_context。两者独立，不用交换机站点充当AP物理归属。未确认/歧义Identity不按名字或MAC相似补全，LLDP继续只是运行发现。

页面DTO读取同一快照字段；现有XLSX流程新增工程线路/建设项目/工程区间/上下文状态四列，来自冻结行，未新建导出入口。外层source_revisions包含base_data_revision，关系变更使页面/导出旧revision失效。嵌套上下文查询时间使用外层snapshot_created_at，避免同事实revision的内容哈希因查询时间漂移。非标准独立数据库夹具无法证明Site根时上下文unavailable，不选择其他根。

不改采集Profile、光衰门限、端口事实、Identity重建或历史光衰；原规划/物理身份/Current/观测分层保留。快照/导出专项48 passed（12.09s），日志见Workspace Phase4 logs/trackside.log。实际页面展示和Electron另在Phase4.6验收。

交换机安装位置、项目和区间在独立上下文中显示。导出工程项目/区间优先采用可确认的点位上下文，缺少时使用明确的交换机工程服务范围；状态同时保留 `switch=...;point=...`，不会把未确认的 AP 写成已关联。非空端口回归验证正式站点 ID、安装位置和快照输出；目录合并保留正式 station ID，异站点写入仍受原冲突保护。
