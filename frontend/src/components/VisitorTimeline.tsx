import React from 'react';
import type { MetricHistory } from '../hooks/useStoreSSE';

interface VisitorTimelineProps {
  history: MetricHistory | undefined;
}

// Generate realistic-looking sample visitor data for demo purposes
function generateDemoHistory(): { data: number[]; timestamps: string[] } {
  const now = Date.now();
  const count = 20;
  const data: number[] = [];
  const timestamps: string[] = [];

  // Start at ~40 visitors, with natural noise and a mid-day spike
  let val = 40;
  for (let i = count - 1; i >= 0; i--) {
    const t = now - i * 30000; // every 30 seconds back
    // Add realistic noise + a small upward trend
    val = Math.max(10, Math.min(120, val + (Math.random() - 0.42) * 8 + 0.5));
    data.push(Math.round(val));
    timestamps.push(new Date(t).toISOString());
  }

  return { data, timestamps };
}

export const VisitorTimeline: React.FC<VisitorTimelineProps> = ({ history }) => {
  const liveData = history?.unique_visitors ?? [];
  const liveTimestamps = history?.timestamps ?? [];

  const isDemo = liveData.length < 2;
  const demo = React.useMemo(() => generateDemoHistory(), []);

  const data = isDemo ? demo.data : liveData;
  const timestamps = isDemo ? demo.timestamps : liveTimestamps;

  const W = 600;
  const H = 110;
  const padX = 8;
  const padY = 12;
  const innerW = W - padX * 2;
  const innerH = H - padY * 2;

  const minVal = Math.min(...data);
  const maxVal = Math.max(...data);
  const range = maxVal - minVal || 1;

  const points = data.map((v, i) => {
    const x = padX + (i / (data.length - 1)) * innerW;
    const y = padY + innerH - ((v - minVal) / range) * innerH;
    return { x, y, v };
  });

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  const areaPath = `${linePath} L ${points[points.length - 1].x} ${H} L ${padX} ${H} Z`;

  // Horizontal grid lines
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: padY + innerH - f * innerH,
    val: Math.round(minVal + f * range),
  }));

  // 5 evenly spaced x-labels
  const labelIndices = [0, Math.floor(data.length / 4), Math.floor(data.length / 2), Math.floor((3 * data.length) / 4), data.length - 1];
  const labelSet = new Set(labelIndices);
  const xLabels = data
    .map((_, i) => i)
    .filter((i) => labelSet.has(i))
    .map((i) => ({
      x: (i / (data.length - 1)) * 100,
      label: timestamps[i]
        ? new Date(timestamps[i]).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        : '',
    }));

  const lastPoint = points[points.length - 1];

  return (
    <div className="timeline-chart-wrap">
      {/* Demo badge */}
      {isDemo && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          marginBottom: '10px',
          fontSize: '0.65rem',
          fontWeight: 600,
          color: '#8b5cf6',
          opacity: 0.75,
        }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" width="11" height="11">
            <circle cx="12" cy="12" r="10" /><path d="M12 8v4M12 16h.01" />
          </svg>
          Sample data — start the replay script to see live metrics
        </div>
      )}

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="timeline-svg"
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <linearGradient id="timelineGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stopColor={isDemo ? '#64748b' : '#8b5cf6'} stopOpacity="1" />
            <stop offset="100%" stopColor={isDemo ? '#64748b' : '#8b5cf6'} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Grid lines */}
        {gridLines.map((g, i) => (
          <line
            key={i}
            x1={padX}
            y1={g.y}
            x2={W - padX}
            y2={g.y}
            className="timeline-grid-line"
          />
        ))}

        {/* Y-axis value labels */}
        {gridLines.filter((_, i) => i % 2 === 0).map((g, i) => (
          <text
            key={i}
            x={padX - 2}
            y={g.y + 3}
            fill="rgba(255,255,255,0.2)"
            fontSize="7"
            textAnchor="end"
            fontFamily="JetBrains Mono, monospace"
          >
            {g.val}
          </text>
        ))}

        {/* Area fill */}
        <path d={areaPath} fill="url(#timelineGrad)" className="timeline-area" />

        {/* Line */}
        <path
          d={linePath}
          className="timeline-line"
          style={{ stroke: isDemo ? '#64748b' : '#8b5cf6' }}
        />

        {/* Last point dot */}
        <circle
          cx={lastPoint.x}
          cy={lastPoint.y}
          r={4}
          className="timeline-dot"
          style={{ fill: isDemo ? '#64748b' : '#8b5cf6', filter: `drop-shadow(0 0 4px ${isDemo ? '#64748b' : '#8b5cf6'})` }}
        />

        {/* Value label at last point */}
        <text
          x={lastPoint.x - 4}
          y={lastPoint.y - 8}
          fill={isDemo ? '#64748b' : '#a78bfa'}
          fontSize="10"
          fontWeight="700"
          fontFamily="JetBrains Mono, monospace"
          textAnchor="middle"
        >
          {lastPoint.v}
        </text>
      </svg>

      <div className="timeline-x-labels">
        {xLabels.map((l, i) => (
          <span key={i} style={{ width: '20%', textAlign: 'center' }}>{l.label}</span>
        ))}
      </div>
    </div>
  );
};

export default VisitorTimeline;
