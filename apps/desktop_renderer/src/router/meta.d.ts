import 'vue-router'

export {}

declare module 'vue-router' {
  interface RouteMeta {
    navigationId?: string
    featureId?: string
    moduleId?: string
    title?: string
    tabTitle?: string
    desktopOnly?: boolean
    hiddenRoute?: boolean
    keepAlive?: boolean
    cacheComponentName?: string
  }
}
