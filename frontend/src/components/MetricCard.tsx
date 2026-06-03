import React from 'react';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtext: string;
  type: 'visitors' | 'conversion' | 'queue' | 'abandonment';
  glow?: boolean;
  delta?: number;
  history?: number[];
}

const ICONS: Record<string, React.ReactNode> = {
  visitors: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  ),
  conversion: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1" y="4" width="22" height="16" rx="2" ry="2" />
      <line x1="1" y1="10" x2="23" y2="10" />
    </svg>
  ),
  queue: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <line x1="3" y1="6" x2="3.01" y2="6" />
      <line x1="3" y1="12" x2="3.01" y2="12" />
      <line x1="3" y1="18" x2="3.01" y2="18" />
    </svg>
  ),
  abandonment: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <polyline points="16 17 21 12 16 7" />
      <line x1="21" y1="12" x2="9" y2="12" />
    </svg>
  ),
};

// Generate realistic demo history seeded from a starting value
function generateDemoSeries(currentValue: number, count = 15, volatility = 0.08): number[] {
  const series: number[] = [];
  let v = Math.max(currentValue * 0.7, 1);
  for (let i = 0; i < count; i++) {
    v = Math.max(0, v + (Math.random() - 0.45) * v * volatility + (currentValue - v) * 0.1);
    series.push(Number(v.toFixed(4)));
  }
  return series;
}

function renderSparkline(history: number[], type: string) {
  if (history.length < 2) return null;
  const W = 200;
  const H = 32;
  const pad = 2;
  const min = Math.min(...history);
  const max = Math.max(...history);
  const range = max - min || 1;

  const pts = history.map((v, i) => ({
    x: pad + (i / (history.length - 1)) * (W - pad * 2),
    y: pad + (H - pad * 2) - ((v - min) / range) * (H - pad * 2),
  }));

  const linePath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  const areaPath = `${linePath} L ${pts[pts.length - 1].x} ${H} L ${pad} ${H} Z`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={`card-sparkline ${type}`}
      preserveAspectRatio="none"
    >
      <path d={areaPath} className="card-sparkline-area" />
      <path d={linePath} />
    </svg>
  );
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title, value, subtext, type, glow = false, delta, history = [],
}) => {
  const getDeltaLabel = () => {
    if (delta === undefined || delta === null) return null;
    if (delta > 0) return { cls: 'up', label: `+${delta > 0.01 ? (delta * 100).toFixed(1) + '%' : delta}` };
    if (delta < 0) return { cls: 'down', label: `${delta > -0.01 ? (delta * 100).toFixed(1) + '%' : delta}` };
    return { cls: 'neutral', label: '—' };
  };

  const deltaInfo = getDeltaLabel();

  // Parse numeric value for demo seed
  const numericValue = typeof value === 'number' ? value : parseFloat(String(value).replace('%', ''));
  const isDemo = history.length < 2;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const demoHistory = React.useMemo(() => generateDemoSeries(isNaN(numericValue) || numericValue === 0 ? 50 : numericValue), []);
  const displayHistory = isDemo ? demoHistory : history;

  return (
    <div className={`metric-card ${type} ${glow ? 'flash' : ''}`}>
      <div className="card-header">
        <div className="card-label-group">
          <div className="card-icon-wrap">
            {ICONS[type]}
          </div>
          <span className="card-title">{title}</span>
        </div>
        {deltaInfo && (
          <span className={`delta-badge ${deltaInfo.cls}`}>
            {deltaInfo.label}
          </span>
        )}
      </div>
      <div className="card-value">{value}</div>
      <div className="card-subtext">{subtext}</div>
      <div style={{ opacity: isDemo ? 0.45 : 1, transition: 'opacity 0.5s' }}>
        {renderSparkline(displayHistory, type)}
      </div>
    </div>
  );
};

export default MetricCard;
