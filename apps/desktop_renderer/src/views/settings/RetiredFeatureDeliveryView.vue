<script setup lang="ts">
import { useRouter } from 'vue-router'
import NcLayout from '../../layouts/NcLayout.vue'

const router = useRouter()
</script>

<template>
  <NcLayout
    title="版本与功能交付已退役"
    description="正式产品统一使用 Full Installer 与 Full Portable；旧版本功能矩阵不再提供运行时编辑或客户版解锁入口。"
  >
    <section class="retired-card">
      <p>如需调整已验收功能，请通过源码、Feature Registry 和正式构建门禁完成变更。</p>
      <el-button type="primary" @click="router.push('/settings')">返回系统设置</el-button>
    </section>
  </NcLayout>
</template>

<style scoped>
.retired-card { padding: 20px; color: var(--nc-text-secondary); background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: var(--nc-radius-base); }
.retired-card p { margin: 0 0 16px; }
</style>
