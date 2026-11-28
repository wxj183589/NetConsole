# Phase 5.1 开源参考审计

沿用已固定的[开源对标源码与许可证](OPEN_SOURCE_REFERENCE_MATRIX.md)。链接内的 40 位哈希标识参考版本。本轮七项全部属于设计或架构参考，未引入其代码、图标或运行时依赖，无新增分发许可证义务。

| 项目 | 顶层许可证 | 实际参考与现有产品位置 | 固定提交源码及许可证 |
| --- | --- | --- | --- |
| netbox | Apache-2.0 | 设备详情模板与接口分区组织同一设备。复用档案页 UUID 与标签页，连接台账只保留基础编辑。 | [源码](https://github.com/netbox-community/netbox/blob/04bdbf464c380d2b4d1dc8d4f9c96fcc26f04981/netbox/templates/dcim/device.html) · [许可证](https://github.com/netbox-community/netbox/blob/04bdbf464c380d2b4d1dc8d4f9c96fcc26f04981/LICENSE.txt) |
| nautobot | Apache-2.0 | 任务表单折叠高级字段并区分任务与调度校验。将高级调度按需展开，复用本机任务模板、权限、日志和 Artifact。 | [源码](https://github.com/nautobot/nautobot/blob/115cb277e0e751ca559b3d22d15b3682ce0fccf9/nautobot/extras/templates/extras/htmx/job_form_modal.html) · [许可证](https://github.com/nautobot/nautobot/blob/115cb277e0e751ca559b3d22d15b3682ce0fccf9/LICENSE.txt) |
| netdisco | BSD-3-Clause | 端口表按自然端口序排列，分组折叠并链接节点。适合档案接口、LLDP 子表；保持既有采集契约。 | [源码](https://github.com/netdisco/netdisco/blob/562642bebb5c1013ba12f61a2560811fa5f6e71b/share/views/ajax/device/ports.tt) · [许可证](https://github.com/netdisco/netdisco/blob/562642bebb5c1013ba12f61a2560811fa5f6e71b/LICENSE.md) |
| librenms | GPLv3，含第三方例外 | Dashboard Widget 控制器校验类型及维护用户部件。首页采用当前局点计数和真实任务记录，统一卡片状态，维持固定布局。 | [源码](https://github.com/librenms/librenms/blob/bef435528ad76629f1db763b15fed701bf409f43/app/Http/Controllers/DashboardWidgetController.php) · [许可证](https://github.com/librenms/librenms/blob/bef435528ad76629f1db763b15fed701bf409f43/LICENSE.txt) |
| oxidized | Apache-2.0 | Git 输出按设备路径限定两个版本的 diff 并提供增删统计。配置中心继续显示现有快照与差异，共用本机快照 ID。 | [源码](https://github.com/ytti/oxidized/blob/9ca3bc45322db62270038e2f821373da28bf2f2c/lib/oxidized/output/git.rb) · [许可证](https://github.com/ytti/oxidized/blob/9ca3bc45322db62270038e2f821373da28bf2f2c/LICENSE) |
| tabby | MIT | 标签独立呈现活动与当前态，并支持可选的会话图标。控制台把低频动作收进菜单，继续使用 Vue、原终端组件与窗口契约。 | [源码](https://github.com/Eugeny/tabby/blob/dc72f059410a5dd51bfd9ca40242abc9d04579ec/tabby-core/src/components/tabHeader.component.pug) · [许可证](https://github.com/Eugeny/tabby/blob/dc72f059410a5dd51bfd9ca40242abc9d04579ec/LICENSE) |
| winscp | GPLv3，图标另有条款 | Commander 窗体支持双栏分隔、各侧目录和排序。受管文件突出当前位置与只读，沿用受管引用、权限和传输队列。 | [源码](https://github.com/winscp/winscp/blob/ae30304af38792b378243e52183aad597a34c5b9/source/forms/ScpCommander.dfm) · [许可证](https://github.com/winscp/winscp/blob/ae30304af38792b378243e52183aad597a34c5b9/license.txt) |
