# AP Optical Treatment Report

## Current 与台账

最终 main commit：`afa35c06`

AP Optical Current 使用 `site_id + ap_identity + side`；Treatment 使用唯一键 `site_id + ap_identity`，AP/SW 两侧合并为一行，避免同一 AP 重复工单。Recent 每个资源最多 10 条有效变化。

## DEV 结果

- `optical_current`：6,638 行。
- `optical_history`：50,863 行，最大每资源深度 10。
- `ap_optical_treatment`：322 行。
- 重复 Treatment key：0；Treatment rows over AP：0。
- hzl10：Current 984、Recent 8,646、Treatment 85。
- 宁波12号线：Current 1,892、Recent 18,907、Treatment 101。
- 旧 `ac_fit_ap_optical_history`/`ap_optical_history`：0 行。

## 结论

**PASS（DEV）**。页面和导出只读取 Current/Treatment；Recent 不用于全量重建。真实 GUI 异常确认和生产接管仍需单独任务。
