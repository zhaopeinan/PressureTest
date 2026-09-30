import { useEffect, useMemo, useRef, useState } from 'react'
import {
  api,
  type GuardrailsInfo,
  type LoadMode,
  type RunDetail,
  type RunSummary,
  type ScenarioInfo,
  type SystemMetrics,
} from './api/client'
import { EndpointTable } from './components/EndpointTable'
import { GeneratorMonitor } from './components/GeneratorMonitor'
import { MetricsChart } from './components/MetricsChart'
import './App.css'

function isActive(status: string | undefined): boolean {
  return status === 'queued' || status === 'running' || status === 'stopping'
}

function isTerminal(status: string | undefined): boolean {
  return status === 'finished' || status === 'stopped' || status === 'failed'
}

const HISTORY_PREVIEW_COUNT = 5

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioInfo[]>([])
  const [guardrails, setGuardrails] = useState<GuardrailsInfo | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selected, setSelected] = useState<RunDetail | null>(null)
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [discovering, setDiscovering] = useState(false)
  const discoverAbortRef = useRef<AbortController | null>(null)

  const [scenarioId, setScenarioId] = useState('bjtu_130th')
  const [host, setHost] = useState('https://130th.bjtu.edu.cn')
  const [loadMode, setLoadMode] = useState<LoadMode>('users')
  const [usersText, setUsersText] = useState('5')
  const [spawnRateText, setSpawnRateText] = useState('1')
  const [targetRpsText, setTargetRpsText] = useState('100')
  const [workers, setWorkers] = useState(4)
  const [duration, setDuration] = useState('30s')
  const [discoveredPaths, setDiscoveredPaths] = useState<string[]>(['/'])
  const [discoveredItems, setDiscoveredItems] = useState<
    { path: string; kind: string; status_code: number; content_type: string }[]
  >([{ path: '/', kind: 'page', status_code: 200, content_type: 'text/html' }])
  const [selectedPaths, setSelectedPaths] = useState<string[]>(['/'])
  const [customPathsText, setCustomPathsText] = useState('')
  const [discoverWarnings, setDiscoverWarnings] = useState<string[]>([])
  const [followStatic, setFollowStatic] = useState(false)
  const [copyHint, setCopyHint] = useState<string | null>(null)
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics | null>(null)
  const [downloadingReport, setDownloadingReport] = useState(false)
  const [historyExpanded, setHistoryExpanded] = useState(false)

  const activeRun = useMemo(
    () => runs.find((r) => isActive(r.status)) || null,
    [runs],
  )

  const visibleRuns = useMemo(() => {
    if (historyExpanded || runs.length <= HISTORY_PREVIEW_COUNT) return runs
    return runs.slice(0, HISTORY_PREVIEW_COUNT)
  }, [runs, historyExpanded])

  const selectedScenario = scenarios.find((s) => s.id === scenarioId)

  const selectedPathSet = useMemo(() => new Set(selectedPaths), [selectedPaths])

  async function refreshLists() {
    const [scenarioList, runList, guards] = await Promise.all([
      api.scenarios(),
      api.runs(),
      api.guardrails(),
    ])
    setScenarios(scenarioList)
    setRuns(runList)
    setGuardrails(guards)
    if (!scenarioList.find((s) => s.id === scenarioId) && scenarioList[0]) {
      setScenarioId(scenarioList[0].id)
    }
  }

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        await api.health()
        if (!cancelled) setApiOk(true)
        await refreshLists()
      } catch (err) {
        if (!cancelled) {
          setApiOk(false)
          setError(err instanceof Error ? err.message : String(err))
        }
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!selectedScenario) return
    setHost(selectedScenario.host_hint)
    const defaults = selectedScenario.default_paths.length
      ? selectedScenario.default_paths
      : ['/']
    setDiscoveredPaths(defaults)
    setDiscoveredItems(
      defaults.map((path) => ({
        path,
        kind: 'page',
        status_code: 200,
        content_type: 'text/html',
      })),
    )
    setSelectedPaths(defaults)
    setCustomPathsText('')
    setDiscoverWarnings([])
    setFollowStatic(false)
  }, [selectedScenario?.id])

  useEffect(() => {
    if (!apiOk) return
    let cancelled = false

    async function pull() {
      try {
        const m = await api.systemMetrics()
        if (!cancelled) setSystemMetrics(m)
      } catch {
        // keep last snapshot; badge/API health covers connectivity
      }
    }

    void pull()
    // Polling is more reliable than SSE through the Vite dev proxy.
    const timer = window.setInterval(pull, 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [apiOk])

  useEffect(() => {
    if (!selected || !isActive(selected.status)) return
    const runId = selected.id
    let cancelled = false

    async function pullRun() {
      try {
        const detail = await api.getRun(runId)
        if (cancelled) return
        setSelected(detail)
        setRuns((prev) => {
          const others = prev.filter((r) => r.id !== detail.id)
          return [detail, ...others]
        })
      } catch {
        // keep last snapshot; next tick retries
      }
    }

    void pullRun()
    // Polling avoids Vite proxy buffering / one-shot SSE close killing the board.
    const timer = window.setInterval(pullRun, 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [selected?.id, selected?.status])

  function collectPaths(): string[] {
    const custom = customPathsText
      .split('\n')
      .map((p) => p.trim())
      .filter(Boolean)
      .map((p) => (p.startsWith('/') ? p : `/${p}`))
    const merged = [...selectedPaths, ...custom]
    const seen = new Set<string>()
    const out: string[] = []
    for (const path of merged) {
      if (seen.has(path)) continue
      seen.add(path)
      out.push(path)
    }
    return out.length ? out : ['/']
  }

  function cancelDiscover() {
    discoverAbortRef.current?.abort()
    discoverAbortRef.current = null
    setDiscovering(false)
  }

  async function onDiscover() {
    setError(null)
    setDiscoverWarnings([])
    discoverAbortRef.current?.abort()
    const controller = new AbortController()
    discoverAbortRef.current = controller
    const timer = window.setTimeout(() => controller.abort(), 45000)
    setDiscovering(true)
    try {
      const result = await api.discoverPaths(
        {
          host,
          start_path: '/',
          max_pages: 2,
        },
        { signal: controller.signal },
      )
      const items =
        result.items?.length
          ? result.items
          : result.paths.map((path) => ({
              path,
              kind: 'page',
              status_code: 200,
              content_type: '',
            }))
      setDiscoveredItems(items)
      setDiscoveredPaths(items.map((i) => i.path))
      // Prefer reachable APIs + homepage by default; assets optional
      const preferred = items
        .filter((i) => i.kind === 'page' || i.kind === 'api')
        .map((i) => i.path)
      setSelectedPaths(preferred.length ? preferred : items.map((i) => i.path))
      setDiscoverWarnings(result.warnings || [])
      if (!items.length) {
        setError('未发现可访问路径。该站若是 SPA，请改选 API/静态资源或手动补充。')
      }
    } catch (err) {
      if (controller.signal.aborted) {
        setError('路径发现已取消或超时（45s）。可重试，或手动填写路径。')
      } else {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      window.clearTimeout(timer)
      if (discoverAbortRef.current === controller) {
        discoverAbortRef.current = null
      }
      setDiscovering(false)
    }
  }

  function togglePath(path: string) {
    setSelectedPaths((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path],
    )
  }

  function selectAllPaths() {
    setSelectedPaths([...discoveredPaths])
  }

  function clearSelectedPaths() {
    setSelectedPaths([])
  }

  async function copySelectedPaths() {
    const selectedSet = new Set(selectedPaths)
    const rows = discoveredItems.filter((item) => selectedSet.has(item.path))
    if (!rows.length) {
      setError('请先勾选要复制的路径')
      return
    }

    const lines = [
      `站点: ${host}`,
      `候选压测路径（已选 ${rows.length} 个，请确认是否需要压测）:`,
      ...rows.map((item) => `- [${item.kind}] ${item.path}`),
      '',
      '纯路径列表:',
      ...rows.map((item) => item.path),
    ]
    const text = lines.join('\n')

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.left = '-9999px'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      setCopyHint(`已复制 ${rows.length} 条路径`)
      window.setTimeout(() => setCopyHint(null), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : '复制失败')
    }
  }

  async function onStart() {
    setError(null)
    const paths = collectPaths()
    if (!paths.length) {
      setError('请至少选择一个页面路径')
      return
    }
    const users = Number(usersText)
    const spawnRate = Number(spawnRateText)
    const targetRps = Number(targetRpsText)
    if (!Number.isFinite(users) || users < 1) {
      setError('请填写有效的 Users')
      return
    }
    if (!Number.isFinite(spawnRate) || spawnRate <= 0) {
      setError('请填写有效的 Spawn rate')
      return
    }
    if (loadMode === 'throughput') {
      if (!Number.isFinite(targetRps) || targetRps <= 0) {
        setError('恒定吞吐模式请填写有效的目标 RPS')
        return
      }
      const maxRps = guardrails?.max_target_rps ?? 100000
      if (targetRps > maxRps) {
        setError(`目标 RPS 超过上限 ${maxRps}`)
        return
      }
    }
    setBusy(true)
    try {
      const run = await api.createRun({
        scenario_id: scenarioId,
        host,
        load_mode: loadMode,
        users,
        spawn_rate: spawnRate,
        target_rps: loadMode === 'throughput' ? targetRps : null,
        duration,
        workers,
        paths,
        headers: { 'User-Agent': 'PressureTest-Locust/0.1' },
        follow_static_assets: followStatic,
      })
      setSelected(run)
      await refreshLists()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function onStop() {
    const id = selected?.id || activeRun?.id
    if (!id) return
    setBusy(true)
    setError(null)
    try {
      const run = await api.stopRun(id)
      setSelected(run)
      await refreshLists()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function openRun(id: string) {
    setError(null)
    try {
      const run = await api.getRun(id)
      setSelected(run)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function onDownloadWordReport() {
    if (!selected || !isTerminal(selected.status)) return
    setDownloadingReport(true)
    setError(null)
    try {
      const res = await fetch(api.wordReportUrl(selected.id))
      if (!res.ok) {
        const text = await res.text()
        let detail = text
        try {
          const parsed = JSON.parse(text) as { detail?: string }
          detail = parsed.detail || text
        } catch {
          // keep raw text
        }
        throw new Error(detail || `下载失败 (${res.status})`)
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `pressure-test-${selected.id}.docx`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDownloadingReport(false)
    }
  }

  const metrics = selected?.latest_metrics

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>PressureTest</h1>
          <p>本机 Locust 压测工作台 · 可插拔场景</p>
        </div>
        <div className={`badge ${apiOk ? 'ok' : apiOk === false ? 'bad' : ''}`}>
          API {apiOk === null ? '检测中…' : apiOk ? '已连接' : '不可用'}
        </div>
      </header>

      <div className="notice">
        仅对自有或已授权系统发起压测。默认白名单：
        {guardrails?.allowed_hosts.join(', ') || '130th.bjtu.edu.cn'}
        。并发上限 {guardrails?.max_users ?? 50000}，时长上限{' '}
        {Math.floor((guardrails?.max_duration_seconds ?? 7200) / 60)} 分钟，
        Workers 上限 {guardrails?.max_workers ?? 8}。
      </div>

      <div className="layout">
        <aside className="panel">
          <h2>配置与启动</h2>

          <div className="field">
            <label>场景</label>
            <select
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              disabled={!!activeRun}
            >
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>

          {selectedScenario && (
            <p className="muted" style={{ marginTop: -4, marginBottom: 12 }}>
              {selectedScenario.description}
            </p>
          )}

          <div className="field">
            <label>Host</label>
            <input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              disabled={!!activeRun}
            />
          </div>

          <div className="field">
            <label>负载模式</label>
            <select
              value={loadMode}
              onChange={(e) => setLoadMode(e.target.value as LoadMode)}
              disabled={!!activeRun}
            >
              <option value="users">恒定用户（Users）</option>
              <option value="throughput">恒定吞吐（目标 RPS）</option>
            </select>
          </div>
          <p className="muted path-hint" style={{ marginTop: -4 }}>
            {loadMode === 'users'
              ? '固定并发用户数，RPS 随目标响应快慢自然变化。'
              : '尽量贴近目标总 RPS；Users 作为并发池。若目标过慢，实际 RPS 可能达不到。'}
          </p>

          <div className="row-2">
            <div className="field">
              <label>{loadMode === 'throughput' ? 'Users（并发池）' : 'Users'}</label>
              <input
                type="text"
                inputMode="numeric"
                value={usersText}
                onChange={(e) => setUsersText(e.target.value.replace(/[^\d]/g, ''))}
                disabled={!!activeRun}
              />
            </div>
            <div className="field">
              <label>Spawn rate</label>
              <input
                type="text"
                inputMode="decimal"
                value={spawnRateText}
                onChange={(e) =>
                  setSpawnRateText(e.target.value.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1'))
                }
                disabled={!!activeRun}
              />
            </div>
          </div>

          {loadMode === 'throughput' && (
            <div className="field">
              <label>目标 RPS</label>
              <input
                type="text"
                inputMode="decimal"
                value={targetRpsText}
                onChange={(e) =>
                  setTargetRpsText(e.target.value.replace(/[^\d.]/g, '').replace(/(\..*)\./g, '$1'))
                }
                disabled={!!activeRun}
              />
            </div>
          )}

          <div className="row-2">
            <div className="field">
              <label>Workers（多核发压）</label>
              <select
                value={workers}
                onChange={(e) => setWorkers(Number(e.target.value))}
                disabled={!!activeRun}
              >
                {[1, 2, 4, 6, 8]
                  .filter((n) => n <= (guardrails?.max_workers ?? 8))
                  .map((n) => (
                    <option key={n} value={n}>
                      {n === 1 ? '1（单进程）' : `${n} workers`}
                    </option>
                  ))}
              </select>
            </div>
            <div className="field">
              <label>Duration（如 30s / 2m）</label>
              <input
                value={duration}
                onChange={(e) => setDuration(e.target.value)}
                disabled={!!activeRun}
              />
            </div>
          </div>
          <p className="muted path-hint" style={{ marginTop: -4 }}>
            Workers&gt;1 时启用 Master/Worker 分布式，可吃满更多逻辑核。建议先 4，再试 8。
          </p>

          <div className="field">
            <label>压测页面</label>
            <div className="path-toolbar">
              <button
                type="button"
                className="btn ghost"
                onClick={onDiscover}
                disabled={discovering || !!activeRun || !apiOk}
              >
                {discovering ? '发现中…' : '从首页发现路径'}
              </button>
              {discovering && (
                <button type="button" className="btn ghost" onClick={cancelDiscover}>
                  取消发现
                </button>
              )}
              <button
                type="button"
                className="btn ghost"
                onClick={selectAllPaths}
                disabled={!discoveredPaths.length || !!activeRun}
              >
                全选
              </button>
              <button
                type="button"
                className="btn ghost"
                onClick={clearSelectedPaths}
                disabled={!selectedPaths.length || !!activeRun}
              >
                清空
              </button>
              <button
                type="button"
                className="btn ghost"
                onClick={copySelectedPaths}
                disabled={!selectedPaths.length}
              >
                {copyHint || '一键复制已选'}
              </button>
            </div>
            <p className="muted path-hint">
              已选 {selectedPaths.length} / {discoveredItems.length}（已探测可访问；SPA 路由若 404 会自动排除）
              {copyHint ? ` · ${copyHint}` : ''}
            </p>
            <div className="path-list">
              {discoveredItems.length === 0 && (
                <div className="muted">点击「从首页发现路径」自动读取页面/接口</div>
              )}
              {discoveredItems.map((item) => (
                <label key={item.path} className="path-item">
                  <input
                    type="checkbox"
                    checked={selectedPathSet.has(item.path)}
                    onChange={() => togglePath(item.path)}
                    disabled={!!activeRun}
                  />
                  <span className={`kind-tag kind-${item.kind}`}>{item.kind}</span>
                  <span className="mono">{item.path}</span>
                </label>
              ))}
            </div>
          </div>

          {discoverWarnings.length > 0 && (
            <div className="muted discover-warn">
              {discoverWarnings.slice(0, 3).map((w) => (
                <div key={w}>{w}</div>
              ))}
            </div>
          )}

          <div className="field">
            <label>额外自定义路径（可选，每行一个）</label>
            <textarea
              value={customPathsText}
              onChange={(e) => setCustomPathsText(e.target.value)}
              disabled={!!activeRun}
              placeholder="/about&#10;/news"
            />
          </div>

          {selectedScenario?.supports_static_assets && (
            <label className="checkbox">
              <input
                type="checkbox"
                checked={followStatic}
                onChange={(e) => setFollowStatic(e.target.checked)}
                disabled={!!activeRun}
              />
              跟随少量静态资源（默认关闭）
            </label>
          )}

          <div className="actions">
            <button
              className="btn primary"
              onClick={onStart}
              disabled={busy || !!activeRun || !apiOk}
            >
              开始压测
            </button>
            <button
              className="btn danger"
              onClick={onStop}
              disabled={busy || !activeRun}
            >
              停止
            </button>
          </div>

          {error && <div className="error">{error}</div>}

          <section className="history">
            <h2>
              历史 Runs{' '}
              {runs.length > 0 && (
                <span className="muted history-count">({runs.length})</span>
              )}
            </h2>
            <div className="history-list">
              {runs.length === 0 && <div className="muted">暂无历史记录</div>}
              {visibleRuns.map((run) => (
                <div
                  key={run.id}
                  className={`history-item ${selected?.id === run.id ? 'active' : ''}`}
                  onClick={() => openRun(run.id)}
                >
                  <div>
                    <div>
                      <strong className="mono">{run.id}</strong>{' '}
                      <span className={`status-pill ${run.status}`}>{run.status}</span>
                    </div>
                    <div className="meta">
                      {run.scenario_name} ·{' '}
                      {run.load_mode === 'throughput'
                        ? `${run.target_rps ?? '-'} rps`
                        : `${run.users}u`}{' '}
                      · {run.workers || 1}w · {run.duration}
                    </div>
                  </div>
                  <div className="muted mono">
                    {new Date(run.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
            {runs.length > HISTORY_PREVIEW_COUNT && (
              <button
                type="button"
                className="btn ghost history-more"
                onClick={() => setHistoryExpanded((v) => !v)}
              >
                {historyExpanded
                  ? '收起'
                  : `更多（还有 ${runs.length - HISTORY_PREVIEW_COUNT} 条）`}
              </button>
            )}
          </section>
        </aside>

        <main className="panel main-panel">
          <GeneratorMonitor metrics={systemMetrics} />

          <h2>
            实时结果{' '}
            {selected && (
              <span className={`status-pill ${selected.status}`}>{selected.status}</span>
            )}
          </h2>

          {!selected && <div className="muted">选择或启动一次压测以查看指标</div>}

          {selected && (
            <>
              <p className="muted">
                {selected.scenario_name} → <span className="mono">{selected.host}</span>
                {' · '}
                {selected.load_mode === 'throughput'
                  ? `恒定吞吐 ${selected.target_rps ?? '-'} RPS / ${selected.users}u`
                  : `恒定用户 ${selected.users}u`}
                {selected.error ? ` · 错误: ${selected.error}` : ''}
              </p>

              {isTerminal(selected.status) && (
                <div className="actions report-actions">
                  <button
                    className="btn ghost"
                    onClick={onDownloadWordReport}
                    disabled={downloadingReport}
                  >
                    {downloadingReport ? '生成中…' : '下载 Word 报告'}
                  </button>
                </div>
              )}

              <div className="kpis">
                <div className="kpi">
                  <div className="label">RPS</div>
                  <div className="value">{(metrics?.total_rps ?? 0).toFixed(2)}</div>
                </div>
                <div className="kpi">
                  <div className="label">失败率</div>
                  <div className="value">
                    {((metrics?.fail_ratio ?? 0) * 100).toFixed(2)}%
                  </div>
                </div>
                <div className="kpi">
                  <div className="label">p95 (ms)</div>
                  <div className="value">
                    {metrics?.p95 != null ? metrics.p95.toFixed(0) : '-'}
                  </div>
                </div>
                <div className="kpi">
                  <div className="label">活跃用户</div>
                  <div className="value">{metrics?.user_count ?? 0}</div>
                </div>
              </div>

              <MetricsChart history={selected.history} />
              <EndpointTable endpoints={metrics?.endpoints ?? []} />
            </>
          )}
        </main>
      </div>
    </div>
  )
}
