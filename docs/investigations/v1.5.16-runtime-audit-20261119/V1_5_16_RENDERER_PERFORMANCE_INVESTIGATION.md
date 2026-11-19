# NetConsole v1.5.16 Renderer 性能专项调查

## 目标测试

`apps/desktop_renderer/src/components/mesh-analysis/tracksideSeriesColors.test.ts`

性能断言保留原阈值：481 series / 7,549 points 为 50 ms；770 series / 44,251 points 为 100 ms。没有修改断言、跳过测试或降低门槛。

## v1.5.16 定向复现

| 次数 | 770 series 算法耗时 | 原阈值 | 结果 |
| --- | ---: | ---: | --- |
| 1 | 29.594 ms | 100 ms | PASS |
| 2 | 30.735 ms | 100 ms | PASS |
| 3 | 31.969 ms | 100 ms | PASS |

三次测试文件均 `5 passed`。481 series 用例三次分别约 `5.893 ms`、`10.761 ms`、`11.363 ms`，均低于 50 ms。随后在当前 release worktree 再运行一次，770 series 为 `27.360 ms`，文件 `5 passed`。

## 与 v1.5.15 基线

- 测试文件 blob：v1.5.15 `956f86a1cd89b09674429beb2c29a4a2fb6151d4`；v1.5.16 相同。
- 实现文件 blob：v1.5.15 `2ebc0860d5210c11150a0a428858382c39b40c41`；v1.5.16 相同。
- Renderer lockfile blob：v1.5.15 `9687bbd7b3a5746a95b13daf6da1b06a5454ef5c`；v1.5.16 相同。
- v1.5.16 失败来自完整 Renderer suite 的一次约 103 ms / 100 ms 波动；定向重复没有复现。

## 结论

`RENDERER_ROOT_CAUSE=TEST_ENVIRONMENT_PERFORMANCE_VARIATION`
`RENDERER_PRODUCT_REGRESSION=NOT_CONFIRMED`
`PRODUCT_CODE_CHANGED=0`

没有发现 v1.5.16 版本更新改变该组件或其依赖。没有进行全量 Renderer 重跑。
