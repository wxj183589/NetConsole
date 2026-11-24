<script setup lang="ts">
import type { InfrastructureDevice, InfrastructureNode, InfrastructureSwitchAps } from '../../../api/railInfrastructure'
import { uniqueDevices } from './infrastructurePresentation'
import { t } from '../../../i18n/runtime'
defineProps<{ node: InfrastructureNode; label: string; selectedUid: string; selectedDeviceId?: string; aps?: InfrastructureSwitchAps }>()
const emit = defineEmits<{ node: [uid: string]; device: [device: InfrastructureDevice]; ap: [ap: InfrastructureSwitchAps['items'][number]] }>()
</script>
<template>
  <div class="engineering-tree-node">
    <el-tooltip :content="label" placement="right" :show-after="350">
      <button class="tree-node" type="button" :aria-pressed="node.uid === selectedUid" @click="emit('node', node.uid)"><span class="tree-label">{{ label }}</span></button>
    </el-tooltip>
    <ul v-if="node.uid === selectedUid && node.devices.length" class="tree-devices">
      <li v-for="device in uniqueDevices(node.devices)" :key="device.device_uuid">
        <el-tooltip :content="device.role && device.role !== device.name ? `${device.role} · ${device.name}` : device.name" placement="right" :show-after="350">
          <button class="tree-node" type="button" :aria-pressed="device.device_uuid === selectedDeviceId" @click="emit('device', device)"><span class="tree-label">{{ device.role && device.role !== device.name ? `${device.role} · ${device.name}` : device.name }}</span></button>
        </el-tooltip>
        <ul v-if="device.device_uuid === selectedDeviceId && aps?.items.length" class="tree-aps">
          <li v-for="ap in aps.items" :key="ap.row_id">
            <button class="tree-node tree-label" type="button" :title="ap.ap_name || t('infrastructure.identity_unconfirmed', '身份未确认')" @click="emit('ap', ap)">{{ ap.ap_name || t('infrastructure.identity_unconfirmed', '身份未确认') }}</button>
          </li>
        </ul>
      </li>
    </ul>
  </div>
</template>
<style scoped>
.tree-node { display: block; width: 100%; padding: 7px 9px 7px 16px; color: inherit; text-align: left; background: transparent; border: 0; border-radius: 5px; cursor: pointer; }
.tree-label { display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.tree-devices, .tree-aps { list-style: none; padding-left: 12px; margin: 0; }
.tree-aps { font-size: 12px; color: var(--nc-text-secondary); }
.tree-node:hover, button[aria-pressed="true"] { background: var(--el-color-primary-light-9); }
button[aria-pressed="true"] { color: var(--el-color-primary); }
</style>
