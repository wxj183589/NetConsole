<script setup lang="ts">
import { useRouter } from 'vue-router'
import NcLayout from '../../layouts/NcLayout.vue'

const router = useRouter()
</script>

<template>
  <NcLayout
    title="版本与功能交付已退役"
    description="此版本随安装包交付功能。"
  >
    <section class="retired-card">
      <el-button type="primary" @click="router.push('/settings')">返回系统设置</el-button>
      <el-button @click="router.push({ name: 'logs', query: { tab: 'about' } })">查看版本信息</el-button>
    </section>
  </NcLayout>
</template>

<style scoped>
.retired-card { padding: 20px; color: var(--nc-text-secondary); background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: var(--nc-radius-base); }
.retired-card p { margin: 0 0 16px; }
</style>
