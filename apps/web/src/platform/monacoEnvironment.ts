import EditorWorker from 'monaco-editor/editor/editor.worker.js?worker'

export type MonacoEditorModule = typeof import('monaco-editor/editor/editor.api.js')

type MonacoWorkerEnvironment = {
  getWorker: (_moduleId: string, _label: string) => Worker
}

let monacoPromise: Promise<MonacoEditorModule> | null = null

export function loadMonacoEditor(): Promise<MonacoEditorModule> {
  const scope = globalThis as typeof globalThis & {
    MonacoEnvironment?: MonacoWorkerEnvironment
  }
  scope.MonacoEnvironment = {
    getWorker() {
      return new EditorWorker()
    },
  }
  monacoPromise ??= import('monaco-editor/editor/editor.api.js')
  return monacoPromise
}
