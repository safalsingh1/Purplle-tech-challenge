import React from 'react';
import type { ZoneDwellMetric } from '../hooks/useStoreSSE';

interface HeatmapChartProps {
  zones: ZoneDwellMetric[];
}

function getHeatClass(ratio: number): string {
  if (ratio > 0.75) return 'heat-hot';
  if (ratio > 0.5) return 'heat-high';
  if (ratio > 0.25) return 'heat-med';
  return 'heat-low';
}

function formatDwell(secs: number): string {
  if (secs >= 60) return `${(secs / 60).toFixed(1)}m`;
  return `${secs.toFixed(0)}s`;
}

export const HeatmapChart: React.FC<HeatmapChartProps> = ({ zones }) => {
  if (!zones || zones.length === 0) {
    return (
      <div className="no-data">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
        No zone heatmap data
      </div>
    );
  }

  const sorted = [...zones].sort((a, b) => b.visit_count - a.visit_count);
  const maxVisits = Math.max(...sorted.map((z) => z.visit_count), 1);

  return (
    <div className="heatmap-grid-cells">
      {sorted.map((zone) => {
        const ratio = zone.visit_count / maxVisits;
        const heatClass = getHeatClass(ratio);

        return (
          <div key={zone.zone_id} className={`heatmap-cell ${heatClass}`}>
            <div className="heatmap-cell-zone">
              {zone.zone_id.replace(/_/g, ' ')}
            </div>
            <div className="heatmap-cell-dwell">
              {formatDwell(zone.avg_dwell_seconds)}
            </div>
            <div className="heatmap-heat-bar" style={{ width: `${ratio * 100}%` }} />
            <div className="heatmap-cell-meta">
              <span>{zone.visit_count} visits</span>
              <span>avg dwell</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default HeatmapChart;
