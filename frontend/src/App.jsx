import { useEffect, useRef, useState } from 'react'
import { createChart, ColorType, CandlestickSeries, createSeriesMarkers } from 'lightweight-charts'
import axios from 'axios'
import './App.css'

const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
const TICKERS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ADANIENT']

function AnimatedNumber({ value }) {
  const [display, setDisplay] = useState(0)
  const frameRef = useRef()

  useEffect(() => {
    const start = display
    const end = value || 0
    const duration = 600
    const startTime = performance.now()

    const tick = (now) => {
      const progress = Math.min((now - startTime) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(start + (end - start) * eased))
      if (progress < 1) frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frameRef.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return <>{display}</>
}

function Particles() {
  const particles = Array.from({ length: 18 }, (_, i) => ({
    left: (i * 37) % 100,
    delay: (i * 1.3) % 12,
    duration: 10 + (i % 6) * 2,
  }))
  return (
    <>
      {particles.map((p, i) => (
        <div
          key={i}
          className="particle"
          style={{
            left: `${p.left}%`,
            animationDelay: `${p.delay}s`,
            animationDuration: `${p.duration}s`,
          }}
        />
      ))}
    </>
  )
}

const MANIPULATION_TYPES = {
  insider_trading: {
    label: 'Insider Trading',
    what: 'A trader with access to non-public, material information (e.g. upcoming earnings, M&A news) trades ahead of that information becoming public.',
    when: 'Typically detected when a trader\'s buy/sell volume spikes sharply in the hours/minutes before a major price-moving announcement, with no public news to explain the move.',
    why: 'Flagged because the trade timing statistically precedes news release far more often than chance would allow, and/or the trader has a known relationship to the company (employee, connected party).',
    how: 'Detected via timing correlation between trade execution and news release, combined with historical behavior profiling of the trader/account (isolation forest + GNN relationship mapping).',
  },
  pump_and_dump: {
    label: 'Pump & Dump',
    what: 'A coordinated group artificially inflates a stock\'s price through misleading positive activity or hype, then sells off their holdings at the peak, leaving other investors with losses.',
    when: 'Flagged when price and volume spike abnormally with no fundamental justification, followed by a sharp sell-off from a concentrated set of accounts shortly after the peak.',
    why: 'The rapid, coordinated buy pressure followed by synchronized selling from a small cluster of accounts is a statistical anomaly compared to normal organic trading.',
    how: 'Detected via volume/price divergence analysis and clustering of accounts that buy and sell in near-identical windows (LSTM autoencoder anomaly scoring).',
  },
  spoofing: {
    label: 'Spoofing',
    what: 'A trader places large orders they never intend to execute, to create a false impression of demand or supply, then cancels them after influencing the price.',
    when: 'Flagged when large order-book entries appear and are cancelled within an unusually short window, repeatedly, without resulting in trades.',
    why: 'A high ratio of order placement to cancellation (with near-zero execution) is a strong statistical signature of intent to manipulate perceived market depth.',
    how: 'Detected via order-to-trade ratio monitoring and order book pattern analysis over short time windows.',
  },
  layering: {
    label: 'Layering',
    what: 'Similar to spoofing, but involves placing multiple orders at different price levels simultaneously to create a false sense of market depth and mislead other traders about supply/demand.',
    when: 'Flagged when multiple orders appear across several price levels from a single account/cluster, then get cancelled together right after triggering a price move.',
    why: 'The synchronized multi-level order placement and cancellation pattern is highly improbable in genuine, uncoordinated trading.',
    how: 'Detected via multi-level order book analysis, identifying clusters of orders that appear and disappear together across price tiers.',
  },
}

function TraderNetworkGraph({ network, onNodeClick, activeTrader }) {
  if (!network || network.length === 0) {
    return <p className="empty">No coordinated trading detected yet.</p>
  }

  const nodeSet = new Set()
  network.forEach(e => { nodeSet.add(e.source); nodeSet.add(e.target) })
  const nodes = Array.from(nodeSet)
  const cx = 200, cy = 160, r = 120
  const positions = {}
  nodes.forEach((n, i) => {
    const angle = (i / nodes.length) * Math.PI * 2
    positions[n] = {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    }
  })

  const maxWeight = Math.max(...network.map(e => e.weight || 1))

  return (
    <svg viewBox="0 0 400 320" className="network-svg">
      {network.map((e, i) => {
        const s = positions[e.source]
        const t = positions[e.target]
        if (!s || !t) return null
        const strength = (e.weight || 1) / maxWeight
        return (
          <line
            key={i}
            x1={s.x} y1={s.y} x2={t.x} y2={t.y}
            stroke="#00ff9d"
            strokeOpacity={0.2 + strength * 0.6}
            strokeWidth={1 + strength * 3}
          />
        )
      })}
      {nodes.map((n, i) => {
        const p = positions[n]
        const isActive = activeTrader === n
        return (
          <g key={n} onClick={() => onNodeClick(n)} className="network-node" style={{ cursor: 'pointer' }}>
            <circle
              cx={p.x} cy={p.y} r={isActive ? 14 : 10}
              fill={isActive ? '#aa3bff' : '#0d1220'}
              stroke="#00ff9d"
              strokeWidth={2}
            />
            <text x={p.x} y={p.y - 16} textAnchor="middle" fontSize="10" fill="#c8d3e6">{n}</text>
          </g>
        )
      })}
    </svg>
  )
}

function ModelBar({ label, value }) {
  return (
    <div className="explain-bar-row">
      <span>{label}</span>
      <div className="explain-bar-bg">
        <div className="explain-bar-fill" style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      <span>{value.toFixed(1)}</span>
    </div>
  )
}

function App() {
  const [selectedTicker, setSelectedTicker] = useState('RELIANCE')
  const [scenario, setScenario] = useState('insider_trading')
  const [alerts, setAlerts] = useState([])
  const [summary, setSummary] = useState({})
  const [heatmap, setHeatmap] = useState([])
  const [network, setNetwork] = useState([])
  const [criticalAlert, setCriticalAlert] = useState(null)
  const [explanation, setExplanation] = useState(null)
  const chartContainerRef = useRef()
  const chartRef = useRef()
  const seriesRef = useRef()
  const markersApiRef = useRef()
  const [liveInfo, setLiveInfo] = useState({ ticker: 'RELIANCE', price: 0, change: 0 })
  const [newsFeed, setNewsFeed] = useState({})
  const [alertNews, setAlertNews] = useState([])

  const [justInjected, setJustInjected] = useState(false)
  const [selectedAlert, setSelectedAlert] = useState(null)
  const [alertExplanation, setAlertExplanation] = useState(null)
  const [modelBreakdown, setModelBreakdown] = useState(null)
  const [regulatoryReport, setRegulatoryReport] = useState(null)
  const [reportModal, setReportModal] = useState(null)
  const [complaintText, setComplaintText] = useState('')
  const [recipientEmail, setRecipientEmail] = useState('')
  const [emailStatus, setEmailStatus] = useState(null) // null | 'sending' | 'sent' | 'error'
  const [csvUploading, setCsvUploading] = useState(false)
  const [csvResult, setCsvResult] = useState(null)
  const [activeTrader, setActiveTrader] = useState(null)
  const fileInputRef = useRef()

  // ---- Tabs ----
  const [activeTab, setActiveTab] = useState('dashboard')
  const [modelStats, setModelStats] = useState(null)
  const [evaluation, setEvaluation] = useState(null)
  const [traderReputation, setTraderReputation] = useState([])
  const [tabLoading, setTabLoading] = useState(false)
  const [washTrading, setWashTrading] = useState([])
  const [plugins, setPlugins] = useState(null)
  const [coordinatedAlert, setCoordinatedAlert] = useState(null)
  const [auditLog, setAuditLog] = useState([])
  const [weightsConfig, setWeightsConfig] = useState(null)
  const [weightsSaveStatus, setWeightsSaveStatus] = useState(null)
  const [escalateStatus, setEscalateStatus] = useState(null)
  const [activeTraderHistory, setActiveTraderHistory] = useState(null)
  const [expandedTrader, setExpandedTrader] = useState(null)

  useEffect(() => {
    if (!chartContainerRef.current) return
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#070b14' }, textColor: '#8fa3bf' },
      grid: { vertLines: { color: '#0f1826' }, horzLines: { color: '#0f1826' } },
      width: chartContainerRef.current.clientWidth,
      height: 500,
      timeScale: { timeVisible: true, secondsVisible: false },
    })
    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#00e676', downColor: '#ff1744',
      borderUpColor: '#00e676', borderDownColor: '#ff1744',
      wickUpColor: '#00e676', wickDownColor: '#ff1744',
    })
    chartRef.current = chart
    seriesRef.current = series
    markersApiRef.current = createSeriesMarkers(series, [])

    const handleResize = () => chart.applyOptions({ width: chartContainerRef.current.clientWidth })
    window.addEventListener('resize', handleResize)
    return () => { window.removeEventListener('resize', handleResize); chart.remove() }
  }, [])

  const loadChartData = async (ticker) => {
    try {
      const res = await axios.get(`${API}/api/ticks?limit=200`)
      const filtered = res.data.filter(t => t.ticker === ticker).reverse()
      if (filtered.length === 0) return

      const candleData = []
      const markers = []
      let lastTime = 0
      filtered.forEach((t, i) => {
        let time = Math.floor(new Date(t.timestamp).getTime() / 1000)
        if (time <= lastTime) time = lastTime + 1
        lastTime = time
        const prevClose = i > 0 ? filtered[i - 1].close : t.close
        candleData.push({
          time, open: prevClose, high: Math.max(prevClose, t.close),
          low: Math.min(prevClose, t.close), close: t.close,
        })
        if (t.scenario) {
          markers.push({
            time, position: 'aboveBar', color: '#ff1744', shape: 'circle',
            text: `⚠ ${t.scenario}`,
          })
        }
      })
      seriesRef.current.setData(candleData)
      markersApiRef.current.setMarkers(markers)

      const last = filtered[filtered.length - 1]
      const first = filtered[0]
      const change = first.close ? (((last.close - first.close) / first.close) * 100).toFixed(2) : 0
      setLiveInfo({ ticker, price: last.close || 0, change })
    } catch (e) { console.error(e) }
  }

  const loadAll = async () => {
    try {
      const [alertsRes, summaryRes, heatmapRes, networkRes, coordRes] = await Promise.all([
        axios.get(`${API}/api/alerts?limit=20`),
        axios.get(`${API}/api/market-summary`),
        axios.get(`${API}/api/heatmap`),
        axios.get(`${API}/api/trader-network`),
        axios.get(`${API}/api/coordinated-alerts`).catch(() => ({ data: { coordinated: false } })),
      ])
      setAlerts(alertsRes.data)
      setSummary(summaryRes.data)
      setHeatmap(heatmapRes.data)
      setNetwork(networkRes.data)
      setCoordinatedAlert(coordRes.data.coordinated ? coordRes.data : null)
      const critical = alertsRes.data.find(a => (a.risk_level === 'CRITICAL' || a.risk_level === 'HIGH') && a.status === 'open')
      setCriticalAlert(critical || null)
      if (critical) setJustInjected(false)
      loadChartData(selectedTicker)
    } catch (e) { console.error(e) }
  }

  useEffect(() => {
    loadAll()
    const interval = setInterval(loadAll, 8000)
    return () => clearInterval(interval)
  }, [selectedTicker])

  useEffect(() => {
    if (criticalAlert) {
      axios.get(`${API}/api/scenario-explanation/${criticalAlert.alert_id}`)
        .then(res => setExplanation(res.data))
        .catch(e => console.error(e))
      axios.get(`${API}/api/alert-news/${criticalAlert.alert_id}`)
        .then(res => setAlertNews(res.data.headlines || []))
        .catch(e => console.error(e))
    } else {
      setExplanation(null)
      setAlertNews([])
    }
  }, [criticalAlert])

  // ---- Tab data loading ----
  const loadModelComparison = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/alerts?limit=200`)
      const allAlerts = res.data
      if (allAlerts.length === 0) {
        setModelStats({ overall: null, byType: {} })
        return
      }
      const avg = (arr, key) => arr.reduce((s, a) => s + (a[key] || 0), 0) / arr.length
      const overall = {
        temporal: avg(allAlerts, 'temporal_score'),
        sentiment: avg(allAlerts, 'sentiment_score'),
        network: avg(allAlerts, 'network_score'),
        lstm: avg(allAlerts, 'lstm_score'),
      }
      const types = [...new Set(allAlerts.map(a => a.alert_type))]
      const byType = {}
      types.forEach(t => {
        const subset = allAlerts.filter(a => a.alert_type === t)
        byType[t] = {
          count: subset.length,
          temporal: avg(subset, 'temporal_score'),
          sentiment: avg(subset, 'sentiment_score'),
          network: avg(subset, 'network_score'),
          lstm: avg(subset, 'lstm_score'),
          avgComposite: avg(subset, 'composite_score'),
        }
      })
      setModelStats({ overall, byType, totalAlerts: allAlerts.length })
    } catch (e) {
      console.error(e)
      setModelStats(null)
    } finally {
      setTabLoading(false)
    }
  }

  const loadEvaluation = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/evaluation`)
      setEvaluation(res.data)
    } catch (e) {
      console.error(e)
    } finally {
      setTabLoading(false)
    }
  }

  const loadTraderReputation = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/trader-reputation`)
      setTraderReputation(res.data)
    } catch (e) {
      console.error(e)
    } finally {
      setTabLoading(false)
    }
  }

  const loadNewsFeed = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/news-feed`)
      setNewsFeed(res.data)
    } catch (e) {
      console.error(e)
    } finally {
      setTabLoading(false)
    }
  }

  const loadWashTrading = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/wash-trading`)
      setWashTrading(res.data)
    } catch (e) { console.error(e) } finally { setTabLoading(false) }
  }
  
  const loadPlugins = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/plugins`)
      setPlugins(res.data)
    } catch (e) { console.error(e) } finally { setTabLoading(false) }
  }

  const loadAuditLog = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/audit-log?limit=100`)
      setAuditLog(res.data)
    } catch (e) { console.error(e) } finally { setTabLoading(false) }
  }

  const loadWeights = async () => {
    setTabLoading(true)
    try {
      const res = await axios.get(`${API}/api/settings/weights`)
      setWeightsConfig(res.data)
    } catch (e) { console.error(e) } finally { setTabLoading(false) }
  }

  const saveWeights = async () => {
    if (!weightsConfig) return
    setWeightsSaveStatus('saving')
    try {
      await axios.post(`${API}/api/settings/weights`, {
        weights: weightsConfig.weights,
        risk_thresholds: weightsConfig.risk_thresholds,
      })
      setWeightsSaveStatus('saved')
    } catch (e) {
      setWeightsSaveStatus('error')
    }
  }

  const toggleTraderHistory = async (traderId) => {
    if (expandedTrader === traderId) {
      setExpandedTrader(null)
      setActiveTraderHistory(null)
      return
    }
    setExpandedTrader(traderId)
    try {
      const res = await axios.get(`${API}/api/trader-reputation-history/${traderId}`)
      setActiveTraderHistory(res.data)
    } catch (e) {
      setActiveTraderHistory([])
    }
  }

  const escalateAlert = async (alertId) => {
    setEscalateStatus('sending')
    try {
      const res = await axios.post(`${API}/api/escalate/${alertId}`)
      setEscalateStatus(res.data.status === 'escalated' ? 'sent' : (res.data.status || 'error'))
    } catch (e) {
      setEscalateStatus('error')
    }
  }

  const printReportPDF = (alert) => {
    const reportText = regulatoryReport || buildReportBody(alert, alertExplanation, regulatoryReport)
    const win = window.open('', '_blank', 'width=800,height=900')
    if (!win) return
    win.document.write(`<!DOCTYPE html><html><head><title>Regulatory Report - Alert #${alert.alert_id}</title>
      <style>
        body{font-family:'Courier New',monospace;background:#fff;color:#111;padding:40px;font-size:13px;line-height:1.6}
        h1{font-size:16px;border-bottom:2px solid #111;padding-bottom:10px;margin-bottom:20px}
        pre{white-space:pre-wrap;word-wrap:break-word}
      </style></head>
      <body>
        <h1>MARKET MANIPULATION DETECTION &amp; INSIDER TRADING PREVENTION SYSTEM<br/>SUSPICIOUS ACTIVITY REPORT</h1>
        <pre>${reportText.replace(/</g, '&lt;')}</pre>
      </body></html>`)
    win.document.close()
    win.focus()
    setTimeout(() => win.print(), 350)
  }

  useEffect(() => {
    if (activeTab === 'models') loadModelComparison()
    if (activeTab === 'evaluation') loadEvaluation()
    if (activeTab === 'reputation') loadTraderReputation()
    if (activeTab === 'news') loadNewsFeed()
    if (activeTab === 'washtrading') loadWashTrading()
    if (activeTab === 'plugins') loadPlugins()
    if (activeTab === 'auditlog') loadAuditLog()
    if (activeTab === 'settings') loadWeights()
  }, [activeTab])

  const injectScenario = async () => {
    setJustInjected(true)
    await axios.post(`${API}/api/inject`, null, {
      params: { ticker: selectedTicker, scenario, length_ticks: 5 }
    })
    let attempts = 0
    const fastPoll = setInterval(async () => {
      attempts += 1
      await loadAll()
      if (attempts >= 6) clearInterval(fastPoll)
    }, 3000)
  }

  const fastForward = async () => {
    await axios.post(`${API}/api/debug/fast-forward?count=10`)
    loadAll()
  }

  const reviewAlert = async (id, decision) => {
    await axios.post(`${API}/api/alerts/${id}/review?decision=${decision}`)
    loadAll()
  }

  const openAlertDetail = async (alert) => {
    setSelectedAlert(alert)
    setAlertExplanation(null)
    setModelBreakdown(null)
    setRegulatoryReport(null)
    try {
      const [explainRes, breakdownRes, reportRes] = await Promise.all([
        axios.get(`${API}/api/scenario-explanation/${alert.alert_id}`),
        axios.get(`${API}/api/explain/${alert.alert_id}`),
        axios.get(`${API}/api/regulatory-report/${alert.alert_id}`),
      ])
      setAlertExplanation(explainRes.data)
      setModelBreakdown(breakdownRes.data.breakdown || [])
      setRegulatoryReport(reportRes.data.report || null)
    } catch (e) {
      console.error(e)
      setAlertExplanation({ why: 'Explanation unavailable.', immediate_issue: '-', recommended_action: '-' })
    }
  }

  const openAlertInNewPage = (e, alertId) => {
    e.preventDefault()
    window.open(`/alert-detail.html?id=${alertId}`, '_blank')
  }

  const buildReportBody = (alert, explanation, report) => {
    if (report) return report
    return [
      `INCIDENT REPORT — MARKET MANIPULATION DETECTION SYSTEM`,
      ``,
      `Alert ID: #${alert.alert_id}`,
      `Ticker: ${alert.ticker}`,
      `Alert Type: ${alert.alert_type}`,
      `Risk Level: ${alert.risk_level}`,
      `Composite Score: ${alert.composite_score}/100`,
      `Detected At: ${alert.timestamp || 'N/A'}`,
      ``,
      `WHY FLAGGED: ${explanation?.why || 'N/A'}`,
      `IMMEDIATE ISSUE: ${explanation?.immediate_issue || 'N/A'}`,
      `RECOMMENDED ACTION: ${explanation?.recommended_action || 'N/A'}`,
      ``,
      `Generated automatically by the Market Manipulation Detection & Insider Trading Prevention System.`
    ].join('\n')
  }

  const sendReportEmail = async (alert) => {
    const body = buildReportBody(alert, alertExplanation, regulatoryReport)
    const subject = `Insider Trading Alert Report — ${alert.ticker} (#${alert.alert_id})`
    setEmailStatus('sending')
    try {
      await axios.post(`${API}/api/send-email`, { recipient: recipientEmail, subject, body })
      setEmailStatus('sent')
    } catch (e) {
      setEmailStatus('error')
    }
  }

  const sendComplaintEmail = async (alert) => {
    const body = [
      `COMPLAINT — SUSPECTED MARKET MANIPULATION / INSIDER TRADING`,
      ``,
      `Ticker: ${alert.ticker}`,
      `Alert Type: ${alert.alert_type}`,
      `Risk Score: ${alert.composite_score}/100`,
      ``,
      `Description of issue:`,
      complaintText || '(no additional details provided)',
      ``,
      `System-generated evidence:`,
      buildReportBody(alert, alertExplanation, regulatoryReport),
    ].join('\n')
    const subject = `Complaint: Suspected Insider Trading — ${alert.ticker} (#${alert.alert_id})`
    setEmailStatus('sending')
    try {
      await axios.post(`${API}/api/send-email`, { recipient: recipientEmail, subject, body })
      setEmailStatus('sent')
    } catch (e) {
      setEmailStatus('error')
    }
  }

  const exportAlertsCSV = async () => {
    try {
      const res = await axios.get(`${API}/api/export/alerts-csv`)
      const blob = new Blob([res.data.csv], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `alerts_export_${Date.now()}.csv`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert('Export failed — check that /api/export/alerts-csv is running.')
    }
  }

  const handleCsvUpload = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setCsvUploading(true)
    setCsvResult(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await axios.post(`${API}/api/analyze-csv`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setCsvResult(res.data)
    } catch (e) {
      setCsvResult({ error: 'Analysis failed. Check that /api/analyze-csv is implemented on the backend.' })
    } finally {
      setCsvUploading(false)
      e.target.value = ''
    }
  }

  const showSiren = criticalAlert || justInjected

  return (
    <div className="app">
      <div className="scanline" />
      <Particles />

      <h1>🛡️ MARKET MANIPULATION DETECTION & INSIDER TRADING PREVENTION SYSTEM</h1>
      <p className="subtitle">AI-driven financial surveillance — live NSE market data via Twelve Data</p>
      <div className="live-badge"><span className="live-dot" /> LIVE MONITORING ACTIVE</div>

      <div className="tabs">
        <div className={`tab ${activeTab === 'dashboard' ? 'active' : ''}`} onClick={() => setActiveTab('dashboard')}>📊 Dashboard</div>
        <div className={`tab ${activeTab === 'models' ? 'active' : ''}`} onClick={() => setActiveTab('models')}>🧠 Model Comparison</div>
        <div className={`tab ${activeTab === 'evaluation' ? 'active' : ''}`} onClick={() => setActiveTab('evaluation')}>📈 Evaluation Metrics</div>
        <div className={`tab ${activeTab === 'reputation' ? 'active' : ''}`} onClick={() => setActiveTab('reputation')}>👤 Trader Reputation</div>
        <div className={`tab ${activeTab === 'news' ? 'active' : ''}`} onClick={() => setActiveTab('news')}>📰 News Feed</div>
        <div className={`tab ${activeTab === 'washtrading' ? 'active' : ''}`} onClick={() => setActiveTab('washtrading')}>🔄 Wash Trading</div>
       <div className={`tab ${activeTab === 'plugins' ? 'active' : ''}`} onClick={() => setActiveTab('plugins')}>🧩 Plugin Detectors</div>
        <div className={`tab ${activeTab === 'auditlog' ? 'active' : ''}`} onClick={() => setActiveTab('auditlog')}>🧾 Audit Log</div>
        <div className={`tab ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => setActiveTab('settings')}>⚙️ Settings</div>
      </div>

      {coordinatedAlert && (
        <div className="siren" style={{ borderColor: '#aa3bff', background: 'rgba(170,59,255,0.12)' }}>
          🌐 COORDINATED MARKET-WIDE MANIPULATION DETECTED across {coordinatedAlert.tickers.join(', ')} within {coordinatedAlert.window_seconds}s — statistically unlikely to be coincidence
        </div>
      )}

      {activeTab === 'dashboard' && (
        <>
          <div className="kpi-row">
            <div className="kpi"><span>Total Alerts</span><b><AnimatedNumber value={summary.total_alerts || 0} /></b></div>
            <div className="kpi"><span>Open Alerts</span><b><AnimatedNumber value={summary.open_alerts || 0} /></b></div>
            <div className="kpi"><span>Ticks Processed</span><b><AnimatedNumber value={summary.total_ticks || 0} /></b></div>
            <div className="kpi"><span>Traders Tracked</span><b><AnimatedNumber value={summary.total_traders || 0} /></b></div>
          </div>

          {showSiren && (
            <div className={`siren ${justInjected ? 'siren-blink' : ''}`}>
                            🚨 {criticalAlert ? `${criticalAlert.risk_level} ALERT — ${criticalAlert.alert_type} DETECTED ON ${criticalAlert.ticker}` : 'MANIPULATION INJECTED — ANALYZING...'} 🚨
              {criticalAlert && (
                <div className="siren-sub">Risk Score: {criticalAlert.composite_score}/100 | Alert #{criticalAlert.alert_id}</div>
              )}
              {criticalAlert && (
                <div className="siren-actions">
                  <button className="report-btn" onClick={() => { openAlertDetail(criticalAlert); setEmailStatus(null); setReportModal({ alert: criticalAlert, mode: 'report' }) }}>
                    📧 Report Insider Trading
                  </button>
                  <button className="complaint-btn" onClick={() => { openAlertDetail(criticalAlert); setEmailStatus(null); setReportModal({ alert: criticalAlert, mode: 'complaint' }) }}>
                    📝 File a Complaint
                  </button>
                </div>
              )}
            </div>
          )}

          {explanation && criticalAlert && (
            <div className="explanation-panel">
              <h3>🔍 WHY THIS WAS FLAGGED</h3>
              <p><b>Reason:</b> {explanation.why}</p>
              <p><b>Immediate Issue:</b> {explanation.immediate_issue}</p>
              <p><b>Recommended Action:</b> {explanation.recommended_action}</p>
            </div>
          )}

          {criticalAlert && alertNews.length > 0 && (
            <div className="explanation-panel">
              <h3>📰 CAUSED DUE TO / RELATED NEWS</h3>
              {alertNews.map((h, i) => (
                <p key={i}>• {h}</p>
              ))}
            </div>
          )}

          <div className="controls">
            <select value={selectedTicker} onChange={e => setSelectedTicker(e.target.value)}>
              {TICKERS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={scenario} onChange={e => setScenario(e.target.value)}>
              <option value="insider_trading">Insider Trading</option>
              <option value="pump_and_dump">Pump & Dump</option>
              <option value="spoofing">Spoofing</option>
              <option value="layering">Layering</option>
            </select>
            <button className="inject-btn" onClick={injectScenario}>🎯 INJECT MANIPULATION</button>
            <button className="ff-btn" onClick={fastForward}>⏩ Fast Forward</button>
            <button className="export-btn" onClick={exportAlertsCSV}>⬇️ Export Alerts CSV</button>
            <button className="upload-btn" onClick={() => fileInputRef.current.click()}>
              {csvUploading ? '⏳ Analyzing...' : '📤 Upload Trades CSV'}
            </button>
            <input ref={fileInputRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={handleCsvUpload} />
          </div>

          {csvResult && (
            <div className="csv-result-panel">
              {csvResult.error ? (
                <p className="csv-error">{csvResult.error}</p>
              ) : (
                <>
                  <h3>📊 CSV Analysis Result</h3>
                  <p>{csvResult.summary || `${csvResult.flagged_count || 0} suspicious trades flagged out of ${csvResult.total_rows || 0} rows.`}</p>
                </>
              )}
              <button className="close-inline" onClick={() => setCsvResult(null)}>Dismiss</button>
            </div>
          )}

          <div className="chart-wrapper">
            <div className="chart-legend">
              <span className="legend-ticker">{liveInfo.ticker}</span>
              <span className="legend-price">₹{liveInfo.price.toFixed(2)}</span>
              <span className={`legend-change ${liveInfo.change >= 0 ? 'up' : 'down'}`}>
                {liveInfo.change >= 0 ? '▲' : '▼'} {Math.abs(liveInfo.change)}%
              </span>
            </div>
            <div ref={chartContainerRef} className="chart-container" />
          </div>

          <div className="panels">
            <div className="panel">
              <h3>🔥 RISK HEATMAP</h3>
              {heatmap.map(h => (
                <div
                  key={h.ticker}
                  className={`heatmap-row risk-${h.risk.toLowerCase()} clickable`}
                  onClick={() => setSelectedTicker(h.ticker)}
                >
                  <span>{h.ticker}</span><span>{h.risk}</span><span>{h.score.toFixed(1)}</span>
                </div>
              ))}
            </div>

            <div className="panel">
              <h3>🚨 RECENT ALERTS</h3>
              <p className="empty" style={{ padding: '0 0 8px', fontSize: '11px' }}>Left-click for quick view · Right-click to open in a new tab</p>
              {alerts.length === 0 && <p className="empty">No alerts yet.</p>}
              {alerts.slice(0, 8).map(a => (
                <div
                  key={a.alert_id}
                  className={`alert-row risk-${a.risk_level.toLowerCase()}`}
                  onContextMenu={(e) => openAlertInNewPage(e, a.alert_id)}
                >
                  <div className="alert-summary clickable" onClick={() => openAlertDetail(a)}>
                    #{a.alert_id} {a.ticker} — {a.alert_type} ({a.composite_score}) 🔍
                  </div>
                  {a.status === 'open' && (
                    <div className="alert-actions">
                      <button onClick={() => reviewAlert(a.alert_id, 'confirmed')}>✅ Confirm</button>
                      <button onClick={() => reviewAlert(a.alert_id, 'dismissed')}>❌ Dismiss</button>
                      <button onClick={() => { openAlertDetail(a); setEmailStatus(null); setReportModal({ alert: a, mode: 'report' }) }}>📧 Report</button>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="panel">
              <h3>🕸️ TRADER NETWORK</h3>
              <TraderNetworkGraph network={network} onNodeClick={setActiveTrader} activeTrader={activeTrader} />
              {activeTrader && (
                <div className="active-trader-info">
                  Selected: <b>{activeTrader}</b>
                  {' '}— {network.filter(e => e.source === activeTrader || e.target === activeTrader).length} connection(s)
                  <button className="close-inline" onClick={() => setActiveTrader(null)}>Clear</button>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {activeTab === 'models' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>🧠 Model Contribution Comparison</h3>
          <p className="empty" style={{ padding: '0 0 16px', textAlign: 'left' }}>
            Average score each detection model contributed across all alerts raised so far (0–100 scale, before weighting).
          </p>
          {tabLoading && <p className="empty">Loading...</p>}
          {!tabLoading && (!modelStats || !modelStats.overall) && <p className="empty">No alerts yet — inject a scenario first to generate comparison data.</p>}
          {!tabLoading && modelStats && modelStats.overall && (
            <>
              <div className="explanation-panel">
                <h3>Overall Average (across {modelStats.totalAlerts} alerts)</h3>
                <ModelBar label="Temporal (Isolation Forest)" value={modelStats.overall.temporal} />
                <ModelBar label="Sentiment (FinBERT)" value={modelStats.overall.sentiment} />
                <ModelBar label="Network (GNN)" value={modelStats.overall.network} />
                <ModelBar label="Temporal (LSTM Autoencoder)" value={modelStats.overall.lstm} />
              </div>

              <div className="panels" style={{ marginTop: 16 }}>
                {Object.entries(modelStats.byType).map(([type, stats]) => (
                  <div className="panel" key={type}>
                    <h3>{type} <span style={{ color: '#6b7a94', fontWeight: 400, fontSize: 12 }}>({stats.count} alerts)</span></h3>
                    <ModelBar label="Temporal (IF)" value={stats.temporal} />
                    <ModelBar label="Sentiment" value={stats.sentiment} />
                    <ModelBar label="Network (GNN)" value={stats.network} />
                    <ModelBar label="LSTM" value={stats.lstm} />
                    <p style={{ marginTop: 10, fontSize: 12, color: '#a8b5cc' }}>
                      Avg composite score: <b style={{ color: '#e8edf5' }}>{stats.avgComposite.toFixed(1)}/100</b>
                    </p>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {activeTab === 'evaluation' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>📈 Evaluation Metrics</h3>
          {tabLoading && <p className="empty">Loading...</p>}
          {!tabLoading && !evaluation && <p className="empty">No evaluation data available.</p>}
          {!tabLoading && evaluation && (
            <>
              <div className="eval-grid">
                <div className="eval-card"><span>Precision</span><b>{(evaluation.estimated_precision * 100).toFixed(1)}%</b></div>
<div className="eval-card"><span>Recall</span><b>{(evaluation.estimated_recall * 100).toFixed(1)}%</b></div>
<div className="eval-card"><span>F1 Score</span><b>{(evaluation.estimated_f1 * 100).toFixed(1)}%</b></div>
                <div className="eval-card"><span>Alerts Raised</span><b>{evaluation.total_alerts_raised}</b></div>
                <div className="eval-card"><span>Manipulated Ticks</span><b>{evaluation.manipulated_ticks_injected}</b></div>
                <div className="eval-card"><span>Normal Ticks</span><b>{evaluation.normal_ticks}</b></div>
              </div>
              <p className="eval-note">{evaluation.note}</p>
            </>
          )}
        </div>
      )}

      {activeTab === 'reputation' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>👤 Trader Reputation Leaderboard</h3>
          <p className="empty" style={{ padding: '0 0 16px', textAlign: 'left' }}>Traders ranked by reputation score — higher means more repeated flags across confirmed manipulation events.</p>
          {tabLoading && <p className="empty">Loading...</p>}
          {!tabLoading && traderReputation.length === 0 && <p className="empty">No flagged traders yet.</p>}
          {!tabLoading && traderReputation.map(t => (
            <div key={t.trader_id}>
              <div className="network-row" style={{ cursor: 'pointer' }} onClick={() => toggleTraderHistory(t.trader_id)}>
                <span><b style={{ color: '#e8edf5' }}>{t.trader_id}</b> {expandedTrader === t.trader_id ? '▲' : '▼'}</span>
                <span>Flags: {t.flag_count}</span>
                <span>Reputation: {t.reputation_score.toFixed(1)}</span>
              </div>
              {expandedTrader === t.trader_id && (
                <div style={{ padding: '8px 16px 16px', display: 'flex', alignItems: 'flex-end', gap: 4, height: 60 }}>
                  {activeTraderHistory === null && <span className="empty">Loading trend...</span>}
                  {Array.isArray(activeTraderHistory) && activeTraderHistory.length === 0 && <span className="empty">No history yet.</span>}
                  {Array.isArray(activeTraderHistory) && activeTraderHistory.map((h, i) => (
                    <div key={i} title={`${h.reputation_score.toFixed(1)} @ ${h.recorded_at}`}
                      style={{ width: 8, height: `${Math.max(4, h.reputation_score / 60 * 50)}px`, background: '#00ff9d', borderRadius: 2 }} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {activeTab === 'news' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>📰 Live News Feed by Security</h3>
          <p className="empty" style={{ padding: '0 0 16px', textAlign: 'left' }}>
            Real headlines pulled from Google News, used as input to the FinBERT sentiment model. Refreshes each time you open this tab.
          </p>
          {tabLoading && <p className="empty">Fetching live headlines...</p>}
          {!tabLoading && (
            <div className="panels">
              {Object.entries(newsFeed).map(([ticker, headlines]) => (
                <div className="panel" key={ticker}>
                  <h3>{ticker}</h3>
                  {headlines.length === 0 && <p className="empty">No recent headlines found.</p>}
                  {headlines.map((h, i) => (
                    <p key={i} style={{ fontSize: 13, color: '#a8b5cc', margin: '8px 0' }}>• {h}</p>
                  ))}
                </div>
              ))}
            </div>
          )}
          <button className="ff-btn" style={{ marginTop: 16 }} onClick={loadNewsFeed}>🔄 Refresh News</button>
        </div>
      )}

      {activeTab === 'washtrading' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>🔄 Wash Trading Detection</h3>
          <p className="empty" style={{ padding: '0 0 16px', textAlign: 'left' }}>
            Detects trader pairs with high mutual trade volume but almost no connections elsewhere — a graph-based
            signature of self-dealing/wash trading, computed via Neo4j (or its in-memory fallback) pattern matching.
            This is a separate, deterministic graph-algorithm detector — independent of the ML ensemble above.
          </p>
          {tabLoading && <p className="empty">Loading...</p>}
          {!tabLoading && washTrading.length === 0 && <p className="empty">No wash trading patterns detected yet.</p>}
          {!tabLoading && washTrading.map((w, i) => (
            <div className="network-row" key={i}>
              <span><b style={{ color: '#e8edf5' }}>{w.trader_a}</b> ↔ <b style={{ color: '#e8edf5' }}>{w.trader_b}</b></span>
              <span>Pair Trades: {w.pair_weight}</span>
            </div>
          ))}
        </div>
      )}
      
      {activeTab === 'plugins' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>🧩 Plugin Detector Framework</h3>
          <p className="empty" style={{ padding: '0 0 16px', textAlign: 'left' }}>
            An extension point built for future contributors: any file dropped into <code>backend/app/ml/plugins/</code>
            containing a class that subclasses <code>Detector</code> is auto-discovered on backend startup and its score
            automatically folds into the composite risk score — no other file needs to be touched. The two detectors
            below are real, working examples, not placeholders.
          </p>
          {tabLoading && <p className="empty">Loading...</p>}
          {!tabLoading && plugins && plugins.loaded.length === 0 && <p className="empty">No plugins found in ml/plugins/.</p>}
          {!tabLoading && plugins && plugins.loaded.map(p => (
            <div className="network-row" key={p.name}>
              <span><b style={{ color: '#e8edf5' }}>{p.name}</b></span>
              <span style={{ fontSize: 12, color: '#a8b5cc', flex: 1 }}>{p.description}</span>
            </div>
          ))}
          {!tabLoading && plugins && Object.keys(plugins.latest_scores || {}).length > 0 && (
            <>
              <h3 style={{ marginTop: 20 }}>Latest live scores by ticker</h3>
              {Object.entries(plugins.latest_scores).map(([ticker, scores]) => (
                <div className="network-row" key={ticker}>
                  <span><b style={{ color: '#e8edf5' }}>{ticker}</b></span>
                  {Object.entries(scores).map(([name, s]) => (
                    <span key={name} style={{ fontSize: 12 }}>{name}: {s.toFixed(1)}</span>
                  ))}
                </div>
              ))}
            </>
          )}
          <h3 style={{ marginTop: 20 }}>Add your own (starter template)</h3>
          <pre style={{ background: '#0a0e1a', border: '1px solid #1f2a3d', borderRadius: 8, padding: 14, fontSize: 12, color: '#a8b5cc', overflowX: 'auto' }}>
{`# save as backend/app/ml/plugins/my_detector.py
from app.ml.plugins.base import Detector

class MyDetector(Detector):
    name = "my_detector"
    description = "One-line description of what this catches."

    def score(self, ticker, tick, history):
        # tick: {"ticker","close","volume","high","low",...}
        # history: recent ticks for this ticker (oldest -> newest)
        return 0.0  # must return 0-100`}
          </pre>
          <button className="ff-btn" style={{ marginTop: 16 }} onClick={loadPlugins}>🔄 Refresh</button>
        </div>
      )}

      {activeTab === 'auditlog' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>🧾 Audit Log</h3>
          <p className="empty" style={{ padding: '0 0 16px', textAlign: 'left' }}>
            Full trail of every analyst review decision, manual escalation, and autonomous notification the system
            has sent — who did what, and when, for compliance record-keeping.
          </p>
          {tabLoading && <p className="empty">Loading...</p>}
          {!tabLoading && auditLog.length === 0 && <p className="empty">No audit events yet.</p>}
          {!tabLoading && auditLog.map(a => (
            <div className="network-row" key={a.audit_id}>
              <span><b style={{ color: '#e8edf5' }}>{a.action}</b> {a.alert_id ? `(alert #${a.alert_id})` : ''}</span>
              <span>{a.actor}</span>
              <span style={{ fontSize: 12, color: '#a8b5cc' }}>{a.action_timestamp}</span>
            </div>
          ))}
          <button className="ff-btn" style={{ marginTop: 16 }} onClick={loadAuditLog}>🔄 Refresh</button>
        </div>
      )}

      {activeTab === 'settings' && (
        <div className="panel-full">
          <h3 style={{ marginTop: 0 }}>⚙️ Detection Settings — Model Weights &amp; Thresholds</h3>
          <p className="empty" style={{ padding: '0 0 16px', textAlign: 'left' }}>
            Tune how much each detector contributes to the composite score, and where LOW/MEDIUM/HIGH/CRITICAL
            cutoffs sit — live, without restarting the backend. Useful for demonstrating that the ensemble is
            genuinely configurable, not a black box.
          </p>
          {tabLoading && <p className="empty">Loading...</p>}
          {!tabLoading && !weightsConfig?.email_configured && (
            <p className="empty" style={{ color: '#ffb020', textAlign: 'left', padding: '0 0 12px' }}>
              ⚠️ Autonomous alert email is not configured yet — set GMAIL_USER / GMAIL_APP_PASSWORD / AUTHORIZED_EMAIL in backend/.env
            </p>
          )}
          {!tabLoading && weightsConfig && (
            <>
              <div className="panels">
                <div className="panel">
                  <h3>Model Weights</h3>
                  {Object.entries(weightsConfig.weights).map(([k, v]) => (
                    <div key={k} style={{ marginBottom: 10 }}>
                      <label style={{ fontSize: 12, color: '#a8b5cc' }}>{k} — {v}</label>
                      <input
                        type="range" min="0" max="0.6" step="0.01" value={v}
                        onChange={e => setWeightsConfig({ ...weightsConfig, weights: { ...weightsConfig.weights, [k]: parseFloat(e.target.value) } })}
                        style={{ width: '100%' }}
                      />
                    </div>
                  ))}
                </div>
                <div className="panel">
                  <h3>Risk Thresholds</h3>
                  {Object.entries(weightsConfig.risk_thresholds).map(([k, v]) => (
                    <div key={k} style={{ marginBottom: 10 }}>
                      <label style={{ fontSize: 12, color: '#a8b5cc' }}>{k} ≥ {v}</label>
                      <input
                        type="range" min="0" max="100" step="1" value={v}
                        onChange={e => setWeightsConfig({ ...weightsConfig, risk_thresholds: { ...weightsConfig.risk_thresholds, [k]: parseFloat(e.target.value) } })}
                        style={{ width: '100%' }}
                      />
                    </div>
                  ))}
                </div>
              </div>
              <button className="ff-btn" style={{ marginTop: 16 }} onClick={saveWeights}>
                {weightsSaveStatus === 'saving' ? '⏳ Saving...' : weightsSaveStatus === 'saved' ? '✅ Saved' : weightsSaveStatus === 'error' ? '⚠️ Failed — Retry' : '💾 Save Changes'}
              </button>
            </>
          )}
        </div>
      )}

      {selectedAlert && !reportModal && (
        <div className="modal" onClick={() => setSelectedAlert(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>Alert #{selectedAlert.alert_id} — {selectedAlert.ticker}</h3>
            <div className="detail-grid">
              <div><span>WHAT</span><b>{selectedAlert.alert_type}</b></div>
              <div><span>WHEN</span><b>{selectedAlert.timestamp || 'N/A'}</b></div>
              <div><span>RISK</span><b>{selectedAlert.risk_level} ({selectedAlert.composite_score}/100)</b></div>
              <div><span>STATUS</span><b>{selectedAlert.status}</b></div>
            </div>

            {alertExplanation ? (
              <div className="explain-detail">
                <p><b>WHY:</b> {alertExplanation.why}</p>
                <p><b>IMMEDIATE ISSUE:</b> {alertExplanation.immediate_issue}</p>
                <p><b>RECOMMENDED ACTION:</b> {alertExplanation.recommended_action}</p>
              </div>
            ) : <p className="empty">Loading explanation...</p>}

            {modelBreakdown && modelBreakdown.length > 0 && (
              <div className="model-breakdown">
                <h4>HOW the score was computed (model contributions)</h4>
                {modelBreakdown.map(m => (
                  <div className="explain-bar-row" key={m.model}>
                    <span>{m.model.replace(/_/g, ' ')}</span>
                    <div className="explain-bar-bg">
                      <div className="explain-bar-fill" style={{ width: `${m.percent}%` }} />
                    </div>
                    <span>{m.percent}%</span>
                  </div>
                ))}
              </div>
            )}

            {selectedAlert.alert_type && MANIPULATION_TYPES[selectedAlert.alert_type.toLowerCase().replace(/ /g, '_')] && (
              <div className="general-pattern">
                <h4>General pattern: {MANIPULATION_TYPES[selectedAlert.alert_type.toLowerCase().replace(/ /g, '_')].label}</h4>
                <p><b>WHAT:</b> {MANIPULATION_TYPES[selectedAlert.alert_type.toLowerCase().replace(/ /g, '_')].what}</p>
                <p><b>WHEN detected:</b> {MANIPULATION_TYPES[selectedAlert.alert_type.toLowerCase().replace(/ /g, '_')].when}</p>
                <p><b>HOW detected:</b> {MANIPULATION_TYPES[selectedAlert.alert_type.toLowerCase().replace(/ /g, '_')].how}</p>
              </div>
            )}

            <details className="other-types">
              <summary>See how other manipulation types are detected →</summary>
              {Object.entries(MANIPULATION_TYPES).map(([key, t]) => (
                <div className="other-type-row" key={key}>
                  <b>{t.label}</b>
                  <p>{t.what}</p>
                </div>
              ))}
            </details>

            <div className="modal-actions">
              <button onClick={() => { setEmailStatus(null); setReportModal({ alert: selectedAlert, mode: 'report' }) }}>📧 Report</button>
              <button onClick={() => { setEmailStatus(null); setReportModal({ alert: selectedAlert, mode: 'complaint' }) }}>📝 File Complaint</button>
              <button onClick={() => { setEscalateStatus(null); escalateAlert(selectedAlert.alert_id) }}>
                {escalateStatus === 'sending' ? '⏳ Escalating...' : escalateStatus === 'sent' ? '✅ Escalated' : escalateStatus === 'not_configured' ? '⚠️ Email not set up' : escalateStatus === 'error' ? '⚠️ Failed' : '🚨 Escalate to Authority'}
              </button>
              <button onClick={() => printReportPDF(selectedAlert)}>🖨️ Export PDF</button>
              <button onClick={() => setSelectedAlert(null)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {reportModal && (
        <div className="modal" onClick={() => setReportModal(null)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>{reportModal.mode === 'report' ? '📧 Report Insider Trading' : '📝 File a Complaint'}</h3>
            <p className="modal-subtext">Alert #{reportModal.alert.alert_id} — {reportModal.alert.ticker}</p>

            <label className="field-label">Recipient email</label>
            <input
              className="text-input"
              type="email"
              placeholder="e.g. your.email@example.com or the authority's email"
              value={recipientEmail}
              onChange={e => setRecipientEmail(e.target.value)}
            />

            {reportModal.mode === 'complaint' && (
              <>
                <label className="field-label">Describe the issue</label>
                <textarea
                  className="text-input textarea"
                  rows={5}
                  placeholder="Describe what you observed..."
                  value={complaintText}
                  onChange={e => setComplaintText(e.target.value)}
                />
              </>
            )}

            <div className="report-text">
              {buildReportBody(reportModal.alert, alertExplanation, regulatoryReport)}
            </div>

            <div className="modal-actions">
              <button
                disabled={!recipientEmail || emailStatus === 'sending'}
                onClick={() => reportModal.mode === 'report' ? sendReportEmail(reportModal.alert) : sendComplaintEmail(reportModal.alert)}
              >
                {emailStatus === 'sending' ? '⏳ Sending...' : emailStatus === 'sent' ? '✅ Sent!' : emailStatus === 'error' ? '⚠️ Failed — Retry' : '📧 Send Email'}
              </button>
              <button onClick={() => setReportModal(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App