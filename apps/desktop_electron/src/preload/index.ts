import { contextBridge, ipcRenderer, webUtils } from 'electron'

import { createDesktopBridge } from './bridge'

contextBridge.exposeInMainWorld('netconsoleDesktop', createDesktopBridge(ipcRenderer, file => webUtils.getPathForFile(file)))
