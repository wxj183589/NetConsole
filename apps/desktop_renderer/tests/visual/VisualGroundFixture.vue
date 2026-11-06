<script setup lang="ts">
import GroundUnattendedView from '../../src/views/rail-transit/GroundUnattendedView.vue'
import NcConfirmDialog from '../../src/components/feedback/NcConfirmDialog.vue'
</script>

<template>
  <div class="ground-fixture">
    <header class="fixture-header">NetConsole · Ground V2 · HTTP Mock</header>
    <div class="fixture-body">
      <aside class="fixture-sidebar">轨道交通<br />地面无人值守</aside>
      <div class="fixture-workspace"><GroundUnattendedView /></div>
    </div>
    <NcConfirmDialog />
  </div>
</template>

<style scoped>
.ground-fixture{height:100vh;width:100%;display:flex;flex-direction:column;min-width:0;overflow:hidden}
.fixture-header{height:52px;flex:none;display:flex;align-items:center;padding:0 18px;border-bottom:1px solid var(--el-border-color)}
.fixture-body{flex:1;min-height:0;min-width:0;display:flex}
.fixture-sidebar{width:200px;flex:none;line-height:2;padding:18px;border-right:1px solid var(--el-border-color)}
.fixture-workspace{flex:1;min-width:0;min-height:0;padding:16px;overflow:auto}
</style>
