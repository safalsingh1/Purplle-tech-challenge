import React, { useState, useEffect } from 'react';

interface TopBarProps {
  activeView: string;
  storeId: string;
  lastUpdated: string | null;
  onStoreChange?: (storeId: string) => void;
}

const VIEW_TITLES: Record<string, string> = {
  dashboard: 'Live Dashboard',
  analytics: 'Deep Analytics',
  events: 'Event Feed',
  comparison: 'Store Comparison',
  cameras: 'Camera Feeds',
};

const STORE_IDS = ['STORE_BLR_002', 'ST1008'];

const STORE_NAMES: Record<string, string> = {
  STORE_BLR_002: '🏪 Bengaluru Central',
  ST1008: '🏪 Brigade Road',
};

export const TopBar: React.FC<TopBarProps> = ({ activeView, storeId, lastUpdated, onStoreChange }) => {
  const [clock, setClock] = useState('');

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setClock(now.toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="topbar">
      <div className="topbar-left">
        <div className="topbar-title">{VIEW_TITLES[activeView] ?? activeView}</div>
        <div className="topbar-breadcrumb" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>APEX Intelligence</span>
          <span style={{ color: '#334155' }}>›</span>
          <select
            value={storeId}
            onChange={(e) => onStoreChange && onStoreChange(e.target.value)}
            style={{
              background: 'rgba(15, 23, 42, 0.65)',
              backdropFilter: 'blur(8px)',
              border: '1px solid rgba(200, 85, 255, 0.4)',
              borderRadius: '20px',
              color: '#f8fafc',
              fontSize: '0.78rem',
              fontWeight: 700,
              padding: '4px 10px',
              outline: 'none',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
              boxShadow: '0 0 12px rgba(200, 85, 255, 0.1)',
            }}
          >
            {STORE_IDS.map((id) => (
              <option key={id} value={id} style={{ background: '#09090f', color: '#f8fafc' }}>
                {STORE_NAMES[id] || id.replace('STORE_', '').replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          {lastUpdated && (
            <>
              <span style={{ color: '#334155' }}>›</span>
              <span style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.72rem', fontWeight: 600 }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', display: 'inline-block', animation: 'pulse 1.5s infinite' }} />
                Updated now
              </span>
            </>
          )}
        </div>
      </div>

      <div className="topbar-right">
        {lastUpdated && (
          <div className="data-freshness">
            <span className="freshness-dot" />
            Live data received
          </div>
        )}
        <div className="topbar-clock">{clock}</div>
      </div>
    </div>
  );
};

export default TopBar;
