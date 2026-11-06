<script setup lang="ts">
import { t } from '../../i18n/runtime'
import { useGroundContext } from './useGroundUnattended'
const { NcDataTable, groundStatusLabel, profile, deepCollections, deepTableHost, deepTableMaxHeight, deepColumns, statusType, showDeepCollector } = useGroundContext()
</script>

<template>
<section class="ground-subpage">
        <el-alert v-if="profile && !profile.deep_collection_master_enabled" :title="t('ground.v2.deep_lightweight', '当前为轻量模式：深度采集已关闭，历史记录仍可查看。')" type="info" :closable="false" show-icon />
        <div class="coverage-strip"><span v-for="value in ['INELIGIBLE','ELIGIBLE','QUEUED','STARTING','RUNNING','STOPPING','STOPPED','FAILED']" :key="value"><b>{{ deepCollections.filter((row) => row.deep_state === value).length }}</b>{{ groundStatusLabel(value) }}</span></div>
        <div ref="deepTableHost" class="table-frame"><NcDataTable :data="deepCollections" :columns="deepColumns" table-id="ground-deep" route-key="rail-ground-unattended" row-key="train_id" :max-height="deepTableMaxHeight" auto-height compact>
          <template #cell-status="{ row }"><el-tag size="small" :type="statusType(row.status)">{{ groundStatusLabel(row.status) }}</el-tag></template>
          <template #cell-deep_state="{ row }"><el-tag size="small" :type="statusType(row.deep_state)">{{ groundStatusLabel(row.deep_state) }}</el-tag></template>
          <template #cell-collector_data="{ row }"><div class="row-actions"><el-button v-for="collector in row.collectors" :key="collector.mr_role || collector.mr_id" size="small" text type="primary" :disabled="!collector.collector_session_id" @click="showDeepCollector(collector)">{{ collector.mr_role || collector.mr_id }} {{ collector.state }}</el-button><span v-if="!row.collectors.length" class="muted">{{ t('ground.v2.no_session', '尚未创建会话') }}</span></div></template>
          <template #cell-fping_health="{ row }"><div class="row-actions"><el-tag v-for="collector in row.collectors" :key="`${collector.mr_role}-fping`" size="small" :type="collector.fping_status === 'running' || collector.fping_status === 'stopped' && collector.fping_sample_count > 0 ? 'success' : collector.fping_status === 'failed' || collector.data_integrity_status === 'INCOMPLETE' ? 'danger' : 'info'">{{ collector.mr_role || 'MR' }} · {{ collector.fping_status }} · {{ collector.fping_sample_count }}</el-tag><span v-if="!row.collectors.length" class="muted">{{ t('ground.v2.no_session', '尚未创建会话') }}</span></div></template>
        </NcDataTable></div>

</section>
</template>

<style scoped src="./groundUnattended.css"></style>
