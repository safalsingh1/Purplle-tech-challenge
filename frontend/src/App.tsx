import React, { useState, useEffect } from 'react';
import './App.css';
import { useStoreSSE, getApiUrl } from './hooks/useStoreSSE';
import TopBar from './components/Header';
import MetricCard from './components/MetricCard';
import FunnelChart from './components/FunnelChart';
import type { FunnelStage } from './components/FunnelChart';
import HeatmapChart from './components/HeatmapChart';
import AnomaliesLog from './components/AnomaliesLog';
import type { Anomaly } from './components/AnomaliesLog';
import QueueTelemetry from './components/QueueTelemetry';
import VisitorTimeline from './components/VisitorTimeline';
import LiveEventTicker from './components/LiveEventTicker';
import StoreComparison from './components/StoreComparison';
import InsightCards from './components/InsightCards';
import StoreLayoutMap from './components/StoreLayoutMap';

const API_BASE = getApiUrl();
const DEFAULT_STORE = 'STORE_BLR_002';
const STORE_IDS = ['STORE_BLR_002', 'ST1008'];
const STORE_NAMES: Record<string, string> = {
  STORE_BLR_002: 'Bengaluru Central',
  ST1008: 'Brigade Road',
};

type ViewId = 'dashboard' | 'analytics' | 'events' | 'comparison' | 'layout';

// Inline SVG nav icons
const NavIcons = {
  dashboard: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  ),
  analytics: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  ),
  events: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
    </svg>
  ),
  comparison: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </svg>
  ),
  layout: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  ),
};

export const App: React.FC = () => {
  const [selectedStore, setSelectedStore] = useState<string>(DEFAULT_STORE);
  const [activeView, setActiveView] = useState<ViewId>('dashboard');
  const [funnelData, setFunnelData] = useState<FunnelStage[]>([]);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const speed = 1.0;

  const handleRestartSimulation = async () => {
    try {
      await fetch(`${API_BASE}/simulation/start?speed=${speed}&cam_id=CAM_1`, { method: 'POST' });
    } catch (err) {
      console.warn('Failed to restart simulation:', err);
    }
  };

  // Auto-start simulation on mount
  useEffect(() => {
    async function autoStart() {
      try {
        await fetch(`${API_BASE}/simulation/start?speed=1.0&cam_id=CAM_1`, { method: 'POST' });
      } catch (err) {
        console.warn('Failed to auto-start simulation:', err);
      }
    }
    autoStart();
  }, [API_BASE]);

  const { storesData, connectionStatus, lastUpdatedStore, metricHistory, metricDeltas } = useStoreSSE(API_BASE);

  // Fetch funnel + anomalies data
  useEffect(() => {
    let active = true;

    async function fetchAdditionalTelemetry() {
      try {
        const [funnelResp, anomResp] = await Promise.all([
          fetch(`${API_BASE}/stores/${selectedStore}/funnel`),
          fetch(`${API_BASE}/stores/${selectedStore}/anomalies`),
        ]);
        if (funnelResp.ok && active) {
          const d = await funnelResp.json();
          setFunnelData(d.stages ?? []);
        }
        if (anomResp.ok && active) {
          const d = await anomResp.json();
          setAnomalies(d.anomalies ?? []);
        }
      } catch {
        // API unreachable
      }
    }

    fetchAdditionalTelemetry();
    const interval = setInterval(fetchAdditionalTelemetry, 5000);
    return () => { active = false; clearInterval(interval); };
  }, [selectedStore, lastUpdatedStore]);

  const activeMetrics = storesData[selectedStore] ?? {
    store_id: selectedStore,
    unique_visitors: 0,
    conversion_rate: 0.0,
    avg_dwell_per_zone: [],
    queue_depth: 0,
    abandonment_rate: 0.0,
    computed_at: new Date().toISOString(),
  };

  const activeHistory = metricHistory[selectedStore];
  const activeDeltas = metricDeltas[selectedStore];
  const isFlashed = lastUpdatedStore === selectedStore;

  return (
    <div className="app-shell">
      {/* ── SIDEBAR ── */}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-logo-mark">
            <div className="logo-gem">
              <svg viewBox="0 0 24 24" fill="white">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
              </svg>
            </div>
            <div>
              <div className="sidebar-title">APEX</div>
            </div>
          </div>
          <div className="sidebar-subtitle">Store Intelligence Platform</div>
        </div>

        <nav className="sidebar-nav">
          <div className="nav-section-label">Navigation</div>

          {(
            [
              { id: 'dashboard', label: 'Live Dashboard' },
              { id: 'analytics', label: 'Deep Analytics' },
              { id: 'layout', label: 'Customer Flow Map' },
              { id: 'events', label: 'Event Feed' },
              { id: 'comparison', label: 'Store Comparison' },
            ] as const
          ).map((item) => (
            <div
              key={item.id}
              className={`nav-item ${activeView === item.id ? 'active' : ''}`}
              onClick={() => setActiveView(item.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && setActiveView(item.id)}
            >
              {NavIcons[item.id]}
              {item.label}
              {item.id === 'layout' && (
                <span style={{
                  marginLeft: 'auto',
                  background: 'rgba(200,85,255,0.12)',
                  color: '#c855ff',
                  border: '1px solid rgba(200,85,255,0.2)',
                  borderRadius: '20px',
                  fontSize: '0.58rem',
                  fontWeight: 800,
                  padding: '1px 6px',
                  letterSpacing: '0.04em',
                }}>
                  LIVE
                </span>
              )}
              {item.id === 'events' && anomalies.length > 0 && (
                <span style={{
                  marginLeft: 'auto',
                  background: 'rgba(239,68,68,0.15)',
                  color: '#f87171',
                  border: '1px solid rgba(239,68,68,0.25)',
                  borderRadius: '20px',
                  fontSize: '0.6rem',
                  fontWeight: 800,
                  padding: '1px 6px',
                }}>
                  {anomalies.length}
                </span>
              )}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="store-selector-label">Active Store</div>
          <select
            className="store-select"
            value={selectedStore}
            onChange={(e) => setSelectedStore(e.target.value)}
          >
            {STORE_IDS.map((id) => (
              <option key={id} value={id}>
                {STORE_NAMES[id] || id.replace('STORE_', '').replace(/_/g, ' — ')}
              </option>
            ))}
          </select>

          <div className={`conn-badge ${connectionStatus}`}>
            <div className="conn-dot" />
            {connectionStatus === 'live' && 'SSE Live'}
            {connectionStatus === 'connecting' && 'Connecting...'}
            {connectionStatus === 'error' && 'Reconnecting'}
            {connectionStatus === 'disconnected' && 'Offline'}
          </div>
        </div>
      </aside>

      {/* ── MAIN ── */}
      <main className="main-content">
        <TopBar
          activeView={activeView}
          storeId={selectedStore}
          lastUpdated={lastUpdatedStore}
          onStoreChange={setSelectedStore}
        />

        <div className="page-body">

          {/* ==================== DASHBOARD VIEW ==================== */}
          {activeView === 'dashboard' && (
            <>
              {/* Simulation Controller */}
              <div className="panel-card simulation-control-bar" style={{ marginBottom: '20px', padding: '16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '15px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span className="ai-badge-dot animate-pulse" style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#00ffc8', boxShadow: '0 0 10px #00ffc8', display: 'inline-block' }} />
                  <span style={{ fontSize: '0.82rem', fontWeight: 800, color: '#e2e8f0', letterSpacing: '0.08em' }}>⚡ LIVE SYNCHRONIZED SIMULATION</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginLeft: 'auto', flexWrap: 'wrap' }}>
                  <button
                    onClick={handleRestartSimulation}
                    className="speed-btn"
                    style={{ border: '1px dashed #00ffc8', color: '#00ffc8', padding: '5px 12px', borderRadius: '4px', background: 'transparent', cursor: 'pointer', fontSize: '0.75rem', fontWeight: 700 }}
                  >
                    🔄 Sync & Restart
                  </button>
                </div>
              </div>

              {/* KPI Cards */}
              <div className="kpi-grid">
                <MetricCard
                  title="Total Visitors"
                  value={activeMetrics.unique_visitors}
                  subtext="Unique customer entries"
                  type="visitors"
                  glow={isFlashed}
                  delta={activeDeltas?.unique_visitors}
                  history={activeHistory?.unique_visitors}
                />
                <MetricCard
                  title="Conversion Rate"
                  value={`${(activeMetrics.conversion_rate * 100).toFixed(1)}%`}
                  subtext="Visits → purchases"
                  type="conversion"
                  glow={isFlashed}
                  delta={activeDeltas?.conversion_rate}
                  history={activeHistory?.conversion_rate}
                />
                <MetricCard
                  title="Checkout Queue"
                  value={activeMetrics.queue_depth}
                  subtext="Customers in line"
                  type="queue"
                  glow={isFlashed}
                  delta={activeDeltas?.queue_depth}
                  history={activeHistory?.queue_depth}
                />
                <MetricCard
                  title="Abandonment Rate"
                  value={`${(activeMetrics.abandonment_rate * 100).toFixed(1)}%`}
                  subtext="Queue desertions"
                  type="abandonment"
                  glow={isFlashed}
                  delta={activeDeltas?.abandonment_rate}
                  history={activeHistory?.abandonment_rate}
                />
              </div>

              {/* AI Insights */}
              <div className="panel-card">
                <div className="panel-title">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M12 2a10 10 0 0 1 0 20A10 10 0 0 1 12 2z" />
                    <path d="M12 8v4M12 16h.01" />
                  </svg>
                  AI Insights
                  <span className="panel-title-badge">LIVE</span>
                </div>
                <InsightCards metrics={activeMetrics} anomalyCount={anomalies.length} />
              </div>

              {/* Live Store Floor Map Panel */}
              <div className="panel-card" style={{ marginBottom: '20px' }}>
                <div className="panel-title">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
                  </svg>
                  Live Store Floor Map
                  <span className="panel-title-badge" style={{ background: 'rgba(0,220,100,0.1)', color: '#00dc64', borderColor: 'rgba(0,220,100,0.2)' }}>
                    ● LIVE SPATIAL TRACKING
                  </span>
                </div>
                <StoreLayoutMap
                  apiBase={API_BASE}
                  storeId={selectedStore}
                  metrics={activeMetrics}
                  speed={speed}
                  onRestartSimulation={handleRestartSimulation}
                />
              </div>

              {/* Main chart grid */}
              <div className="primary-grid">
                {/* Funnel */}
                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M4 6h16M7 12h10M10 18h4" />
                    </svg>
                    Conversion Funnel
                  </div>
                  <FunnelChart stages={funnelData} />
                </div>

                {/* Queue + Heatmap stacked */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div className="panel-card">
                    <div className="panel-title">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                        <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
                      </svg>
                      Checkout Queue
                    </div>
                    <QueueTelemetry queueDepth={activeMetrics.queue_depth} />
                  </div>

                  <div className="panel-card">
                    <div className="panel-title">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                        <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
                        <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
                      </svg>
                      Zone Dwell Heatmap
                    </div>
                    <HeatmapChart zones={activeMetrics.avg_dwell_per_zone} />
                  </div>
                </div>
              </div>

              {/* Bottom grid: Timeline + Anomalies */}
              <div className="secondary-grid">
                <div className="panel-card" style={{ gridColumn: 'span 2' }}>
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
                    </svg>
                    Visitor Timeline
                    <span className="panel-title-badge">LAST {activeHistory?.unique_visitors?.length ?? 0} pts</span>
                  </div>
                  <VisitorTimeline history={activeHistory} />
                </div>

                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    Active Anomalies
                    {anomalies.length > 0 && (
                      <span className="panel-title-badge" style={{ background: 'rgba(239,68,68,0.1)', color: '#f87171', borderColor: 'rgba(239,68,68,0.2)' }}>
                        {anomalies.length} alerts
                      </span>
                    )}
                  </div>
                  <AnomaliesLog anomalies={anomalies} />
                </div>
              </div>
            </>
          )}

          {/* ==================== ANALYTICS VIEW ==================== */}
          {activeView === 'analytics' && (
            <>
              <div className="kpi-grid">
                <MetricCard title="Total Visitors" value={activeMetrics.unique_visitors} subtext="Unique entries" type="visitors" history={activeHistory?.unique_visitors} />
                <MetricCard title="Conversion Rate" value={`${(activeMetrics.conversion_rate * 100).toFixed(1)}%`} subtext="Purchase rate" type="conversion" history={activeHistory?.conversion_rate} />
                <MetricCard title="Queue Depth" value={activeMetrics.queue_depth} subtext="Current queue" type="queue" history={activeHistory?.queue_depth} />
                <MetricCard title="Abandonment" value={`${(activeMetrics.abandonment_rate * 100).toFixed(1)}%`} subtext="Checkout exits" type="abandonment" history={activeHistory?.abandonment_rate} />
              </div>

              <div className="primary-grid">
                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
                    </svg>
                    Visitor Volume Over Time
                  </div>
                  <VisitorTimeline history={activeHistory} />
                </div>

                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M4 6h16M7 12h10M10 18h4" />
                    </svg>
                    Conversion Funnel Analysis
                  </div>
                  <FunnelChart stages={funnelData} />
                </div>
              </div>

              <div className="secondary-grid">
                <div className="panel-card" style={{ gridColumn: 'span 2' }}>
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
                      <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
                    </svg>
                    Zone Traffic Heatmap
                  </div>
                  <HeatmapChart zones={activeMetrics.avg_dwell_per_zone} />
                </div>

                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
                    </svg>
                    Checkout Performance
                  </div>
                  <QueueTelemetry queueDepth={activeMetrics.queue_depth} />
                </div>
              </div>
            </>
          )}

          {/* ==================== EVENTS VIEW ==================== */}
          {activeView === 'events' && (
            <>
              <div className="primary-grid">
                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <circle cx="12" cy="12" r="2" /><path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14" />
                    </svg>
                    Live CCTV Event Feed
                    <span className="panel-title-badge">STREAMING</span>
                  </div>
                  <LiveEventTicker apiBase={API_BASE} storeId={selectedStore} />
                </div>

                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    Active Anomalies
                    {anomalies.length > 0 && (
                      <span className="panel-title-badge" style={{ background: 'rgba(239,68,68,0.1)', color: '#f87171', borderColor: 'rgba(239,68,68,0.2)' }}>
                        {anomalies.length}
                      </span>
                    )}
                  </div>
                  <AnomaliesLog anomalies={anomalies} />
                </div>
              </div>

              <div className="panel-card">
                <div className="panel-title">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M12 2a10 10 0 0 1 0 20A10 10 0 0 1 12 2z" />
                    <path d="M12 8v4M12 16h.01" />
                  </svg>
                  System Insights
                </div>
                <InsightCards metrics={activeMetrics} anomalyCount={anomalies.length} />
              </div>
            </>
          )}

          {/* ==================== COMPARISON VIEW ==================== */}
          {activeView === 'comparison' && (
            <>
              <div className="panel-card">
                <div className="panel-title">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" />
                    <line x1="6" y1="20" x2="6" y2="14" />
                  </svg>
                  Multi-Store Performance Comparison
                  <span className="panel-title-badge">{STORE_IDS.length} Stores</span>
                </div>
                <StoreComparison
                  storesData={storesData}
                  selectedStore={selectedStore}
                  storeIds={STORE_IDS}
                />
              </div>

              <div className="secondary-grid">
                {STORE_IDS.map((sid) => {
                  const m = storesData[sid];
                  const h = metricHistory[sid];
                  if (!m) return (
                    <div key={sid} className="panel-card">
                      <div className="panel-title" style={{ marginBottom: 0 }}>
                        {sid.replace('STORE_', '').replace(/_/g, ' — ')}
                      </div>
                      <div className="no-data" style={{ height: '80px' }}>No data yet</div>
                    </div>
                  );
                  return (
                    <div key={sid} className="panel-card">
                      <div className="panel-title">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
                          <polyline points="9 22 9 12 15 12 15 22" />
                        </svg>
                        {sid.replace('STORE_', '').replace(/_/g, ' — ')}
                        {sid === selectedStore && <span className="panel-title-badge">ACTIVE</span>}
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <MetricCard title="Visitors" value={m.unique_visitors} subtext="" type="visitors" history={h?.unique_visitors} />
                        <MetricCard title="Conv. Rate" value={`${(m.conversion_rate * 100).toFixed(1)}%`} subtext="" type="conversion" history={h?.conversion_rate} />
                      </div>
                    </div>
                  );
                })}
                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M12 2a10 10 0 0 1 0 20A10 10 0 0 1 12 2z" />
                      <path d="M12 8v4M12 16h.01" />
                    </svg>
                    Network Insights
                  </div>
                  <InsightCards metrics={activeMetrics} anomalyCount={anomalies.length} />
                </div>
              </div>
            </>
          )}

          {/* ==================== CUSTOMER FLOW MAP VIEW ==================== */}
          {activeView === 'layout' && (
            <>
              {/* Live metrics strip while watching layout */}
              <div className="kpi-grid">
                <MetricCard
                  title="Total Visitors"
                  value={activeMetrics.unique_visitors}
                  subtext="Tracked via CV pipeline"
                  type="visitors"
                  glow={isFlashed}
                  history={activeHistory?.unique_visitors}
                />
                <MetricCard
                  title="Conversion Rate"
                  value={`${(activeMetrics.conversion_rate * 100).toFixed(1)}%`}
                  subtext="Purchases / entries"
                  type="conversion"
                  glow={isFlashed}
                  history={activeHistory?.conversion_rate}
                />
                <MetricCard
                  title="Checkout Queue"
                  value={activeMetrics.queue_depth}
                  subtext="Waiting in line"
                  type="queue"
                  glow={isFlashed}
                  history={activeHistory?.queue_depth}
                />
                <MetricCard
                  title="Abandonment"
                  value={`${(activeMetrics.abandonment_rate * 100).toFixed(1)}%`}
                  subtext="Queue desertions"
                  type="abandonment"
                  glow={isFlashed}
                  history={activeHistory?.abandonment_rate}
                />
              </div>

              {/* Full-width store layout with customer movement */}
              <div className="panel-card" style={{ padding: '0', overflow: 'hidden' }}>
                <div className="panel-title" style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
                  </svg>
                  Live Customer Flow — {selectedStore === 'ST1008' ? 'Brigade Road' : selectedStore === 'STORE_BLR_002' ? 'Bengaluru Central' : 'Mumbai 1076'}
                  <span className="panel-title-badge" style={{ background: 'rgba(200,85,255,0.1)', color: '#c855ff', borderColor: 'rgba(200,85,255,0.2)' }}>
                    ● SPATIAL TRACKING
                  </span>
                  <span className="panel-title-badge" style={{ marginLeft: '6px', background: 'rgba(0,255,200,0.08)', color: '#00ffc8', borderColor: 'rgba(0,255,200,0.15)' }}>
                    {activeMetrics.unique_visitors} ACTIVE
                  </span>
                </div>
                <div style={{ padding: '20px' }}>
                  <StoreLayoutMap
                    apiBase={API_BASE}
                    storeId={selectedStore}
                    metrics={activeMetrics}
                    speed={speed}
                    onRestartSimulation={handleRestartSimulation}
                  />
                </div>
              </div>

              {/* Zone traffic breakdown */}
              <div className="primary-grid">
                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
                      <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
                    </svg>
                    Zone Dwell Heatmap
                  </div>
                  <HeatmapChart zones={activeMetrics.avg_dwell_per_zone} />
                </div>
                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M4 6h16M7 12h10M10 18h4" />
                    </svg>
                    Conversion Funnel
                  </div>
                  <FunnelChart stages={funnelData} />
                </div>
              </div>

              {/* Anomalies */}
              {anomalies.length > 0 && (
                <div className="panel-card">
                  <div className="panel-title">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                    Zone Anomalies
                    <span className="panel-title-badge" style={{ background: 'rgba(239,68,68,0.1)', color: '#f87171', borderColor: 'rgba(239,68,68,0.2)' }}>
                      {anomalies.length} alerts
                    </span>
                  </div>
                  <AnomaliesLog anomalies={anomalies} />
                </div>
              )}
            </>
          )}


        </div>
      </main>
    </div>
  );
};

export default App;

