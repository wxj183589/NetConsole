import { apiRequest } from './client'
import type {
  WirelessDashboard,
  WirelessDashboardAgents,
  WirelessDashboardAlerts,
  WirelessDashboardAnalysis,
  WirelessDashboardFreshness,
  WirelessDashboardInfrastructure,
  WirelessDashboardRecentOperations,
  WirelessDashboardSummary,
  WirelessDashboardTrains,
} from '../types/wirelessDashboard'

const root = '/api/rail-transit/wireless-dashboard'

export const getWirelessDashboard = (): Promise<WirelessDashboard> => apiRequest(root)
export const getWirelessDashboardSummary = (): Promise<WirelessDashboardSummary> => apiRequest(`${root}/summary`)
export const getWirelessDashboardInfrastructure = (): Promise<WirelessDashboardInfrastructure> => apiRequest(`${root}/infrastructure`)
export const getWirelessDashboardTrains = (): Promise<WirelessDashboardTrains> => apiRequest(`${root}/trains`)
export const getWirelessDashboardAlerts = (): Promise<WirelessDashboardAlerts> => apiRequest(`${root}/alerts`)
export const getWirelessDashboardFreshness = (): Promise<WirelessDashboardFreshness> => apiRequest(`${root}/freshness`)
export const getWirelessDashboardRecentOperations = (): Promise<WirelessDashboardRecentOperations> => apiRequest(`${root}/recent-operations`)
export const getWirelessDashboardAnalysis = (): Promise<WirelessDashboardAnalysis> => apiRequest(`${root}/analysis`)
export const getWirelessDashboardAgents = (): Promise<WirelessDashboardAgents> => apiRequest(`${root}/agents`)
