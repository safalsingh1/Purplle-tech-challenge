import React from 'react';
import type { StoreMetrics } from '../hooks/useStoreSSE';

interface StoreComparisonProps {
  storesData: Record<string, StoreMetrics>;
  selectedStore: string;
  storeIds: string[];
}

function formatStore(id: string) {
  return id.replace('STORE_', '').replace(/_/g, ' — ');
}

export const StoreComparison: React.FC<StoreComparisonProps> = ({
  storesData,
  selectedStore,
  storeIds,
}) => {
  const rows = storeIds.map((id) => {
    const m = storesData[id];
    return {
      id,
      visitors: m?.unique_visitors ?? '—',
      conversion: m ? `${(m.conversion_rate * 100).toFixed(1)}%` : '—',
      queue: m?.queue_depth ?? '—',
      abandonment: m ? `${(m.abandonment_rate * 100).toFixed(1)}%` : '—',
      updatedAt: m?.computed_at ? new Date(m.computed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—',
      isActive: id === selectedStore,
      hasData: !!m,
    };
  });

  return (
    <table className="comparison-table">
      <thead>
        <tr>
          <th>Store</th>
          <th>Visitors</th>
          <th>Conv. Rate</th>
          <th>Queue</th>
          <th>Abandon.</th>
          <th>Updated</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>
              <div className="store-name-cell">
                {row.hasData && <div className="store-active-dot" />}
                {formatStore(row.id)}
                {row.isActive && (
                  <span style={{
                    fontSize: '0.58rem',
                    background: 'rgba(139,92,246,0.12)',
                    color: '#a78bfa',
                    border: '1px solid rgba(139,92,246,0.25)',
                    borderRadius: '4px',
                    padding: '1px 6px',
                    fontWeight: 700,
                    letterSpacing: '0.04em',
                  }}>
                    ACTIVE
                  </span>
                )}
              </div>
            </td>
            <td className={`metric-value-cell ${row.isActive ? 'highlight' : ''}`}>{row.visitors}</td>
            <td className="metric-value-cell">{row.conversion}</td>
            <td className="metric-value-cell">{row.queue}</td>
            <td className="metric-value-cell">{row.abandonment}</td>
            <td className="metric-value-cell">{row.updatedAt}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

export default StoreComparison;
