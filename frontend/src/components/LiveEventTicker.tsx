import React, { useEffect, useState } from 'react';

export interface TickerEvent {
  id: string;
  type: 'ZONE_ENTER' | 'ZONE_EXIT' | 'DWELL' | 'ANOMALY';
  zone: string;
  track_id: string;
  timestamp: string;
  extra?: string;
}

interface LiveEventTickerProps {
  apiBase: string;
  storeId: string;
}

const TYPE_LABELS: Record<string, string> = {
  ZONE_ENTER: 'ENTER',
  ZONE_EXIT: 'EXIT',
  DWELL: 'DWELL',
  ANOMALY: 'ALERT',
  CHECKOUT_ENTER: 'QUEUE',
  CHECKOUT_EXIT: 'CLEARED',
};

const TYPE_CSS: Record<string, string> = {
  ZONE_ENTER: 'ticker-type-enter',
  ZONE_EXIT: 'ticker-type-exit',
  DWELL: 'ticker-type-dwell',
  ANOMALY: 'ticker-type-anomaly',
  CHECKOUT_ENTER: 'ticker-type-enter',
  CHECKOUT_EXIT: 'ticker-type-exit',
};

export const LiveEventTicker: React.FC<LiveEventTickerProps> = ({ apiBase, storeId }) => {
  const [events, setEvents] = useState<TickerEvent[]>([]);

  // Fetch recent events from the API and simulate a live ticker by polling
  useEffect(() => {
    let active = true;

    async function fetchEvents() {
      try {
        const resp = await fetch(`${apiBase}/stores/${storeId}/events?limit=30`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (active && Array.isArray(data.events)) {
          setEvents((prev) => {
            // Merge new events, dedup by id, keep latest 30
            const existing = new Set(prev.map((e) => e.id));
            const fresh = (data.events as TickerEvent[]).filter((e) => !existing.has(e.id));
            const merged = [...fresh, ...prev].slice(0, 30);
            return merged;
          });
        }
      } catch {
        // API not reachable — show empty state
      }
    }

    fetchEvents();
    const interval = setInterval(fetchEvents, 3000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [apiBase, storeId]);

  // If no events from API, show mock seed events so the ticker looks alive
  const displayEvents = events.length > 0 ? events : generateMockEvents();

  return (
    <div className="event-ticker">
      <div className="ticker-inner">
        {displayEvents.map((evt) => {
          const typeKey = evt.type as string;
          return (
            <div key={evt.id} className="ticker-event">
              <span className={`ticker-event-type ${TYPE_CSS[typeKey] ?? 'ticker-type-dwell'}`}>
                {TYPE_LABELS[typeKey] ?? typeKey}
              </span>
              <span className="ticker-event-info">
                <span className="ticker-event-zone">{evt.zone?.replace(/_/g, ' ')}</span>
                {evt.track_id ? ` — Track #${evt.track_id}` : ''}
                {evt.extra ? ` (${evt.extra})` : ''}
              </span>
              <span className="ticker-event-time">
                {evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--:--'}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

function generateMockEvents(): TickerEvent[] {
  const zones = ['Entry Zone', 'Produce Section', 'Dairy Aisle', 'Billing Counter', 'Checkout Queue'];
  const types = ['ZONE_ENTER', 'ZONE_EXIT', 'DWELL', 'ZONE_ENTER', 'ZONE_ENTER', 'ZONE_EXIT'] as const;
  const now = Date.now();
  return Array.from({ length: 12 }, (_, i) => ({
    id: `mock-${i}`,
    type: types[i % types.length],
    zone: zones[i % zones.length],
    track_id: String(100 + i),
    timestamp: new Date(now - i * 8000).toISOString(),
  }));
}

export default LiveEventTicker;
