<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, UploadFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { useRailTransitBaseDataStore } from '../../stores/railTransitBaseData'
import type { TracksideAp, VehicleMr } from '../../types/railTransitBaseData'

const store = useRailTransitBaseDataStore()
const router = useRouter()
const activeTab = ref('overview')
const locationTab = ref('stations')
const vehicleTab = ref('trains')
const previewFilter = ref('all')
const mergeRows = computed(() => {
  const rows = store.importPreview?.merge_plan?.items || []
  return previewFilter.value === 'all' ? rows : rows.filter((row) => row.result === previewFilter.value)
})
const issueCodeStats = computed(() => Object.entries(store.issueCodeCounts).sort((left, right) => right[1] - left[1]))
const summaryCards = computed(() => [
  ['站点', store.summary?.station_count || 0, 'normal'],
  ['区间', store.summary?.section_count || 0, 'normal'],
  ['轨旁 AP', store.summary?.ap_count || 0, 'normal'],
  ['列车', store.summary?.train_count || 0, 'normal'],
  ['车载 MR', store.summary?.mr_count || 0, 'normal'],
  ['缺失位置 AP', store.summary?.missing_location_ap_count || 0, 'warning'],
  ['无效里程', store.summary?.invalid_mileage_count || 0, 'danger'],
  ['重复 AP MAC', store.summary?.duplicate_ap_mac_count || 0, 'danger'],
  ['重复静态 IP', store.summary?.duplicate_static_ip_count || 0, 'danger'],
  ['未关联列车 MR', store.summary?.unbound_mr_count || 0, 'warning'],
])

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibility)
  store.startPolling()
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibility)
  store.stopPolling()
})

function handleVisibility(): void {
  if (document.hidden) store.stopPolling()
  else store.startPolling()
}

async function handleFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    await store.previewImport(file)
    ElMessage.success('导入预览解析完成，未写入数据库')
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : '导入预览失败')
  } finally {
    input.value = ''
  }
}

function openApAc(ap: TracksideAp): void {
  router.push({ path: '/ac-management', query: { ap: ap.runtime.fit_ap_status !== 'unknown' ? ap.name : undefined } })
}
function openApMesh(ap: TracksideAp): void {
  router.push({ path: '/ac-management/mesh-links', query: { peer_ap_name: ap.name } })
}
function openMrMesh(mr: VehicleMr): void {
  router.push({ path: '/ac-management/mesh-links', query: { mr_name: mr.name } })
}
function openMrSession(mr: VehicleMr): void {
  router.push({ path: '/rail-transit/online-mr', query: { session_id: mr.runtime.latest_session_id || undefined, device_id: mr.id } })
}
function issueType(value: string): 'danger' | 'warning' | 'info' {
  return value === 'error' ? 'danger' : value === 'warning' ? 'warning' : 'info'
}
function mergeType(value: string): 'success' | 'danger' | 'warning' | 'info' {
  if (value === 'CREATE' || value === 'UPDATE') return 'success'
  if (value === 'CONFLICT') return 'danger'
  if (value === 'NEEDS_CONFIRMATION') return 'warning'
  return 'info'
}
function diffSummary(diffs: Array<{ field_name: string; action: string }>): string {
  return diffs.map((item) => `${item.field_name}: ${item.action}`).join('；') || '--'
}
function stateType(value: string): 'success' | 'danger' | 'warning' | 'info' {
  if (['online', 'normal', 'fresh'].includes(value)) return 'success'
  if (['offline', 'critical', 'error'].includes(value)) return 'danger'
  if (['stale', 'warning', 'unauthenticated'].includes(value)) return 'warning'
  return 'info'
}
function display(value: unknown): string { return value === null || value === undefined || value === '' ? '--' : String(value) }
function mileageRange(minimum: number | null, maximum: number | null): string {
  if (minimum === null && maximum === null) return '--'
  if (minimum === maximum || maximum === null) return `${minimum} m`
  return `${minimum}–${maximum} m`
}
function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}
</script>

<template>
  <section class="rail-base-data" v-loading="store.loading">
    <el-alert
      title="轨道交通基础资料只读视图"
      description="本页只查询当前局点的线路、位置、轨旁 AP、列车和车载 MR；导入功能仅做预览校验，不写数据库、不创建任务、不连接设备。"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="page-toolbar">
      <div>
        <h2>轨道交通基础资料</h2>
        <p>{{ store.summary?.site_name || '当前局点' }} · {{ store.summary?.line_name || '线路未填写' }} · {{ store.summary?.project_type || '项目类型未填写' }}</p>
      </div>
      <el-button :icon="Refresh" :loading="store.loading" @click="store.manualRefresh">刷新只读数据</el-button>
    </div>
    <el-alert v-if="store.error" :title="store.error" type="error" :closable="false" show-icon class="page-error" />

    <div class="content-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="基础资料总览" name="overview">
          <div class="summary-grid">
            <article v-for="card in summaryCards" :key="String(card[0])" :class="String(card[2])">
              <span>{{ card[0] }}</span><strong>{{ card[1] }}</strong>
            </article>
          </div>
          <el-descriptions :column="3" border class="meta-block">
            <el-descriptions-item label="局点 ID">{{ store.summary?.site_id || '--' }}</el-descriptions-item>
            <el-descriptions-item label="网络类型">{{ store.summary?.network_type || '--' }}</el-descriptions-item>
            <el-descriptions-item label="数据更新时间">{{ store.summary?.updated_at || '--' }}</el-descriptions-item>
            <el-descriptions-item label="说明" :span="3">{{ store.summary?.message || '--' }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>

        <el-tab-pane label="站点与区间" name="locations">
          <el-tabs v-model="locationTab" type="card">
            <el-tab-pane label="站点" name="stations">
              <el-table :data="store.stations" stripe height="calc(100vh - 365px)" empty-text="暂无站点资料">
                <el-table-column prop="sort_order" label="顺序" width="80" />
                <el-table-column prop="name" label="站点名称" min-width="180" />
                <el-table-column prop="code" label="站点编码" min-width="120"><template #default="scope">{{ display(scope.row.code) }}</template></el-table-column>
                <el-table-column prop="ap_count" label="AP 数量" width="110" />
                <el-table-column prop="section_count" label="关联区间" width="110" />
                <el-table-column label="里程范围" min-width="160"><template #default="scope">{{ mileageRange(scope.row.mileage_min, scope.row.mileage_max) }}</template></el-table-column>
                <el-table-column prop="remark" label="备注" min-width="180"><template #default="scope">{{ display(scope.row.remark) }}</template></el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="区间" name="sections">
              <el-table :data="store.sections" stripe height="calc(100vh - 365px)" empty-text="暂无区间资料">
                <el-table-column prop="name" label="区间名称" min-width="200" />
                <el-table-column prop="start_station" label="起始站" min-width="140"><template #default="scope">{{ display(scope.row.start_station) }}</template></el-table-column>
                <el-table-column prop="end_station" label="终点站" min-width="140"><template #default="scope">{{ display(scope.row.end_station) }}</template></el-table-column>
                <el-table-column prop="line_side" label="线路方向" min-width="120"><template #default="scope">{{ display(scope.row.line_side) }}</template></el-table-column>
                <el-table-column prop="ap_count" label="AP 数量" width="110" />
                <el-table-column label="里程范围" min-width="160"><template #default="scope">{{ mileageRange(scope.row.mileage_min, scope.row.mileage_max) }}</template></el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="轨旁 AP" name="aps">
          <div class="filter-bar">
            <el-input v-model="store.apFilters.query" clearable placeholder="AP 名称 / 点位 / MAC / IP" @keyup.enter="store.applyApFilters" />
            <el-input v-model="store.apFilters.station" clearable placeholder="归属站点" />
            <el-input v-model="store.apFilters.section" clearable placeholder="归属区间" />
            <el-select v-model="store.apFilters.line_side" clearable placeholder="线路方向"><el-option label="左线" value="左线" /><el-option label="右线" value="右线" /><el-option label="出段线" value="出段线" /><el-option label="入段线" value="入段线" /></el-select>
            <el-select v-model="store.apFilters.has_issue" clearable placeholder="数据质量"><el-option label="只看异常" :value="true" /><el-option label="只看正常" :value="false" /></el-select>
            <el-button type="primary" @click="store.applyApFilters">应用筛选</el-button>
          </div>
          <el-table :data="store.aps" stripe height="calc(100vh - 430px)" empty-text="暂无轨旁 AP 扩展资料">
            <el-table-column label="AP 名称 / 点位" min-width="170" fixed="left"><template #default="scope">{{ scope.row.name || scope.row.point_code || '--' }}</template></el-table-column>
            <el-table-column prop="mac" label="AP MAC" min-width="150" />
            <el-table-column prop="management_ip" label="管理 IP" min-width="125"><template #default="scope">{{ display(scope.row.management_ip) }}</template></el-table-column>
            <el-table-column prop="station" label="站点" min-width="130"><template #default="scope">{{ display(scope.row.station) }}</template></el-table-column>
            <el-table-column prop="section" label="区间" min-width="170"><template #default="scope">{{ display(scope.row.section) }}</template></el-table-column>
            <el-table-column label="里程" min-width="120"><template #default="scope">{{ scope.row.mileage.normalized || scope.row.mileage.raw || '--' }}</template></el-table-column>
            <el-table-column prop="line_side" label="线路方向" width="110"><template #default="scope">{{ display(scope.row.line_side) }}</template></el-table-column>
            <el-table-column label="FIT-AP 状态" width="120"><template #default="scope"><el-tag :type="stateType(scope.row.runtime.fit_ap_status)">{{ scope.row.runtime.fit_ap_status }}</el-tag></template></el-table-column>
            <el-table-column label="关联 MR" min-width="150"><template #default="scope">{{ display(scope.row.runtime.mesh_related_name) }}</template></el-table-column>
            <el-table-column label="光衰" width="105"><template #default="scope"><el-tag :type="stateType(scope.row.runtime.optical_status)">{{ scope.row.runtime.optical_status }}</el-tag></template></el-table-column>
            <el-table-column prop="source_file" label="数据来源" min-width="150" show-overflow-tooltip />
            <el-table-column label="问题" width="90"><template #default="scope"><el-tag v-if="scope.row.issue_count" :type="issueType(scope.row.highest_issue_severity)">{{ scope.row.issue_count }}</el-tag><span v-else>--</span></template></el-table-column>
            <el-table-column label="跳转" width="190" fixed="right"><template #default="scope"><el-button link type="primary" @click="openApAc(scope.row)">FIT-AP</el-button><el-button link type="primary" @click="openApMesh(scope.row)">Mesh-Link</el-button></template></el-table-column>
          </el-table>
          <el-pagination background layout="total, prev, pager, next, sizes" :total="store.apTotal" :current-page="store.apFilters.page" :page-size="store.apFilters.page_size" :page-sizes="[20, 50, 100, 200]" @current-change="store.setApPage" @size-change="(size: number) => { store.apFilters.page_size = size; store.applyApFilters() }" />
        </el-tab-pane>

        <el-tab-pane label="列车与车载 MR" name="vehicles">
          <el-tabs v-model="vehicleTab" type="card">
            <el-tab-pane label="列车" name="trains">
              <el-table :data="store.trains" stripe height="calc(100vh - 365px)" empty-text="暂无列车资料">
                <el-table-column prop="train_no" label="列车编号" min-width="120" />
                <el-table-column prop="name" label="列车名称" min-width="150" />
                <el-table-column prop="mr_count" label="MR 数量" width="100" />
                <el-table-column label="MR 角色" min-width="130"><template #default="scope">{{ scope.row.roles.join(' / ') || '--' }}</template></el-table-column>
                <el-table-column label="最近 Mesh-Link" width="140"><template #default="scope"><el-tag :type="stateType(scope.row.latest_mesh_status)">{{ scope.row.latest_mesh_status }}</el-tag></template></el-table-column>
                <el-table-column prop="latest_session_id" label="最近 Online MR" min-width="210"><template #default="scope">{{ display(scope.row.latest_session_id) }}</template></el-table-column>
                <el-table-column label="问题" width="90"><template #default="scope">{{ scope.row.issue_count || '--' }}</template></el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="车载 MR" name="mrs">
              <div class="filter-bar">
                <el-input v-model="store.mrFilters.query" clearable placeholder="MR 名称 / IP / MAC / 设备 ID" @keyup.enter="store.applyMrFilters" />
                <el-input v-model="store.mrFilters.train" clearable placeholder="列车编号" />
                <el-select v-model="store.mrFilters.mr_role" clearable placeholder="MR 角色"><el-option label="CT" value="CT" /><el-option label="TC" value="TC" /></el-select>
                <el-button type="primary" @click="store.applyMrFilters">应用筛选</el-button>
              </div>
              <el-table :data="store.mrs" stripe height="calc(100vh - 430px)" empty-text="暂无车载 MR 资料">
                <el-table-column prop="name" label="MR 名称" min-width="170" />
                <el-table-column prop="device_id" label="设备 ID" width="100" />
                <el-table-column prop="train_id" label="所属列车" min-width="120" />
                <el-table-column prop="role" label="角色" width="80" />
                <el-table-column prop="management_ip" label="管理 IP" min-width="125" />
                <el-table-column prop="mac" label="MAC" min-width="150"><template #default="scope">{{ display(scope.row.mac) }}</template></el-table-column>
                <el-table-column label="协议 / 端口" min-width="120"><template #default="scope">{{ display(scope.row.protocol) }} / {{ display(scope.row.port) }}</template></el-table-column>
                <el-table-column label="Mesh-Link" width="120"><template #default="scope"><el-tag :type="stateType(scope.row.runtime.mesh_status)">{{ scope.row.runtime.mesh_status }}</el-tag></template></el-table-column>
                <el-table-column label="当前轨旁 AP" min-width="160"><template #default="scope">{{ display(scope.row.runtime.mesh_related_name) }}</template></el-table-column>
                <el-table-column label="跳转" width="190"><template #default="scope"><el-button link type="primary" @click="openMrMesh(scope.row)">Mesh-Link</el-button><el-button link type="primary" @click="openMrSession(scope.row)">Online MR</el-button></template></el-table-column>
              </el-table>
              <el-pagination background layout="total, prev, pager, next, sizes" :total="store.mrTotal" :current-page="store.mrFilters.page" :page-size="store.mrFilters.page_size" :page-sizes="[20, 50, 100, 200]" @current-change="store.setMrPage" @size-change="(size: number) => { store.mrFilters.page_size = size; store.applyMrFilters() }" />
            </el-tab-pane>
          </el-tabs>
        </el-tab-pane>

        <el-tab-pane label="数据质量问题" name="issues">
          <div class="filter-bar">
            <el-input v-model="store.issueFilters.query" clearable placeholder="实体 / 错误码 / 说明" @keyup.enter="store.applyIssueFilters" />
            <el-select v-model="store.issueFilters.blocking_only" clearable placeholder="阻断状态"><el-option label="只看阻断问题" :value="true" /><el-option label="排除阻断问题" :value="false" /></el-select>
            <el-select v-model="store.issueFilters.needs_confirmation_only" clearable placeholder="人工确认"><el-option label="只看待人工确认" :value="true" /><el-option label="无需人工确认" :value="false" /></el-select>
            <el-button type="primary" @click="store.applyIssueFilters">应用筛选</el-button>
          </div>
          <div class="issue-stats">
            <el-tag v-for="item in issueCodeStats" :key="item[0]" type="info">{{ item[0] }}：{{ item[1] }}</el-tag>
          </div>
          <el-table :data="store.issueGroups" stripe height="calc(100vh - 460px)" empty-text="当前没有数据质量问题">
            <el-table-column type="expand"><template #default="scope"><el-table :data="scope.row.issues" size="small"><el-table-column prop="field_name" label="字段" width="150" /><el-table-column prop="message" label="字段问题" min-width="260" /><el-table-column prop="suggested_action" label="建议处理" min-width="260" /></el-table></template></el-table-column>
            <el-table-column label="状态" width="110"><template #default="scope"><el-tag v-if="scope.row.blocking" type="danger">阻断</el-tag><el-tag v-else-if="scope.row.needs_confirmation" type="warning">待确认</el-tag><el-tag v-else type="info">提示</el-tag></template></el-table-column>
            <el-table-column prop="entity_type" label="实体类型" width="110" />
            <el-table-column prop="display_name" label="实体" min-width="180" />
            <el-table-column prop="issue_count" label="问题数" width="90" />
            <el-table-column label="错误 / 警告 / 提示" width="160"><template #default="scope">{{ scope.row.error_count }} / {{ scope.row.warning_count }} / {{ scope.row.info_count }}</template></el-table-column>
            <el-table-column prop="suggested_action" label="建议处理" min-width="300" show-overflow-tooltip />
          </el-table>
          <el-pagination background layout="total, prev, pager, next" :total="store.issueGroupTotal" :current-page="store.issueFilters.page" :page-size="store.issueFilters.page_size" @current-change="store.setIssuePage" />
        </el-tab-pane>

        <el-tab-pane label="导入预览" name="preview">
          <el-alert title="当前仅支持校验和合并预览。正式写入功能默认关闭。" description="支持 XLSX、CSV、JSON；不会创建任务，不会保存正式导入文件，也不会自动覆盖正式身份。" type="warning" :closable="false" show-icon />
          <div class="preview-toolbar">
            <label class="file-picker"><el-icon><UploadFilled /></el-icon><span>{{ store.selectedFileName || '选择预览文件' }}</span><input type="file" accept=".xlsx,.csv,.json" @change="handleFile" /></label>
            <span v-if="store.importPreview">{{ formatBytes(store.importPreview.file_size) }} · {{ store.importPreview.template_type }} · 置信度 {{ store.importPreview.confidence_score }}</span>
          </div>
          <div v-if="store.importPreview" class="preview-summary">
            <article><span>解析行数</span><strong>{{ store.importPreview.total_rows }}</strong></article>
            <article class="normal"><span>有效行</span><strong>{{ store.importPreview.valid_rows }}</strong></article>
            <article class="danger"><span>错误</span><strong>{{ store.importPreview.error_count }}</strong></article>
            <article class="warning"><span>警告</span><strong>{{ store.importPreview.warning_count }}</strong></article>
          </div>
          <div v-if="store.importPreview" class="preview-actions">
            <el-radio-group v-model="previewFilter" class="preview-filter"><el-radio-button value="all">全部</el-radio-button><el-radio-button value="CREATE">CREATE</el-radio-button><el-radio-button value="UPDATE">UPDATE</el-radio-button><el-radio-button value="UNCHANGED">UNCHANGED</el-radio-button><el-radio-button value="CONFLICT">CONFLICT</el-radio-button><el-radio-button value="NEEDS_CONFIRMATION">待人工确认</el-radio-button></el-radio-group>
            <el-button type="primary" disabled>正式写入未启用</el-button>
          </div>
          <el-table v-loading="store.previewLoading" :data="mergeRows" stripe height="calc(100vh - 520px)" empty-text="请选择文件生成合并预览">
            <el-table-column prop="row_number" label="行号" width="80" />
            <el-table-column label="处理结果" width="150"><template #default="scope"><el-tag :type="mergeType(scope.row.result)">{{ scope.row.result }}</el-tag></template></el-table-column>
            <el-table-column label="来源身份" min-width="210"><template #default="scope">{{ display(scope.row.source_identity.ap_name) }} / {{ display(scope.row.source_identity.ap_mac) }}</template></el-table-column>
            <el-table-column prop="matched_entity_name" label="正式实体" min-width="170"><template #default="scope">{{ display(scope.row.matched_entity_name) }}</template></el-table-column>
            <el-table-column prop="match_method" label="匹配方式" width="140" />
            <el-table-column label="字段差异" min-width="320" show-overflow-tooltip><template #default="scope">{{ diffSummary(scope.row.field_diffs) }}</template></el-table-column>
            <el-table-column prop="conflict_summary" label="冲突" min-width="240"><template #default="scope">{{ display(scope.row.conflict_summary) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="关联运行状态" name="relations">
          <el-table :data="store.relations" stripe height="calc(100vh - 330px)" empty-text="暂无 Mesh-Link 关联快照">
            <el-table-column prop="train_no" label="列车" width="100" />
            <el-table-column prop="mr_name" label="车载 MR" min-width="170" />
            <el-table-column prop="ap_name" label="当前轨旁 AP" min-width="180" />
            <el-table-column prop="station" label="站点" min-width="140"><template #default="scope">{{ display(scope.row.station) }}</template></el-table-column>
            <el-table-column prop="section" label="区间" min-width="180"><template #default="scope">{{ display(scope.row.section) }}</template></el-table-column>
            <el-table-column label="状态" width="110"><template #default="scope"><el-tag :type="stateType(scope.row.status)">{{ scope.row.status }}</el-tag></template></el-table-column>
            <el-table-column prop="updated_at" label="最近更新" min-width="180" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>
  </section>
</template>

<style scoped>
.rail-base-data { max-width: 1760px; margin: 0 auto; }
.page-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin: 18px 0; }
.page-toolbar h2 { margin: 0; color: #172033; }
.page-toolbar p { margin: 5px 0 0; color: #748197; font-size: 12px; }
.page-error { margin-bottom: 14px; }
.content-card { min-width: 0; padding: 0 18px 18px; background: #fff; border: 1px solid #dfe7f1; border-radius: 10px; }
.summary-grid, .preview-summary { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)); gap: 12px; margin: 8px 0 18px; }
.summary-grid article, .preview-summary article { min-height: 86px; padding: 14px 16px; background: #f6f8fb; border-left: 3px solid #8192a8; border-radius: 8px; }
.summary-grid article.normal, .preview-summary article.normal { border-left-color: #35a873; }
.summary-grid article.warning, .preview-summary article.warning { border-left-color: #d99b28; }
.summary-grid article.danger, .preview-summary article.danger { border-left-color: #d95656; }
.summary-grid span, .preview-summary span { display: block; color: #738096; font-size: 12px; }
.summary-grid strong, .preview-summary strong { display: block; margin-top: 8px; color: #172033; font-size: 25px; }
.meta-block { margin-top: 12px; }
.filter-bar { display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)) auto; gap: 10px; margin: 8px 0 14px; }
.el-pagination { justify-content: flex-end; margin-top: 14px; }
.preview-toolbar { display: flex; align-items: center; gap: 16px; margin: 16px 0; color: #718096; font-size: 12px; }
.file-picker { display: inline-flex; align-items: center; gap: 8px; padding: 9px 14px; color: #fff; background: #2387b8; border-radius: 6px; cursor: pointer; }
.file-picker input { display: none; }
.preview-summary { grid-template-columns: repeat(4, minmax(140px, 1fr)); }
.preview-filter { margin-bottom: 12px; }
.preview-actions { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.issue-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.row-issues { display: flex; flex-wrap: wrap; gap: 5px; }
@media (max-width: 1360px) {
  .summary-grid { grid-template-columns: repeat(3, 1fr); }
  .filter-bar { grid-template-columns: repeat(3, 1fr); }
}
</style>
