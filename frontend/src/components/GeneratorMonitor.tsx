import type { SystemMetrics } from '../api/client'

interface Props {
  metrics: SystemMetrics | null
}

function levelClass(percent: number): string {
  if (percent >= 85) return 'hot'
  if (percent >= 65) return 'warm'
  return 'cool'
}

function bottleneckLabel(code: string): string {
  switch (code) {
    case 'generator_cpu':
      return '发压机 CPU 可能饱和'
    case 'generator_memory':
      return '发压机内存紧张'
    case 'locust_process':
      return 'Locust 进程接近上限'
    case 'headroom':
      return '发压机仍有余量'
    case 'balanced':
      return '负载中等'
    default:
      return '空闲 / 未压测'
  }
}

export function GeneratorMonitor({ metrics }: Props) {
  if (!metrics) {
    return (
      <section className="generator-monitor">
        <h2>发压机资源</h2>
        <div className="muted">正在读取本机 CPU / 内存…</div>
      </section>
    )
  }

  const cpu = metrics.cpu_percent
  const mem = metrics.memory_percent
  const locustCpuTotal = metrics.locust_cpu_total_percent ?? metrics.locust?.cpu_percent ?? null
  const procCount = metrics.locust_process_count ?? (metrics.locust ? 1 : 0)

  return (
    <section className="generator-monitor">
      <div className="generator-head">
        <h2>发压机资源</h2>
        <span className={`status-pill ${metrics.bottleneck === 'headroom' ? 'finished' : metrics.bottleneck.includes('generator') || metrics.bottleneck === 'locust_process' ? 'failed' : 'running'}`}>
          {bottleneckLabel(metrics.bottleneck)}
        </span>
      </div>
      <p className="muted generator-host">
        {metrics.hostname} · {metrics.cpu_count} 逻辑核 ·{' '}
        {metrics.memory_used_gb}/{metrics.memory_total_gb} GB
        {procCount > 0 ? ` · Locust ${procCount} 进程` : ''}
      </p>

      <div className="meter">
        <div className="meter-label">
          <span>CPU</span>
          <span className="mono">{cpu.toFixed(1)}%</span>
        </div>
        <div className="meter-track">
          <div className={`meter-fill ${levelClass(cpu)}`} style={{ width: `${Math.min(cpu, 100)}%` }} />
        </div>
      </div>

      <div className="meter">
        <div className="meter-label">
          <span>内存</span>
          <span className="mono">{mem.toFixed(1)}%</span>
        </div>
        <div className="meter-track">
          <div className={`meter-fill ${levelClass(mem)}`} style={{ width: `${Math.min(mem, 100)}%` }} />
        </div>
      </div>

      {locustCpuTotal != null && procCount > 0 && (
        <div className="meter">
          <div className="meter-label">
            <span>Locust 合计 CPU（可超 100%）</span>
            <span className="mono">{locustCpuTotal.toFixed(1)}%</span>
          </div>
          <div className="meter-track">
            <div
              className={`meter-fill ${levelClass(Math.min(locustCpuTotal / Math.max(procCount, 1), 100))}`}
              style={{
                width: `${Math.min((locustCpuTotal / Math.max(metrics.cpu_count, 1)) * 100, 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      <div className="generator-grid">
        <div className="kpi mini">
          <div className="label">Load 1m</div>
          <div className="value">{metrics.load_avg_1 ?? '-'}</div>
        </div>
        <div className="kpi mini">
          <div className="label">上行 Mbps</div>
          <div className="value">{metrics.net_sent_mbps.toFixed(2)}</div>
        </div>
        <div className="kpi mini">
          <div className="label">下行 Mbps</div>
          <div className="value">{metrics.net_recv_mbps.toFixed(2)}</div>
        </div>
        <div className="kpi mini">
          <div className="label">Locust 内存</div>
          <div className="value">
            {procCount > 0
              ? `${(metrics.locust_processes || [metrics.locust].filter(Boolean))
                  .reduce((sum, p) => sum + (p?.memory_rss_mb || 0), 0)
                  .toFixed(0)}MB`
              : '-'}
          </div>
        </div>
      </div>

      {metrics.hints[0] && <p className="generator-hint">{metrics.hints[0]}</p>}
    </section>
  )
}
