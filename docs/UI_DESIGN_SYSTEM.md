# NetConsole UI Design System v1.0

本文定义 Electron 唯一桌面产品中 Vue Renderer 的视觉基础。当前技术边界为 Vue 3、Element Plus、ECharts、NetConsole Design Token 与 Electron Shell；Element Plus 提供交互组件，NetConsole Token 负责视觉、密度和网络运维状态语义。

本设计系统面向长时间运行、高信息密度的网络运维场景，参考工业控制台和监控平台的稳定、克制风格。它不是第二套 Renderer，不改变 FastAPI/API 契约，也不把设备命令、采集、数据库或任务状态机移入 Vue。

## 1. 当前实现状态

全局主题基础已经接入唯一 Renderer：

- `apps/web/src/theme/tokens.css`：品牌、状态、字体、间距、圆角、密度和 Shell 尺寸；
- `apps/web/src/theme/light.css` 与 `dark.css`：浅色/深色语义色；
- `apps/web/src/theme/element-plus.css`：Element Plus 变量到 NetConsole Token 的映射；
- `apps/web/src/theme/theme.ts`：浅色、深色、跟随系统的运行时切换；
- `apps/web/src/theme/echarts.ts`：从当前 CSS Token 读取图表色并通知已挂载图表重绘；
- `NcCard`、`NcStatusTag`、`NcTable` 和 `NcLayout`：首批公共基础件；
- `components/table/NcDataTable`：标准业务表格、统一列定义、自动列宽、列设置和视图偏好的阶段 1 基础；当前仍有旧表待按清单逐域迁移；
- `AppLayout`：继续作为唯一应用 Shell，并开始消费统一尺寸和颜色 Token。
- Electron Main：窗口初始背景使用预定义浅/深安全色，运行期只接受受信 Renderer 报告的 `{ resolvedTheme: 'light' | 'dark' }`，不接受任意颜色或窗口参数。

应用 Shell、侧栏、顶部栏、页面、Element Plus 浮层和现有 Traffic/Mesh 图表已进入同一主题链，不再把固定深色侧栏作为默认行为。历史页面状态色已收敛到语义 Token，E10B 的 `WEB_STATUS_COLOR_TOKEN` 例外为 0；Guard 已收窄 `--nc-text-primary` 等普通文本 Token 的误报规则并有单元测试。业务页面尚未全部迁移到公共组件，最终 Electron 多尺寸、多缩放和 Windows 跟随系统视觉验收仍为 `PENDING`，不得因为自动 Guard 通过就标记视觉完成。

## 2. 分层与唯一职责

```text
Electron Main / Preload
        |
唯一 Vue Renderer
        |
AppLayout（应用 Shell）
        |
NcLayout（业务页骨架）
        |
NcCard / NcStatusTag / NcTable
        |
Element Plus + ECharts
        |
NetConsole Design Token
```

- `AppLayout` 管理全局导航、Header、Backend 状态和 RouterView。
- `NcLayout` 只管理业务页标题、动作、摘要、内容和响应式排列，不创建新导航或新运行时。
- 公共组件只处理布局与展示；超过 300 ms 的操作仍通过 Application Service 和 Job Center。

## 3. Token 规则

业务组件只引用语义变量，不直接绑定某个主题的十六进制颜色。

| 类别 | 代表变量 | 用途 |
| --- | --- | --- |
| 品牌 | `--nc-primary`、`--nc-primary-hover`、`--nc-primary-active` | 主动作、当前导航、趋势主线 |
| 状态 | `--nc-success`、`--nc-warning`、`--nc-danger`、`--nc-info` | 正常、告警、故障、未知/离线 |
| 背景 | `--nc-bg-page`、`--nc-bg-card`、`--nc-bg-sidebar`、`--nc-bg-code` | 页面、卡片、导航、日志 |
| 文字 | `--nc-text-primary`、`--nc-text-secondary`、`--nc-text-disabled` | 主信息、辅助信息、禁用态 |
| 边框 | `--nc-border`、`--nc-border-light`、`--nc-border-strong` | 容器、分隔、强调 |
| 密度 | `--nc-table-row-height`、`--nc-card-padding`、`--nc-card-gap` | 统一 40px 表格行高和 16px 卡片节奏 |
| Shell | `--nc-shell-header-height`、`--nc-shell-sidebar-width` | 56px Header、220px Sidebar |

浅色和深色文件只能给语义变量赋值；组件不得通过 `.dark` 再维护一套业务样式。

## 4. 主题与持久化

系统设置中的 `theme`、`theme_color` 和 `language` 仍是唯一事实源：

1. FastAPI 系统设置接口读取/保存配置；
2. `applySystemAppearance()` 调用 `applyNetConsoleTheme()`；
3. 根元素同步 `data-theme="light|dark"` 与 Element Plus 兼容的 `dark` class；
4. `auto` 模式监听操作系统颜色变化；
5. 用户选择的主题色覆盖 `--nc-primary`，Element Plus 派生色由统一映射生成。
6. Renderer 将解析后的 `light|dark` 通过严格单向 IPC 报告给 Electron Main；Main 只映射到预定义窗口背景色。

不得为主题另建 localStorage、Pinia 持久化或 Electron 配置文件，否则会形成第二事实源。设置页的实时预览、取消恢复和正式保存继续复用现有链路。

主题设置加载失败时，Browser 和 Electron 都回落到完整安全浅色，而不是只切换内容区。`auto` 模式通过 `prefers-color-scheme` 监听 Windows 主题变化，不重载路由和业务页面。

## 5. 公共组件契约

### `NcCard`

提供标题、副标题、动作、正文和 Footer 槽位。默认使用卡片背景、边框、8px 圆角、16px padding；只有明确可点击的卡片才启用 `interactive`。

### `NcStatusTag`

统一任务、Agent、设备和采集状态。传入值会先去空格并转为大写；运行中使用品牌色、完成使用成功色、告警使用警告色、失败使用危险色。未知值保留原始文本，避免诊断信息被“未知”吞掉。

### `NcTable`

基于 `el-table`，默认 40px 行高、14px 字体、浅色表头、hover/当前行语义背景，保留 Element Plus 的排序、选择、列宽和事件能力。默认 `stripe=true`，复杂页面可以使用 `compact`，但不能压缩到不可读。

表格仍应遵循：

- 核心字段稳定可读，总宽超出时允许横向滚动；
- 路径、错误和命令摘要使用省略号、Tooltip 或详情；
- 分页/懒加载，不在 Renderer 一次构造无上限数据；
- loading、empty、success、error、cancelled 均有可见反馈。

### `NcDataTable`

新增和完成迁移的标准数据表格使用 `NcDataTable`。它保证表头/内容默认居中、缺失值统一、文本真实测量、字段类型宽度基线、跨页宽度稳定、手工列宽与列布局偏好，并在容器不足时保持表头完整后由表格区域横向滚动。核心不变量是 `finalWidth >= headerRequiredWidth`。详情、日志等长文本左对齐必须在列定义中声明原因。

当前清单仍包含阶段 1 前已存在的直接 `el-table`，状态为 `BLOCKED`；该状态表示待迁移债务，不能写成全局表格整改完成。详见 [表格与字段展示标准](ui/TABLE_AND_FIELD_STANDARDS.md) 和 [表格清单](ui/TABLE_INVENTORY.md)。

### `NcLayout`

提供业务页 `eyebrow/title/description/actions/summary/body/footer` 区域，默认最大宽度 1680px；小于 850px 时标题和动作改为纵向。它不替代 `AppLayout`。

## 6. Element Plus 与 ECharts

Element Plus 的颜色、背景、文字、边框、圆角和阴影统一从 `element-plus.css` 映射。业务页面不得以 `--el-*` 重新定义另一套品牌色；需要业务语义时优先用 `--nc-*`。

ECharts Canvas 不能直接解析 CSS `var()`。图表初始化或主题变化后，应通过 `getComputedStyle(document.documentElement)` 读取 `--nc-primary`、状态色和文字色，再生成 option 并调用 `setOption`。约定：

- RSSI/吞吐趋势主线：`--nc-primary`；
- Mesh 主链路：`--nc-primary`；
- Mesh 备链路：`--nc-info`；
- 异常链路和失败点：`--nc-danger`；
- 告警阈值：`--nc-warning`。

现有 Traffic RTT、Traffic 带宽和 Mesh RSSI 图表已订阅统一主题事件；异步加载系统设置、切换主色或 `auto` 跟随系统变化后会重新读取 Token 并更新文字、坐标轴、网格、Tooltip、缩放条和数据色。本阶段不新增 `NcChart`，避免在现有图表生命周期尚未统一前制造空抽象。

Electron IPC 不属于图表或主题的第二事实源。它只接收最终解析结果以消除窗口装载期白闪/黑闪；Renderer 主题仍以系统设置和 CSS Token 为准。

## 7. 页面接入示例

```vue
<NcLayout eyebrow="AC 管理" title="FIT-AP 资源" description="当前局点资源">
  <template #actions>
    <el-button type="primary">更新资源</el-button>
  </template>
  <NcCard title="AP 列表">
    <NcTable :data="rows">
      <el-table-column prop="name" label="AP 名称" min-width="180" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }"><NcStatusTag :status="row.status" /></template>
      </el-table-column>
    </NcTable>
  </NcCard>
</NcLayout>
```

## 8. 渐进接入顺序

后续页面按真实功能开发或整改顺序接入，不做纯样式大爆炸修改：

1. 新页面直接使用四个基础件；
2. 已有页面在功能整改触及其布局时，收敛重复的 `content-card`、`metric-card` 和状态映射；
3. 新增或触碰 AC、Online MR、Mesh、Traffic 图表时复用 `theme/echarts.ts`，禁止重新硬编码独立色板；
4. 1920×1080 作为最低完整性视口，同时验证窄窗口滚动和操作区可达；
5. 浅色、深色、跟随系统三种模式均验证文字、边框、表格、弹窗和状态色，而不是只检查页面背景。

任何设计增强都必须建立在页面功能可用和 Qt 历史事实已完成 1:1 迁移的前提上，不能用视觉完成替代业务验收。

当前自动测试只证明主题解析、Token、Element Plus/ECharts 事件和 Electron IPC 契约。最终仍需在 Electron 中人工覆盖浅色、深色、跟随系统，1280×720/1920×1080/2560×1440，以及 100%/125%/150% 缩放；在该清单实际完成前，视觉状态保持 `PENDING`。
