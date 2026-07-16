import { contextBridge, ipcRenderer } from 'electron'

import { createDesktopBridge } from './bridge'

contextBridge.exposeInMainWorld('netconsoleDesktop', createDesktopBridge(ipcRenderer))
