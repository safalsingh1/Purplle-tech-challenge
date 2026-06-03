import { useState, useEffect, useCallback } from 'react';

export interface ZoneDwellMetric {
  zone_id: string;
  avg_dwell_seconds: number;
  visit_count: number;
}

export interface StoreMetrics {
  store_id: string;
  unique_visitors: number;
  conversion_rate: number;
  avg_dwell_per_zone: ZoneDwellMetric[];
  queue_depth: number;
  abandonment_rate: number;
  computed_at: string;
}

export interface SSEUpdateMessage {
  type: string;
  store_id: string;
  data: StoreMetrics;
}

export type ConnectionStatus = 'connecting' | 'live' | 'disconnected' | 'error';

export interface MetricHistory {
  unique_visitors: number[];
  conversion_rate: number[];
  queue_depth: number[];
  abandonment_rate: number[];
  timestamps: string[];
}

export interface MetricDeltas {
  unique_visitors: number;
  conversion_rate: number;
  queue_depth: number;
  abandonment_rate: number;
}

const MAX_HISTORY = 20;

// Use __API_URL__ injected by Vite's define config for production builds (Railway/Vercel).
declare const __API_URL__: string;

export function getApiUrl(): string {
  let url = 'http://localhost:8000';

  if (typeof __API_URL__ !== 'undefined' && __API_URL__ !== 'http://localhost:8000' && __API_URL__ !== '') {
    url = __API_URL__;
  } else if (typeof window !== 'undefined' && window.location) {
    const host = window.location.hostname;
    if (host !== 'localhost' && host !== '127.0.0.1' && host !== '0.0.0.0') {
      url = 'https://purplle-tech-challenge-production.up.railway.app';
    }
  }

  url = url.trim().replace(/\/$/, '');
  if (url && !/^https?:\/\//i.test(url)) {
    if (/^(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?$/i.test(url)) {
      url = 'http://' + url;
    } else {
      url = 'https://' + url;
    }
  }
  return url;
}

const _DEFAULT_API_URL = getApiUrl();

export function useStoreSSE(apiUrl: string = _DEFAULT_API_URL, storeIds: string[] = ['STORE_BLR_002', 'ST1008']) {
  const [storesData, setStoresData] = useState<Record<string, StoreMetrics>>({});
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const [lastUpdatedStore, setLastUpdatedStore] = useState<string | null>(null);
  const [metricHistory, setMetricHistory] = useState<Record<string, MetricHistory>>({});
  const [metricDeltas, setMetricDeltas] = useState<Record<string, MetricDeltas>>({});

  const updateHistory = useCallback((storeId: string, newMetrics: StoreMetrics) => {
    setMetricHistory((prev) => {
      const existing = prev[storeId] ?? {
        unique_visitors: [],
        conversion_rate: [],
        queue_depth: [],
        abandonment_rate: [],
        timestamps: [],
      };

      const append = <T,>(arr: T[], val: T): T[] => {
        const next = [...arr, val];
        return next.length > MAX_HISTORY ? next.slice(next.length - MAX_HISTORY) : next;
      };

      return {
        ...prev,
        [storeId]: {
          unique_visitors: append(existing.unique_visitors, newMetrics.unique_visitors),
          conversion_rate: append(existing.conversion_rate, newMetrics.conversion_rate),
          queue_depth: append(existing.queue_depth, newMetrics.queue_depth),
          abandonment_rate: append(existing.abandonment_rate, newMetrics.abandonment_rate),
          timestamps: append(existing.timestamps, newMetrics.computed_at),
        },
      };
    });

    setMetricDeltas((prev) => {
      setStoresData((prevMetrics) => {
        const old = prevMetrics[storeId];
        if (!old) return prevMetrics;
        const deltas: MetricDeltas = {
          unique_visitors: newMetrics.unique_visitors - old.unique_visitors,
          conversion_rate: newMetrics.conversion_rate - old.conversion_rate,
          queue_depth: newMetrics.queue_depth - old.queue_depth,
          abandonment_rate: newMetrics.abandonment_rate - old.abandonment_rate,
        };
        setMetricDeltas((d) => ({ ...d, [storeId]: deltas }));
        return prevMetrics;
      });
      return prev;
    });
  }, []);

  useEffect(() => {
    let eventSource: EventSource | null = null;
    let reconnectTimeout: number | null = null;
    let delay = 1000;

    function connect() {
      setConnectionStatus('connecting');
      eventSource = new EventSource(`${apiUrl}/dashboard/stream`);

      eventSource.onopen = () => {
        setConnectionStatus('live');
        delay = 1000;
      };

      eventSource.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'metrics') {
            updateHistory(message.store_id, message.data);
            setStoresData((prev) => ({
              ...prev,
              [message.store_id]: message.data,
            }));
            setLastUpdatedStore(message.store_id);
            setTimeout(() => setLastUpdatedStore(null), 1000);
          } else if (message.type === 'reset') {
            setStoresData({});
            setMetricHistory({});
            setMetricDeltas({});
            setLastUpdatedStore(null);
          }
        } catch {
          // heartbeats / unparseable
        }
      };

      eventSource.onerror = () => {
        setConnectionStatus('error');
        if (eventSource) eventSource.close();
        reconnectTimeout = window.setTimeout(() => {
          connect();
        }, delay);
        delay = Math.min(delay * 2, 30000);
      };
    }

    connect();

    return () => {
      if (eventSource) eventSource.close();
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
    };
  }, [apiUrl, updateHistory]);

  // Polling fallback when SSE is not live
  useEffect(() => {
    if (connectionStatus === 'live') return;

    let active = true;
    async function pollMetrics() {
      for (const storeId of storeIds) {
        try {
          const resp = await fetch(`${apiUrl}/stores/${storeId}/metrics`);
          if (resp.ok && active) {
            const data = await resp.json();
            updateHistory(storeId, data);
            setStoresData((prev) => ({
              ...prev,
              [storeId]: data,
            }));
          }
        } catch {
          // ignore poll errors
        }
      }
    }

    pollMetrics();
    const interval = setInterval(pollMetrics, 3000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [connectionStatus, apiUrl, storeIds, updateHistory]);

  return { storesData, connectionStatus, lastUpdatedStore, metricHistory, metricDeltas };
}
