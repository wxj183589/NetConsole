<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

onMounted(() => {
  void router.replace('/rail-transit/train-communication')
})
</script>

<template>
  <div class="car-network-diagnostic-compat" aria-hidden="true" />
</template>
