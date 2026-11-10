# 稳定性报告

## 已执行场景

- 七项工作区反复进入 / 离开；
- 主链路完整范围与窄窗口切换；
- 普通滚轮缩放和不同锚点；
- Radio 1 / Radio 2 快速切换；
- Tooltip 固定、鼠标移出、Esc 解除；
- Shift 选择和 Ctrl 动态浏览；
- 链路明细角色 / 文本筛选；
- 列设置应用；
- 页面离开到其他无线页面后重新进入；
- 全范围 13 指标加载后 45 秒空闲；
- 受影响组件生命周期和取消状态。

## 结果

- 真实 Electron Renderer crash：0（修复后复测）。
- 页面异常空白：0。
- 页面永久 loading：0。
- 未观察到未释放的 pending raw / metric / records / AP 请求。
- ECharts dispose、mount / unmount 和 native listener 数量保持有界。
- Radio 2 空数据不会污染 Radio 1 数据。
- gap boundary 在视觉有界采样后仍可见。

## 前后缺陷

最初全范围图表直接交给 ECharts 时曾出现
ELECTRON_RENDERER_PROCESS_GONE reason=crashed exit_code=-36861。
根因是图表端同时持有过大的完整业务对象和绘制负载。本轮以最小范围修复：

1. raw cache 仍保存完整样本；
2. derived metric cache 按窗口复用并限制条目数；
3. 只把紧凑字段和边界保留样本交给图表；
4. 为 Electron 原生 dblclick 增加 fallback，并做双来源去重；
5. 补充两个组件回归测试。

修复后重新跑全指标、窗口、tooltip、Radio 和页面重入，没有重现 crash。

## 限定

未宣称本轮重新完成 30 分钟长稳；Phase 11.9 的 30 分钟证据保持为历史基线，
当前修复场景完成持续空闲和交互复测。
