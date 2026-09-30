export type RunStatus =
  | 'queued'
  | 'running'
  | 'stopping'
  | 'finished'
  | 'failed'
  | 'stopped'

export type LoadMode = 'users' | 'throughput'

export interface ScenarioInfo {
  id: string
  name: string
  description: string
  host_hint: string
  default_paths: string[]
  supports_static_assets: boolean
}

export interface EndpointStat {
  name: string
  method: string
  num_requests: number
  num_failures: number
  current_rps: number
  avg_response_time: number
  min_response_time: number | null
  max_response_time: number | null
  p50: number | null
  p95: number | null
  p99: number | null
}

export interface MetricsSnapshot {
  ts: string
  user_count: number
  total_rps: number
  fail_ratio: number
  total_requests: number
  total_failures: number
  p50: number | null
  p95: number | null
  p99: number | null
  endpoints: EndpointStat[]
}

export interface RunSummary {
  id: string
  scenario_id: string
  scenario_name: string
  host: string
  load_mode: LoadMode
  users: number
  spawn_rate: number
  target_rps: number | null
  duration: string
  workers: number
  status: RunStatus
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  latest_metrics: MetricsSnapshot | null
}

export interface RunDetail extends RunSummary {
  paths: string[]
  headers: Record<string, string>
  follow_static_assets: boolean
  history: MetricsSnapshot[]
  report_path: string | null
  word_report_path: string | null
  config: Record<string, unknown>
}

export interface RunCreate {
  scenario_id: string
  host: string
  load_mode: LoadMode
  users: number
  spawn_rate: number
  target_rps?: number | null
  duration: string
  workers: number
  paths: string[]
  headers: Record<string, string>
  follow_static_assets: boolean
}

export interface GuardrailsInfo {
  allowed_hosts: string[]
  max_users: number
  max_spawn_rate: number
  max_duration_seconds: number
  max_workers: number
  max_target_rps: number
}

export interface DiscoverPathsRequest {
  host: string
  start_path?: string
  max_pages?: number
}

export interface DiscoveredPathItem {
  path: string
  kind: 'page' | 'api' | 'asset' | string
  status_code: number
  content_type: string
}

export interface DiscoverPathsResponse {
  host: string
  start_path: string
  paths: string[]
  items: DiscoveredPathItem[]
  fetched_pages: number
  warnings: string[]
}

export interface LocustProcessMetrics {
  pid: number
  name: string
  status: string
  cpu_percent: number
  memory_rss_mb: number
  num_threads: number
}

export interface SystemMetrics {
  ts: string
  hostname: string
  cpu_percent: number
  cpu_count: number
  memory_percent: number
  memory_used_gb: number
  memory_total_gb: number
  load_avg_1: number | null
  load_avg_5: number | null
  load_avg_15: number | null
  net_sent_mbps: number
  net_recv_mbps: number
  locust: LocustProcessMetrics | null
  locust_processes: LocustProcessMetrics[]
  locust_process_count: number
  locust_cpu_total_percent: number
  bottleneck: string
  hints: string[]
}

const API_BASE = import.meta.env.VITE_API_BASE?.replace(/\/$/, '') || ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { headers: initHeaders, ...rest } = init || {}
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      'Content-Type': 'application/json',
      ...(initHeaders || {}),
    },
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || JSON.stringify(body)
    } catch {
      // ignore
    }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>('/api/health'),
  guardrails: () => request<GuardrailsInfo>('/api/guardrails'),
  scenarios: () => request<ScenarioInfo[]>('/api/scenarios'),
  runs: () => request<RunSummary[]>('/api/runs'),
  getRun: (id: string) => request<RunDetail>(`/api/runs/${id}`),
  createRun: (payload: RunCreate) =>
    request<RunDetail>('/api/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  stopRun: (id: string) =>
    request<RunDetail>(`/api/runs/${id}/stop`, { method: 'POST' }),
  discoverPaths: (payload: DiscoverPathsRequest, init?: RequestInit) =>
    request<DiscoverPathsResponse>('/api/discover-paths', {
      method: 'POST',
      body: JSON.stringify(payload),
      ...(init || {}),
    }),
  systemMetrics: () => request<SystemMetrics>('/api/system/metrics'),
  eventsUrl: (id: string) => `${API_BASE}/api/runs/${id}/events`,
  systemEventsUrl: () => `${API_BASE}/api/system/events`,
  wordReportUrl: (id: string) => `${API_BASE}/api/runs/${id}/report.docx`,
}
