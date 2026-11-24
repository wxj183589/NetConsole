# Ground 工程上下文接入

库存继续来自 BaseData 当前 MR投影和formal assignment，Ground inventory 是运行缓存，不是永久归属主数据。原 source_revision 缓存继续失效；100MR/50列车夹具验证旧TTL一小时也能在关系解除后刷新。原资产保留。

list_trains 批量附加每端位 engineering_context、位置AP的position_engineering_context及状态。上下文通过唯一Query读取当前工程事实；PositionEngine/Heartbeat/Syslog/QuickPing采集和调度未改变。原位置名称、时间、freshness、历史事件原封不动；当前工程位置单列，不用当前AP归属反写历史。

上下文失败返回unavailable，读取基础候选失败时保留已保存运行库存，显式状态不冒充未关联。无自动清库、重建任务、停止采集、会话迁移或历史回填。AP只通过稳定point/identity entity ID解析，不按名字猜测。无法定位历史point时仍保留原观测，不伪造历史工程关系。

定向：engineering_context、heartbeat_inventory、position_engine、quick_ping、syslog_manual_join共62 passed（42.02s）。具体命令和后续失败隔离补测记录于Workspace Phase4 logs/ground.log。真实设备、场景漫游、长时监控NOT RUN。
