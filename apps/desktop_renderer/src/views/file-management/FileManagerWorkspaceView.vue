<script setup lang="ts">
import { activeSiteContext } from '../../stores/siteContext'
import FileWorkspacePanel from './FileWorkspacePanel.vue'
</script>

<template>
  <FileWorkspacePanel :key="activeSiteContext?.siteId" />
</template>
