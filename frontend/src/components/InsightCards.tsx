import React from 'react';
import type { StoreMetrics } from '../hooks/useStoreSSE';

interface InsightCardsProps {
  metrics: StoreMetrics;
  anomalyCount: number;
}

interface Insight {
  icon: string;
  level: 'good' | 'warn' | 'info' | 'critical';
  title: string;
  body: string;
}

function generateInsights(m: StoreMetrics, anomalyCount: number): Insight[] {
  const insights: Insight[] = [];

  // Visitor volume
  if (m.unique_visitors > 80) {
    insights.push({ icon: '🔥', level: 'warn', title: 'High Foot Traffic', body: `${m.unique_visitors} unique visitors — consider opening an additional checkout lane.` });
  } else if (m.unique_visitors > 30) {
    insights.push({ icon: '📈', level: 'good', title: 'Healthy Traffic Volume', body: `${m.unique_visitors} visitors active. Store is operating in optimal traffic range.` });
  } else {
    insights.push({ icon: '📉', level: 'info', title: 'Low Visitor Count', body: `Only ${m.unique_visitors} visitors detected. Consider running a promotional activity.` });
  }

  // Conversion rate
  const convPct = (m.conversion_rate * 100).toFixed(1);
  if (m.conversion_rate >= 0.3) {
    insights.push({ icon: '✅', level: 'good', title: 'Strong Conversion Rate', body: `${convPct}% of visitors made a purchase — above industry average (20-25%).` });
  } else if (m.conversion_rate >= 0.1) {
    insights.push({ icon: '🎯', level: 'info', title: 'Conversion Opportunity', body: `${convPct}% conversion rate. Targeted promotions near billing could lift this.` });
  } else {
    insights.push({ icon: '⚠️', level: 'warn', title: 'Low Conversion Rate', body: `${convPct}% conversion. Investigate browsing patterns in high-dwell zones.` });
  }

  // Queue depth
  if (m.queue_depth >= 4) {
    insights.push({ icon: '🚨', level: 'critical', title: 'Checkout Congestion', body: `Queue depth ${m.queue_depth} is critically high. Open additional billing counters immediately.` });
  } else if (m.queue_depth >= 2) {
    insights.push({ icon: '⏳', level: 'warn', title: 'Queue Building Up', body: `${m.queue_depth} customers waiting. Monitor closely and prep a second counter.` });
  } else {
    insights.push({ icon: '✅', level: 'good', title: 'Checkout Flow Normal', body: `Queue depth ${m.queue_depth} — customers are being served without significant wait.` });
  }

  // Abandonment rate
  const abandonPct = (m.abandonment_rate * 100).toFixed(1);
  if (m.abandonment_rate >= 0.4) {
    insights.push({ icon: '🚪', level: 'critical', title: 'High Abandonment Alert', body: `${abandonPct}% of customers are abandoning checkout. Investigate queue friction.` });
  } else if (m.abandonment_rate >= 0.2) {
    insights.push({ icon: '📊', level: 'warn', title: 'Moderate Abandonment', body: `${abandonPct}% abandonment. Review queue UX and cashier responsiveness.` });
  } else {
    insights.push({ icon: '✅', level: 'good', title: 'Low Abandonment Rate', body: `${abandonPct}% abandonment. Excellent checkout retention — customers completing purchases.` });
  }

  // Anomalies
  if (anomalyCount > 3) {
    insights.push({ icon: '🔔', level: 'critical', title: `${anomalyCount} Active Anomalies`, body: 'Multiple anomalies detected. Security and ops teams should review the alert log.' });
  } else if (anomalyCount > 0) {
    insights.push({ icon: '⚠️', level: 'warn', title: `${anomalyCount} Anomaly Detected`, body: 'System has flagged unusual patterns. Review the anomalies panel for details.' });
  } else {
    insights.push({ icon: '🛡️', level: 'good', title: 'All Systems Normal', body: 'No anomalies detected. Store operations are within expected parameters.' });
  }

  return insights.slice(0, 4);
}

export const InsightCards: React.FC<InsightCardsProps> = ({ metrics, anomalyCount }) => {
  const insights = generateInsights(metrics, anomalyCount);

  return (
    <div className="insights-grid">
      {insights.map((ins, i) => (
        <div key={i} className="insight-card">
          <div className={`insight-icon ${ins.level}`}>{ins.icon}</div>
          <div className="insight-text">
            <div className="insight-title">{ins.title}</div>
            <div className="insight-body">{ins.body}</div>
          </div>
        </div>
      ))}
    </div>
  );
};

export default InsightCards;
