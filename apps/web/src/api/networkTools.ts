import { apiRequest } from './client'
import type { TcpPortTestRequest, TcpPortTestResponse } from '../types/networkTools'

export function startTcpPortTest(value: TcpPortTestRequest): Promise<TcpPortTestResponse> {
  return apiRequest<TcpPortTestResponse>('/api/network-tools/tcp-port-test', {
    method: 'POST',
    body: JSON.stringify(value),
  })
}
