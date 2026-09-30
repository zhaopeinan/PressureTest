import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MetricsSnapshot } from '../api/client'

interface Props {
  history: MetricsSnapshot[]
}

function formatTime(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleTimeString()
}

export function MetricsChart({ history }: Props) {
  const data = history.map((h) => ({
    time: formatTime(h.ts),
    rps: Number(h.total_rps.toFixed(2)),
    p95: h.p95 ?? null,
    failPct: Number((h.fail_ratio * 100).toFixed(2)),
    users: h.user_count,
  }))

  if (data.length === 0) {
    return <div className="muted">等待指标数据…</div>
  }

  return (
    <div className="chart-wrap">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid stroke="#2d3c4c" strokeDasharray="3 3" />
          <XAxis dataKey="time" stroke="#93a4b5" minTickGap={24} />
          <YAxis yAxisId="left" stroke="#93a4b5" />
          <YAxis yAxisId="right" orientation="right" stroke="#93a4b5" />
          <Tooltip
            contentStyle={{
              background: '#172029',
              border: '1px solid #2d3c4c',
              borderRadius: 8,
            }}
          />
          <Legend />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="rps"
            name="RPS"
            stroke="#3d8bfd"
            dot={false}
            strokeWidth={2}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="p95"
            name="p95 (ms)"
            stroke="#2bb673"
            dot={false}
            strokeWidth={2}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="failPct"
            name="失败率 %"
            stroke="#e35d6a"
            dot={false}
            strokeWidth={2}
          />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="users"
            name="用户数"
            stroke="#e0a24a"
            dot={false}
            strokeWidth={1.5}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
