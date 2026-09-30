import type { EndpointStat } from '../api/client'

interface Props {
  endpoints: EndpointStat[]
}

function fmt(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '-'
  return n.toFixed(digits)
}

export function EndpointTable({ endpoints }: Props) {
  if (!endpoints.length) {
    return <div className="muted">暂无 endpoint 统计</div>
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Method</th>
            <th>Name</th>
            <th>Requests</th>
            <th>Failures</th>
            <th>RPS</th>
            <th>Avg (ms)</th>
            <th>p95</th>
            <th>p99</th>
          </tr>
        </thead>
        <tbody>
          {endpoints.map((ep) => (
            <tr key={`${ep.method}-${ep.name}`}>
              <td className="mono">{ep.method}</td>
              <td className="mono">{ep.name}</td>
              <td>{ep.num_requests}</td>
              <td>{ep.num_failures}</td>
              <td>{fmt(ep.current_rps, 2)}</td>
              <td>{fmt(ep.avg_response_time)}</td>
              <td>{fmt(ep.p95)}</td>
              <td>{fmt(ep.p99)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
