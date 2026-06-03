import React from 'react';

interface QueueTelemetryProps {
  queueDepth: number;
}

const MAX_CAPACITY = 6;

export const QueueTelemetry: React.FC<QueueTelemetryProps> = ({ queueDepth }) => {
  const isSpike = queueDepth >= 4;
  const capacityPct = Math.min((queueDepth / MAX_CAPACITY) * 100, 100);

  // SVG Gauge arc values
  const R = 60;
  const strokeW = 10;
  const cx = 70;
  const cy = 70;
  const startAngle = -200;
  const endAngle = 20;
  const totalSweep = endAngle - startAngle;
  const filled = (capacityPct / 100) * totalSweep;

  function polarToXY(angle: number, r: number) {
    const rad = ((angle - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function describeArc(startDeg: number, endDeg: number) {
    const s = polarToXY(startDeg, R);
    const e = polarToXY(endDeg, R);
    const large = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y}`;
  }

  const trackPath = describeArc(startAngle, endAngle);
  const fillPath = describeArc(startAngle, startAngle + filled);
  const gaugeColor = isSpike ? '#ef4444' : queueDepth >= 2 ? '#f59e0b' : '#10b981';

  return (
    <div className="queue-layout">
      {/* Gauge */}
      <div className="queue-gauge-wrap">
        <svg viewBox="0 0 140 100" className="queue-gauge-svg">
          {/* Track */}
          <path
            d={trackPath}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={strokeW}
            strokeLinecap="round"
          />
          {/* Fill */}
          <path
            d={fillPath}
            fill="none"
            stroke={gaugeColor}
            strokeWidth={strokeW}
            strokeLinecap="round"
            style={{
              filter: `drop-shadow(0 0 6px ${gaugeColor})`,
              transition: 'stroke 0.4s, filter 0.4s',
            }}
          />
          {/* Center value */}
          <text
            x={cx}
            y={cy - 4}
            textAnchor="middle"
            fill={gaugeColor}
            fontSize="24"
            fontWeight="800"
            fontFamily="Inter, sans-serif"
            style={{ transition: 'fill 0.4s' }}
          >
            {queueDepth}
          </text>
          <text x={cx} y={cy + 14} textAnchor="middle" fill="#475569" fontSize="9" fontWeight="600" fontFamily="Inter, sans-serif">
            / {MAX_CAPACITY} MAX
          </text>
        </svg>

        <div className={`queue-status-pill ${isSpike ? 'warn' : 'normal'}`}>
          <span style={{ fontSize: '0.7rem' }}>{isSpike ? '🚨' : '✅'}</span>
          {isSpike ? 'Queue Spike Detected' : 'Flow Normal'}
        </div>
      </div>

      {/* Customer dots */}
      <div className="queue-dots-row">
        {Array.from({ length: MAX_CAPACITY }).map((_, idx) => {
          const occupied = idx < queueDepth;
          const danger = occupied && isSpike;
          return (
            <div
              key={idx}
              className={`queue-dot ${occupied ? (danger ? 'danger' : 'occupied') : 'empty'}`}
              title={occupied ? `Customer ${idx + 1}` : 'Empty slot'}
            >
              {occupied ? '👤' : ''}
            </div>
          );
        })}
        {queueDepth > MAX_CAPACITY && (
          <div className="queue-dot danger" style={{ fontSize: '0.72rem', fontWeight: 800, color: '#ef4444' }}>
            +{queueDepth - MAX_CAPACITY}
          </div>
        )}
      </div>

      {/* Capacity bar */}
      <div className="queue-capacity-bar">
        <div className="queue-capacity-labels">
          <span>Queue Load</span>
          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>
            {capacityPct.toFixed(0)}%
          </span>
        </div>
        <div className="queue-capacity-track">
          <div
            className={`queue-capacity-fill ${isSpike ? 'danger' : 'normal'}`}
            style={{ width: `${capacityPct}%`, transition: 'width 0.5s cubic-bezier(0.16,1,0.3,1)' }}
          />
        </div>
      </div>
    </div>
  );
};

export default QueueTelemetry;
