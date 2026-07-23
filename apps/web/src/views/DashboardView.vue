<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CircleCheckFilled, InfoFilled, Lock, WarningFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

import { getDeviceCompatibilitySummary } from '../api/deviceCompatibility'
import { findNavigation } from '../navigation/registry'
import type { DeviceCompatibilitySummary } from '../types/deviceCompatibility'

type DashboardSectionTone = 'success' | 'info' | 'warning' | 'neutral'

interface DashboardSection {
  title: string
  tag: string[]
  tone: DashboardSectionTone
  icon: unknown
  lead?: string
  body: string[]
}

const router = useRouter()
const navigationError = ref('')
const compatibility = ref<DeviceCompatibilitySummary | null>(null)
const compatibilityError = ref('')

const compatibilityBody = computed(() => {
  const summary = compatibility.value
  const platforms = summary?.platforms?.length ? summary.platforms.join(' / ') : 'Comware V7 / V9'
  const roles = summary?.roles?.length ? summary.roles.join('、') : '无线控制器、交换机、车载 MR（Cloud AP）'
  return [
    `当前代码内置兼容基线主要面向 H3C ${platforms} 设备，覆盖 ${roles}。`,
    '不同设备型号、软件版本和项目配置可能存在命令、字段及返回格式差异。未经过实际设备验证的型号或版本，不保证可以直接使用全部采集和分析功能。',
    summary?.disclaimer || '本地扫描候选不会显示到普通用户首页；已登记基线也不等于所有型号和 Release 均已完成现场验证。',
    '软件涉及的设备查询、采集和受控配置命令，请进入“命令说明”查看。',
  ]
})

const sections = computed<DashboardSection[]>(() => [
  {
    title: '已重点完善的功能',
    tag: ['重点完善'],
    tone: 'success',
    icon: CircleCheckFilled,
    lead: '目前已重点完善并可正常使用的功能包括：',
    body: [
      '设备管理；',
      '设备文件下载；',
      '配置采集与配置下载；',
      '轨旁 AP 业务中的光衰采集、关联与查看。',
      '实际可用范围仍受设备型号、软件版本、现场网络和项目配置影响。',
    ],
  },
  {
    title: '当前设备适配范围',
    tag: ['V7 / V9', 'H3C', '车载 MR'],
    tone: 'info',
    icon: InfoFilled,
    body: compatibilityBody.value,
  },
  {
    title: '测试功能与报告免责声明',
    tag: ['测试中', '仅供参考'],
    tone: 'warning',
    icon: WarningFilled,
    lead: '除上述已重点完善的功能外，当前页面中的其他功能仍可能处于开发、联调、测试或设计阶段。',
    body: [
      'MR 原始日志分析报告、MR 离线分析报告及相关分析功能仍在持续设计中，其中使用的分析算法、异常判定规则、阈值、统计口径、图表和报告结构仍可能调整。',
      '相关阈值、异常判断、统计结果、图表和结论，不代表正式检测结果、正式分析结论、项目验收结论或正式交付报告。',
      '在相关规则未经项目确认、现场验证及人工复核前，不应直接用于工程验收、质量判定、故障定责或其他正式决策。',
    ],
  },
  {
    title: '设备操作安全说明',
    tag: ['受控操作'],
    tone: 'neutral',
    icon: Lock,
    body: [
      'NetConsole 主要用于设备信息采集、状态查看、文件获取、配置采集和无线数据分析。',
      '本软件不提供删除设备、重启设备等高风险设备操作命令，也不向 Web 页面开放任意命令执行能力。',
      '软件中涉及的受控配置操作，仅允许执行程序内预先定义、参数受限且用途明确的固定操作。具体命令及用途以“命令说明”页面为准。',
    ],
  },
])

function resolveNavigationTarget(navigationId: string, fallbackName: string): { name: string } | { path: string } {
  const entry = findNavigation(navigationId)
  if (entry?.route_name) return { name: entry.route_name }
  if (entry?.route_path) return { path: entry.route_path }
  return { name: fallbackName }
}

async function openNavigation(navigationId: string, fallbackName: string, message: string): Promise<void> {
  navigationError.value = ''
  try {
    await router.push(resolveNavigationTarget(navigationId, fallbackName))
  } catch (reason) {
    navigationError.value = message
    console.warn(`Dashboard navigation failed: ${navigationId}`, reason)
  }
}

onMounted(async () => {
  try {
    compatibility.value = await getDeviceCompatibilitySummary()
  } catch (reason) {
    compatibilityError.value = reason instanceof Error ? reason.message : '设备兼容性基线暂时不可用'
  }
})
</script>

<template>
  <section class="dashboard-page">
    <header class="dashboard-header">
      <div>
        <p class="dashboard-eyebrow">当前版本功能状态</p>
        <h1>NetConsole</h1>
        <p class="dashboard-subtitle">当前首页仅展示已重点完善功能、适配范围、测试免责声明和设备操作安全边界。</p>
      </div>
    </header>

    <el-alert v-if="navigationError" type="warning" :title="navigationError" show-icon :closable="false" class="dashboard-alert" />
    <el-alert v-if="compatibilityError" type="warning" :title="compatibilityError" show-icon :closable="false" class="dashboard-alert" />

    <div class="dashboard-grid">
      <article v-for="section in sections" :key="section.title" class="dashboard-card" :class="`dashboard-card--${section.tone}`">
        <div class="dashboard-card-header">
          <el-icon class="dashboard-card-icon"><component :is="section.icon" /></el-icon>
          <div class="dashboard-card-heading">
            <div class="dashboard-card-title-row">
              <h2>{{ section.title }}</h2>
              <el-tag v-for="item in section.tag" :key="item" :type="section.tone === 'neutral' ? 'info' : section.tone" effect="light" round>{{ item }}</el-tag>
            </div>
            <p v-if="section.lead">{{ section.lead }}</p>
          </div>
        </div>
        <div class="dashboard-card-body">
          <p v-for="line in section.body" :key="line">{{ line }}</p>
        </div>
      </article>
    </div>

    <footer class="dashboard-actions">
      <el-button type="primary" @click="openNavigation('command-reference', 'command-reference', '命令说明页面暂时无法打开，请从左侧菜单进入。')">查看命令说明</el-button>
      <el-button @click="openNavigation('tasks', 'tasks', '任务中心暂时无法打开，请从左侧菜单进入。')">打开任务中心</el-button>
    </footer>
  </section>
</template>

<style scoped>
.dashboard-page{display:flex;flex-direction:column;gap:16px;min-width:0}
.dashboard-header{padding:22px 24px;background:var(--nc-bg-card);border:1px solid var(--nc-border-light);border-radius:var(--nc-radius-lg);box-shadow:var(--nc-shadow-card)}
.dashboard-eyebrow{margin:0 0 6px;color:var(--nc-text-secondary);font-size:12px;font-weight:700;letter-spacing:0}
.dashboard-header h1{margin:0;color:var(--nc-text-primary);font-size:28px;line-height:1.2}
.dashboard-subtitle{max-width:780px;margin:8px 0 0;color:var(--nc-text-secondary);line-height:1.6}
.dashboard-actions{display:flex;flex-wrap:wrap;justify-content:flex-start;gap:10px}
.dashboard-alert{border-radius:var(--nc-radius-base)}
.dashboard-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.dashboard-card{display:flex;flex-direction:column;gap:16px;min-width:0;padding:20px 20px 18px;background:var(--nc-bg-card);border:1px solid var(--nc-border-light);border-radius:var(--nc-radius-lg);box-shadow:var(--nc-shadow-card)}
.dashboard-card-header{display:flex;gap:14px;min-width:0}
.dashboard-card-icon{flex:none;display:grid;place-items:center;width:36px;height:36px;color:var(--nc-text-inverse);border-radius:10px}
.dashboard-card--success .dashboard-card-icon{background:var(--nc-success)}
.dashboard-card--info .dashboard-card-icon{background:var(--nc-info)}
.dashboard-card--warning .dashboard-card-icon{background:var(--nc-warning)}
.dashboard-card--neutral .dashboard-card-icon{background:var(--nc-primary)}
.dashboard-card-heading{min-width:0;flex:1}
.dashboard-card-title-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.dashboard-card h2{margin:0;color:var(--nc-text-primary);font-size:18px;line-height:1.3}
.dashboard-card-heading p{margin:8px 0 0;color:var(--nc-text-secondary);line-height:1.6}
.dashboard-card-body{display:flex;flex-direction:column;gap:8px}
.dashboard-card-body p{margin:0;color:var(--nc-text-primary);line-height:1.7}
.dashboard-card--warning .dashboard-card-body p:last-child,
.dashboard-card--neutral .dashboard-card-body p:last-child,
.dashboard-card--info .dashboard-card-body p:last-child,
.dashboard-card--success .dashboard-card-body p:last-child{color:var(--nc-text-secondary)}
.dashboard-card--neutral{border-top:3px solid var(--nc-primary)}
.dashboard-card--info{border-top:3px solid var(--nc-info)}
.dashboard-card--warning{border-top:3px solid var(--nc-warning)}
.dashboard-card--success{border-top:3px solid var(--nc-success)}
:deep(.el-tag){margin-left:0}

@media (max-width: 1100px){
  .dashboard-grid{grid-template-columns:1fr}
}
</style>
