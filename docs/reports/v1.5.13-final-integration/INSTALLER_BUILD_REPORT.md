# Installer Build Report

## 结果

`INSTALLER_BUILD=BLOCKED_BY_UPSTREAM_PROTECTION`。

Full Gate 的 package-smoke 按仓库既有流程尝试进入：

```text
pnpm run smoke:package
pnpm run package:dir
pnpm run package:prepare
scripts.build.build_installer --prepare-identity
```

构建在 electron-builder 之前被仓库保护拒绝，原始错误为：

```text
INSTALLER BUILD FAILED
正式安装器必须在最终提交推送到 upstream 后构建
```

因此本轮没有 Installer 文件、大小或 SHA256；`INSTALLER_SMOKE=NOT_RUN`。没有修改保护脚本，也没有伪造安装器文件或 hash。

## 边界

- Full 源码统一入口和 v1.5.13 版本信息已通过源代码、定向测试和 Portable 构建验证。
- 安装版真实构建、安装/升级/卸载、签名、GUI 和现场验收仍需在 GitHub PR/必需检查完成后的允许候选上重新执行。
- Customer/定制版交付入口已在 changelog 标记为 Deprecated；兼容脚本保留用于历史构建，不代表 Customer 安装包验收完成。
