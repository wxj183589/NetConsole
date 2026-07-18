# fping 5.5 Windows/Cygwin 构建配方

本配方记录仓库中 `fping.exe` 的实际构建输入。产品和 Agent 打包只复制、校验本目录中的固定文件，不执行本配方，也不访问网络。

## 固定输入

- 上游仓库：`https://github.com/schweikert/fping`
- 上游标签：`v5.5`
- 上游提交：`06f9481ef3cf79c2aa973718366fb13927777689`
- 本地补丁：`CYGWIN_ICMP_COMPAT.patch`
- 构建环境：Cygwin x86_64，运行时 `cygwin-3.6.9-1`
- 配置参数：`--disable-ipv6 --enable-safe-limits`

补丁新增 `src/cygwin_icmp_compat.h`，并在 `src/fping.c`、`src/socket4.c` 中引入该头文件，用于补齐 Cygwin 环境缺少的 ICMP 常量和结构定义。补丁哈希由 `SOURCE_PROVENANCE.json` 和发布 Guard 固定。

## 可复现步骤

在具备 `git`、`gcc`、`make`、`autoconf`、`automake`、`libtoolize`、`pkg-config`、`perl`、`patch` 与 `cygcheck` 的 Cygwin x86_64 环境中执行：

```bash
git clone https://github.com/schweikert/fping.git fping
cd fping
git checkout --detach 06f9481ef3cf79c2aa973718366fb13927777689
git apply --check /path/to/CYGWIN_ICMP_COMPAT.patch
git apply /path/to/CYGWIN_ICMP_COMPAT.patch
./autogen.sh
./configure --disable-ipv6 --enable-safe-limits
make -j"$(nproc)"
src/fping.exe -v
src/fping.exe -h
cygcheck src/fping.exe
```

验收要求：版本输出为 5.5，帮助中包含 `-J/--json`，`cygcheck` 运行时闭包只使用清单中固定的 Cygwin x64 DLL。生成物必须再通过 Python、PowerShell 和 Electron 三层本地文件 Guard；不得由构建脚本在线下载或静默替换。
