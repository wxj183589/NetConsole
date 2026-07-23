<template>
  <RouterView v-slot="{ Component, route: viewRoute }">
    <KeepAlive :max="1">
      <component
        :is="Component"
        v-if="viewRoute.meta.keepAlive"
        :key="String(viewRoute.name)"
      />
    </KeepAlive>
    <component
      :is="Component"
      v-if="!viewRoute.meta.keepAlive"
      :key="viewRoute.fullPath"
    />
  </RouterView>
</template>
