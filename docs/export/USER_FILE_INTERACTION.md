# 用户文件导入导出交互契约

本文是 NetConsole 新增或修改用户文件交互的永久开发契约。页面、Task Center、Electron Bridge 与 Backend 的实现和测试必须共同遵守本文；一次性页面审计矩阵不作为长期事实源。

## 一、适用范围与文件边界

本契约覆盖所有用户可见的导入文件、批量导入、导入文件夹、模板导入、局点包导入、表格/报告/链路明细导出、报告生成、模板下载、ZIP/Markdown/TXT/CSV/XLSX/PDF 下载、Artifact 保存或另存，以及已有受管文件导出副本。

实现前必须先区分以下六类文件：

1. **用户最终副本**：用户明确发起并选择最终路径的导出、下载或另存结果。
2. **Export Worker 内部临时文件**：Worker 生成过程中的临时输出，不向用户暴露最终路径。
3. **Artifact Store 文件**：任务完成后由 Task Center 管理的受管 Artifact。
4. **文件管理受管下载**：SFTP 队列按业务规则写入受管下载区的文件。
5. **受管本地日志扫描**：用户显式触发后，只在当前局点数据根内发现待补录日志，不接受任意路径。
6. **测试和构建输出**：自动化测试、打包和 smoke 流程产生的非用户文件。

用户最终副本必须由用户当次选择路径。内部 Artifact、任务日志、缓存、Worker 临时文件、受管下载、测试和构建输出不等同于用户最终导出，不逐次弹出“另存为”。

## 二、任务型导出的唯一流程

新增任务型导出必须遵循：

1. 在 [`exportActionRegistry.ts`](../../apps/desktop_renderer/src/platform/exportActionRegistry.ts) 注册稳定的固定动作。
2. 为动作定义 `module`、`label`、`filters`、`artifactExtensions` 和 `artifactMediaTypes`。
3. 页面调用 [`submitExportAfterDestinationSelected(...)`](../../apps/desktop_renderer/src/composables/useUserSelectedExport.ts)。
4. Electron Main 先打开 Save As；用户取消时不调用 `submit`、不创建任务、不产生 Artifact，也不提示任务提交成功。
5. 用户确认路径后才创建 Export Task。共享协调器绑定 `taskId`、`action`、Main 授权路径、文件名、`module` 和 `context`。
6. Export Process 只生成内部 Artifact，Task Center 发布 Artifact 元数据。
7. Artifact 就绪后，共享协调器调用 `saveReadyArtifact(...)`，并向 Electron Main 传递 `destinationPath`、`expectedSizeBytes` 和 `expectedSha256`。
8. 已预选路径时不得弹出第二次 Save As。只有 Electron Main 返回 `saved` 才能提示已保存。
9. 本地保存失败时保留 Artifact，通过 `retryArtifactSave(...)` 重新选择路径；不得重新创建任务或重新生成报告。

页面接入使用现有 API：

```ts
const {
  submitExportAfterDestinationSelected,
  hasActiveExportAction,
} = useUserSelectedExport()

async function exportData(): Promise<void> {
  const result = await submitExportAfterDestinationSelected({
    action: 'module.export_action',
    suggestedName: buildSuggestedName(),
    context: {
      scope: 'current',
    },
    submit: () => startExportTask(buildRequest()),
    taskId: (task) => task.task_id,
  })

  if (result.status === 'cancelled') return
}
```

`hasActiveExportAction(...)` 用于沿用共享的防重复提交状态。页面不自行轮询 Artifact，不自行维护 `destinationPath` 或私有 `sessionStorage`，也不在调用 `chooseSavePath` 后复制任务绑定、保存和失败重试状态机；全局协调器和 Task Center 负责保存终态。

## 三、固定动作注册规则

所有新增任务型导出必须先修改 [`apps/desktop_renderer/src/platform/exportActionRegistry.ts`](../../apps/desktop_renderer/src/platform/exportActionRegistry.ts)。

禁止页面：

- 传入任意字符串动作。
- 自行定义 MIME 类型、Artifact 扩展名校验或重复维护 CSV/XLSX/ZIP/TXT filters。
- 只凭 `suggestedName` 后缀判断 Artifact 类型。
- 私建 `pendingExports`、`autoSavedTaskIds`、轮询器或保存状态机。

代码评审必须确认动作 ID 稳定且有领域前缀、`module` 正确、扩展名与真实 Artifact 一致、媒体类型与 Backend 响应一致、页面使用共享协调器，并补充相关行为测试与静态审计。

## 四、已有文件与历史 Artifact

历史 Artifact、单个已有配置文件、已生成归档和现成模板响应不需要新建 Export Task。用户点击“下载”或“另存 Artifact”时调用 [`downloadBackendResource(...)`](../../apps/desktop_renderer/src/platform/runtime.ts)，且不传 `destinationPath`，由 Electron Main 当次弹出一次 Save As。

页面加载、Tab 恢复和历史任务恢复不得自动弹窗或自动保存。已有文件若需要“导出副本”，仍属于用户最终副本，必须由用户当次选择路径。

## 五、导入的唯一流程

### Browser File/FileList

`<input type="file">`、`multiple` 和 `webkitdirectory` 适用于需要上传文件内容的入口：

- 只能由用户点击触发。
- 取消时不得调用 prepare、preview 或 import API。
- 处理完成后清空 `input.value`，保证再次选择同名文件仍触发 `change`。
- 文件夹导入只使用用户实际选择的 `FileList`，不得扫描默认目录或上次目录。
- UI 显示实际文件名、数量和预检结果。

### Electron Main 授权路径

`selectFile`、`selectDirectory`、`selectSitePackage` 等专用选择器适用于将本地路径交给 Main/Backend 的入口：

- 只使用 Main 返回的授权路径，不接受 Renderer 任意文本路径。
- 用户取消后不得调用 Backend。
- 文件选择框的扩展名过滤不能替代 Backend 校验。

Backend 必须继续校验扩展名、文件头和可读性、文件契约、`module/type/schema`、必要字段/Sheet/manifest、非空数据、重复内容、业务结构和 ZIP 路径穿越。

## 六、Browser 与 Electron 边界

正式 Electron 必须使用 Native Bridge。`netconsole_host=electron` 缺少 Bridge 时直接失败，不得回退 `anchor.download`，也不得把 Backend 内部 Artifact 路径当作用户最终路径。

Browser 开发模式可以返回 `started`，UI 只能提示“浏览器已开始下载”，不得提示文件已保存到某目录，也不保证本地落盘完整性。

## 七、已登记例外

1. **OmniPeek 名称表**：保留专用目录和文件预选流程，但仍必须在创建任务前选择最终路径。
2. **局点包**：保留 `selectSitePackage` / `selectSiteExportDestination`，以及迁移包、脱敏包、现场包和回传包的安全提示与文件契约。
3. **SFTP 文件管理**：保留受管下载目录、批量队列、重试、归档和自动导入语义，不要求每个远程文件弹 Save As；从受管文件区“导出副本/另存为”时仍须弹窗。
4. **MESH 本地日志扫描**：这是历史遗留、手工复制和失败导入的补偿机制，只允许用户点击后扫描当前局点受管 MESH raw 目录；不提供路径输入，不访问其他局点，不替代 Browser `File/FileList` 手工导入。目录遍历、哈希和批量补录进入 Job Center，页面进入不得自动全量扫描。
5. **内部 Artifact、任务日志、缓存和临时文件**：不属于用户最终副本，不弹 Save As。

任何新增例外都必须在本文和静态审计测试中登记，写明不能使用通用协调器的技术原因，并获得明确代码评审。

## 八、禁止事项

- 在页面重新实现导出状态机、私有 `sessionStorage` 绑定或 Artifact 自动保存 watcher。
- 任务完成后突然弹 Save As，或页面/历史任务恢复时自动保存。
- 用户取消选择后仍创建任务。
- 使用 Downloads、Documents、Desktop、业务数据根、`cwd` 或测试目录作为用户最终默认路径。
- Renderer 直接执行 `fs`、`writeFile`、`Workbook.save`、`to_excel` 或 `savefig`。
- 将 Main 未授权路径传给 Backend，或把用户最终路径写入 Python `ExportJob` / 业务数据库。
- Electron Bridge 缺失时回退浏览器下载。
- 仅依赖前端 `accept` / filter 判断导入文件安全。

## 九、新功能检查表

```text
[ ] 是否是用户最终导出副本
[ ] 是否已在 exportActionRegistry.ts 注册
[ ] 是否调用 submitExportAfterDestinationSelected
[ ] 取消后是否完全不创建任务
[ ] 是否由共享协调器保存 Artifact
[ ] 是否传入大小和 SHA-256
[ ] 保存失败是否复用 Artifact
[ ] 历史任务是否只在用户点击后另存
[ ] 是否避免页面私有保存状态机
[ ] Browser 是否只报告 started
[ ] 导入取消是否不预检
[ ] file input 是否处理后清空
[ ] Backend 文件契约校验是否保留
[ ] 是否属于已登记例外
[ ] 是否补充行为测试和静态审计
```

Export Process 的内部 Artifact、临时文件、JSONL、取消和原子替换规则见 [导出进程规范](./PROCESS_POLICY.md)。
