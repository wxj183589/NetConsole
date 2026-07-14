import type { TrafficExecutionTargetRequest, TrafficRun } from './traffic'

export interface TcpPortTestRequest {
  execution_target: TrafficExecutionTargetRequest
  target: string
  port: number
  interval_ms: number
  timeout_ms: number
  count: number
}

export interface TcpPortTestResponse {
  run: TrafficRun
}
