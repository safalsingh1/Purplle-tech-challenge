import React from 'react';

export interface FunnelStage {
  stage: string;
  count: number;
  drop_off_pct: number;
}

interface FunnelChartProps {
  stages: FunnelStage[];
}

const STAGE_COLORS = [
  { bar: 'linear-gradient(90deg, #8b5cf6, #a78bfa)', glow: 'rgba(139,92,246,0.3)' },
  { bar: 'linear-gradient(90deg, #06b6d4, #22d3ee)', glow: 'rgba(6,182,212,0.3)' },
  { bar: 'linear-gradient(90deg, #10b981, #34d399)', glow: 'rgba(16,185,129,0.3)' },
  { bar: 'linear-gradient(90deg, #f59e0b, #fbbf24)', glow: 'rgba(245,158,11,0.3)' },
  { bar: 'linear-gradient(90deg, #ef4444, #f87171)', glow: 'rgba(239,68,68,0.3)' },
];

export const FunnelChart: React.FC<FunnelChartProps> = ({ stages }) => {
  if (!stages || stages.length === 0) {
    return (
      <div className="no-data">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M4 6h16M7 12h10M10 18h4" strokeLinecap="round" />
        </svg>
        No funnel data available
      </div>
    );
  }

  const maxCount = stages[0]?.count || 1;

  return (
    <div className="funnel-container">
      <div className="funnel-stage-list">
        {stages.map((stage, idx) => {
          const ratio = stage.count / maxCount;
          const color = STAGE_COLORS[idx % STAGE_COLORS.length];

          return (
            <div key={stage.stage} className="funnel-stage-item">
              <div className="funnel-stage-header">
                <span className="funnel-stage-name">
                  {stage.stage.replace(/_/g, ' ')}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  {idx > 0 && stage.drop_off_pct > 0 && (
                    <span className="funnel-drop">↓ {stage.drop_off_pct}%</span>
                  )}
                  <span className="funnel-stage-count">{stage.count.toLocaleString()}</span>
                </div>
              </div>
              <div className="funnel-bar-track">
                <div
                  className="funnel-bar-fill"
                  style={{
                    width: `${ratio * 100}%`,
                    background: color.bar,
                    boxShadow: `0 0 8px ${color.glow}`,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Mini SVG trapezoid funnel diagram below the bars */}
      <div style={{ marginTop: '20px' }}>
        <svg
          viewBox="0 0 400 180"
          className="funnel-svg-wrap"
          style={{ width: '100%', height: '160px' }}
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            {STAGE_COLORS.map((c, i) => (
              <linearGradient key={i} id={`fg${i}`} x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor={c.bar.match(/#[a-f0-9]{6}/gi)?.[0] ?? '#8b5cf6'} stopOpacity="0.9" />
                <stop offset="100%" stopColor={c.bar.match(/#[a-f0-9]{6}/gi)?.[1] ?? '#a78bfa'} stopOpacity="0.9" />
              </linearGradient>
            ))}
            <filter id="fglow">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>
          {stages.map((stage, idx) => {
            const total = stages.length;
            const layerH = 160 / total;
            const maxCount = stages[0]?.count || 1;
            const curRatio = stage.count / maxCount;
            const nextRatio = stages[idx + 1] ? stages[idx + 1].count / maxCount : curRatio * 0.7;
            const W = 400;
            const yTop = idx * layerH + 4;
            const yBot = yTop + layerH - 6;
            const wTop = 300 * curRatio + 40;
            const wBot = 300 * nextRatio + 40;
            const xTL = (W - wTop) / 2;
            const xTR = xTL + wTop;
            const xBL = (W - wBot) / 2;
            const xBR = xBL + wBot;
            const path = `M ${xTL} ${yTop} L ${xTR} ${yTop} L ${xBR} ${yBot} L ${xBL} ${yBot} Z`;
            return (
              <g key={stage.stage}>
                <path d={path} fill={`url(#fg${idx % STAGE_COLORS.length})`} filter="url(#fglow)" opacity="0.15" />
                <path d={path} fill={`url(#fg${idx % STAGE_COLORS.length})`} stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
                <text
                  x={W / 2}
                  y={(yTop + yBot) / 2 + 5}
                  textAnchor="middle"
                  fill="rgba(255,255,255,0.9)"
                  fontSize="10"
                  fontWeight="700"
                  fontFamily="Inter, sans-serif"
                  letterSpacing="0.04em"
                >
                  {stage.stage.replace(/_/g, ' ').toUpperCase()}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
};

export default FunnelChart;
