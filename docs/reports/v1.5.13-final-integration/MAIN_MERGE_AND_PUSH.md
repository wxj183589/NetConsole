# Main Merge and Push

## 本地整合

- 本地 `main` 起点：`e2d98cf801c07ab606a188596b893e6462a949dc`
- 合并源提交：`29d76f4a2abedbb950409ebad4799dea522a9148`
- 产品代码合并提交：`5294f1ea7e1a1829e38d77c167f5e2d088ed0d99`
- 最终产品工作树分支：`main`
- 合并方式：常规 Git merge；7 个内容冲突人工解析并完成冲突标记、定向回归和 diff check 检查。

解析时保留了便携模式 `portable.mode`、程序目录下默认 `data`、`portable-data-root.json`、C 盘允许但提示非系统盘优先、安装器 fail-closed 以及既有数据根保护语义。

## GitHub 推送

远程：`github`，地址为 `git@github.com:wxj183589/NetConsole.git`。

执行了非强制：

```text
git push github main
```

GitHub 返回 `GH013: Repository rule violations found for refs/heads/main`，明确包含：

- `Changes must be made through a pull request.`
- `Required status check "Engineering hardening blocking gates" is expected.`

因此 `REMOTE_MAIN_PUSH=BLOCKED_BY_BRANCH_PROTECTION`。未使用 force push、管理员绕过或其他保护规避方式。推送拒绝后远程 `github/main` 仍为 `37b0df95a3208d0d03380e76ccfe5419af1422f1`，本地变更没有被错误宣称为远程已合并。

后续若要进入 GitHub 主线，应通过仓库要求的 Pull Request 和必需状态检查完成；本报告不代替该远程门禁。
