# UI 表格与全选框规范

本文档是 NetConsole 全局 UI 表格规范。所有新建或修改的表格类界面必须遵守本文档，包括设备管理、AC 管理、FIT-AP 资源、任务中心、配置采集中心、文件管理以及未来新增页面。

## 1. 全选框 / 勾选列规范

所有表格中的批量选择列必须使用统一的 `CheckBoxOnlyDelegate`。

禁止在表格单元格中直接使用 `QCheckBox` cellWidget。

正确方式：

- 使用 `QTableWidgetItem`。
- 使用 `Qt.ItemDataRole.CheckStateRole` 保存勾选状态。
- 使用 `CheckBoxOnlyDelegate` 绘制 checkbox。
- checkbox 必须居中显示。
- 不绘制文字区域。
- 不绘制 focus rectangle。
- 不显示 checkbox 右侧多余小方框。

禁止写法：

```python
table.setCellWidget(row, 0, QCheckBox())
```

禁止同一单元格同时使用：

- `QTableWidgetItem.setCheckState(...)`
- `setCellWidget(..., QCheckBox)`

推荐写法：

```python
from netconsole.ui.widgets.table_check_delegate import (
    create_checkable_table_item,
    install_checkbox_only_delegate,
)

install_checkbox_only_delegate(table, 0)

item = create_checkable_table_item(False)
table.setItem(row, 0, item)
```

## 2. 全选 / 反选 / 清空选择规范

全选、反选、清空选择不能只维护内部 `selected_ids` 集合，必须同步更新表格第一列的 `CheckStateRole`。

点击全选后，用户必须能立即看到 checkbox 已勾选。

点击清空选择后，用户必须能立即看到 checkbox 已取消。

点击反选后，显示状态必须和内部选择状态一致。

推荐调用统一工具函数：

```python
from netconsole.ui.widgets.table_check_delegate import (
    invert_table_rows_checked,
    is_table_row_checked,
    set_all_table_rows_checked,
)

set_all_table_rows_checked(table, True)
invert_table_rows_checked(table)
```

## 3. 表格列宽规范

所有表格必须优先保证内容可读，不允许为了塞进窗口而强行压缩字段。

表格列宽必须根据表头和内容自动初始化。

按内容自动列宽不能无限放大超长文本列。错误信息、路径、备注、描述、命令输出等长文本列必须设置合理最大宽度；超过列宽时使用省略号显示，完整内容通过 tooltip、复制单元格或详情弹窗查看。

如果总列宽超过当前界面宽度，必须显示横向滚动条。

用户必须可以手动拖动调整列宽。

禁止：

- 禁止默认使用 `QHeaderView.Stretch` 强行压缩所有列。
- 禁止为了适配窗口宽度隐藏用户需要看的列。
- 禁止让操作列按钮被遮挡。
- 禁止让字段压缩到不可读。
- 禁止让单个超长文本列覆盖其他列或导致核心字段不可读。

推荐写法：

```python
from netconsole.ui.table_utils import setup_readable_table

setup_readable_table(
    table,
    horizontal_scroll=True,
    interactive=True,
    stretch_last_section=False,
)
```

已有表格在填充数据后需要按内容初始化列宽时，推荐使用：

```python
from netconsole.ui.table_utils import auto_resize_table_columns_to_contents

auto_resize_table_columns_to_contents(table)
```

## 4. 横向滚动条规范

当表格总宽度超过可视区域时，应使用横向滚动条查看完整内容。

不要把所有列强制压缩到当前窗口宽度。

推荐设置：

```python
table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
```

## 5. 用户手动调整列宽规范

表格可以在首次加载、刷新、导入后执行一次自动列宽初始化。

但用户手动拖动列宽后，不应在单击、勾选、右键、滚动等普通操作中反复覆盖用户设置。

允许自动调整的时机：

- 表格首次加载。
- 点击刷新后整表重载。
- 导入数据后整表重载。
- 切换局点后整表重载。

不允许频繁自动调整的时机：

- 单击单元格。
- 勾选 checkbox。
- 右键菜单。
- 滚动表格。
- 普通行选择变化。

## 6. 操作列规范

如果表格中存在“详情 / 外部终端 / 删除 / 打开目录”等按钮，操作列必须给足宽度，不允许按钮被遮挡。

操作列可以设置固定最小宽度，例如 180px、220px 或根据按钮数量计算。

## 7. 长文本 Tooltip 规范

对于路径、错误信息、备注、命令输出摘要等长文本字段，单元格应设置 tooltip，便于用户悬停查看完整内容。

即使用户手动缩小列宽，也应能通过 tooltip 查看完整内容。

长文本列必须使用 `Qt.TextElideMode.ElideRight` 或等价省略号显示策略。禁止把全局表格默认设置为 `ElideNone`，避免超长文本绘制越界或挤压其他列。

长文本列建议最大宽度不超过 520px；特殊详情表可按场景放宽，但必须保证设备名称、地址、状态、耗时等核心字段稳定可读。

推荐写法：

```python
item.setToolTip(str(value))
```

## 8. 字段显示规范

主列表只显示当前页面最常用的核心字段。

诊断字段、内部字段、原始字段、历史字段不应默认塞进主列表。

需要排查时，应放入详情页、调试页、全部字段页或高级导出。

FIT-AP 资源主列表默认不显示：

- SN
- Radio3
- LLDP 高级字段
- 光模块高级字段
- BSSID 高级字段

这些数据可以保留在数据库、详情页和高级导出中，但不要污染主列表。
