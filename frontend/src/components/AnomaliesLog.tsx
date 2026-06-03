import React, { useState } from 'react';

export interface Anomaly {
  anomaly_id: string;
  anomaly_type: string;
  severity: 'INFO' | 'WARN' | 'CRITICAL';
  description: string;
  suggested_action: string;
  detected_at: string;
  zone_id?: string;
  value?: number;
}

interface AnomaliesLogProps {
  anomalies: Anomaly[];
}

const SEVERITY_ICON: Record<string, string> = {
  CRITICAL: '🚨',
  WARN: '⚠️',
  INFO: 'ℹ️',
};

export const AnomaliesLog: React.FC<AnomaliesLogProps> = ({ anomalies }) => {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (anomalies.length === 0) {
    return (
      <div className="no-anomalies">
        <div className="no-anomalies-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            <path d="M9 12l2 2 4-4" />
          </svg>
        </div>
        <p className="no-anomalies-text">System Normal — No active anomalies</p>
      </div>
    );
  }

  // Sort: CRITICAL first, then WARN, then INFO
  const sorted = [...anomalies].sort((a, b) => {
    const order = { CRITICAL: 0, WARN: 1, INFO: 2 };
    return (order[a.severity] ?? 9) - (order[b.severity] ?? 9);
  });

  return (
    <div className="anomalies-container">
      {sorted.map((anom) => {
        const isOpen = expanded.has(anom.anomaly_id);
        return (
          <div
            key={anom.anomaly_id}
            className={`anomaly-item ${anom.severity}`}
            onClick={() => toggle(anom.anomaly_id)}
            style={{ cursor: 'pointer' }}
          >
            <div className="anomaly-header-row">
              <span className={`severity-pill ${anom.severity}`}>
                {SEVERITY_ICON[anom.severity]} {anom.severity}
              </span>
              <span className="anomaly-type-text">
                {anom.anomaly_type.replace(/_/g, ' ')}
              </span>
              {anom.zone_id && (
                <span style={{
                  fontSize: '0.62rem',
                  color: '#64748b',
                  background: 'rgba(255,255,255,0.03)',
                  border: '1px solid rgba(255,255,255,0.06)',
                  borderRadius: '4px',
                  padding: '1px 6px',
                }}>
                  {anom.zone_id.replace(/_/g, ' ')}
                </span>
              )}
              <span className="anomaly-time">
                {new Date(anom.detected_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
              <span style={{ color: '#475569', fontSize: '0.7rem', flexShrink: 0 }}>
                {isOpen ? '▲' : '▼'}
              </span>
            </div>

            {isOpen && (
              <>
                <p className="anomaly-desc">{anom.description}</p>
                <div className="anomaly-action">
                  <div style={{ flex: 1 }}>
                    <span className="action-label">Recommended Action</span>
                    <span className="action-text">{anom.suggested_action}</span>
                  </div>
                </div>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default AnomaliesLog;
