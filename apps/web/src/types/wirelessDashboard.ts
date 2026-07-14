import type { AcAp, AcManagementSummary } from './acManagement'
import type { AcMeshLinkRecord, AcMeshLinkSummary } from './acMeshLink'
import type { AgentItem } from './agent'
import type { MeshAnalysisSession, MeshAnalysisSummary } from './meshAnalysis'
import type { OnlineMrSessionSummary } from './onlineMr'
import type { TrainCommunicationRow, TrainCommunicationSummary } from './trainCommunication'

export interface WirelessDashboardAlert {
  id: string; severity: string; category: string; title: string; message: string
  entity_id: string; detail_path: string; updated_at: string
}
export interface WirelessDashboardFreshnessItem {
  source: string; label: string; status: string; updated_at: string; age_seconds: number | null; message: string
}
export interface WirelessDashboardTask {
  id: string; type: string; name: string; status: string; progress: number; owner: string; executor: string
  device_name: string; mr_name: string; updated_time: string; error_summary: string; has_warning: boolean
}
export interface WirelessDashboardSummary {
  site_id: string; site_name: string; line_name: string
  ap_total: number; online_aps: number; offline_aps: number; unauthenticated_aps: number; optical_anomalies: number
  registered_trains: number; registered_mrs: number; online_mrs: number; offline_mrs: number; stale_mrs: number
  active_online_mr_sessions: number; agent_total: number; online_agents: number; running_tasks: number
  mesh_analysis_sessions: number; alert_total: number; critical_alerts: number; warning_alerts: number
  updated_at: string; data_version: string; cached: boolean
}
export interface WirelessDashboardInfrastructure {
  ac: AcManagementSummary; mesh_link: AcMeshLinkSummary; optical_anomalies: AcAp[]; current_links: AcMeshLinkRecord[]
}
export interface WirelessDashboardTrains { summary: TrainCommunicationSummary; items: TrainCommunicationRow[]; total: number }
export interface WirelessDashboardAlerts { items: WirelessDashboardAlert[]; total: number; critical: number; warning: number }
export interface WirelessDashboardFreshness { items: WirelessDashboardFreshnessItem[] }
export interface WirelessDashboardRecentOperations { tasks: WirelessDashboardTask[]; sessions: OnlineMrSessionSummary[] }
export interface WirelessDashboardAnalysis { summary: MeshAnalysisSummary; sessions: MeshAnalysisSession[] }
export interface WirelessDashboardAgents { items: AgentItem[]; total: number; online: number; offline: number; unknown: number }
export interface WirelessDashboard {
  summary: WirelessDashboardSummary; infrastructure: WirelessDashboardInfrastructure; trains: WirelessDashboardTrains
  alerts: WirelessDashboardAlerts; freshness: WirelessDashboardFreshness
  recent_operations: WirelessDashboardRecentOperations; analysis: WirelessDashboardAnalysis; agents: WirelessDashboardAgents
}
