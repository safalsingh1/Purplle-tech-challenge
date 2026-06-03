import React, { useState, useEffect } from 'react';

interface Camera {
  cam_id: string;
  name: string;
  filename: string;
  store_id: string;
  available: boolean;
  stream_url: string;
}

interface CameraFeedProps {
  apiBase: string;
  storeId: string;
  selectedCam?: string;
  onCameraChange?: (camId: string) => void;
}

const CAM_LABELS: Record<string, string> = {
  CAM_1: 'Secondary Zone (CCTV 1)',
  CAM_2: 'Main Zone (CCTV 2)',
  CAM_3: 'Entry/Exit (CCTV 3)',
  CAM_4: 'Secondary Entrance (CCTV 4)',
  CAM_5: 'Billing Queue (CCTV 5)',
  CAM_S2_ENTRY1: 'North Entry',
  CAM_S2_ENTRY2: 'South Entry',
  CAM_S2_ZONE: 'Main Floor Zone',
  CAM_S2_BILLING: 'Billing Area',
  CAM_ENTRY_01: 'Main Entry',
  CAM_FLOOR_01: 'Main Floor',
  CAM_BILLING_01: 'Billing Queue',
};

const CAM_ZONES_CONFIG: Record<string, { label: string; zones: { name: string; color: string }[] }> = {
  CAM_1: {
    label: 'Secondary Floor Zone',
    zones: [
      { name: 'Skincare', color: '#b43cff' },
      { name: 'Haircare', color: '#ff783c' },
    ]
  },
  CAM_2: {
    label: 'Main Floor Zone',
    zones: [
      { name: 'Skincare Aisles', color: '#b43cff' },
      { name: 'Fragrances Counter', color: '#3cc8ff' },
      { name: 'Wellness Section', color: '#3cffb4' }
    ]
  },
  CAM_3: {
    label: 'Entry / Exit',
    zones: [
      { name: 'Entry Threshold', color: '#00dc64' }
    ]
  },
  CAM_4: {
    label: 'Secondary Entry',
    zones: [
      { name: 'Entry Threshold', color: '#00dc64' }
    ]
  },
  CAM_5: {
    label: 'Billing & Queue',
    zones: [
      { name: 'Billing Counter', color: '#008cff' },
      { name: 'Billing Queue', color: '#0050dc' },
      { name: 'Impulse Buys', color: '#50c8ff' }
    ]
  },
  CAM_S2_ENTRY1: {
    label: 'North Entry',
    zones: [{ name: 'Entry Threshold', color: '#00dc64' }]
  },
  CAM_S2_ENTRY2: {
    label: 'South Entry',
    zones: [{ name: 'Entry Threshold', color: '#00dc64' }]
  },
  CAM_S2_ZONE: {
    label: 'Main Store Zone',
    zones: [
      { name: 'Skincare', color: '#b43cff' },
      { name: 'Haircare', color: '#ff783c' },
      { name: 'Wellness', color: '#3cffb4' }
    ]
  },
  CAM_S2_BILLING: {
    label: 'Billing Counter & Queue',
    zones: [
      { name: 'Billing Counter', color: '#008cff' },
      { name: 'Billing Queue', color: '#0050dc' }
    ]
  },
  CAM_ENTRY_01: {
    label: 'Main Entry',
    zones: [{ name: 'Entry Threshold', color: '#00dc64' }]
  },
  CAM_FLOOR_01: {
    label: 'Main Floor',
    zones: [
      { name: 'Left Shelf', color: '#b43cff' },
      { name: 'Center Display', color: '#ff783c' },
      { name: 'Lipstick Aisle', color: '#3cc8ff' }
    ]
  },
  CAM_BILLING_01: {
    label: 'Billing Area',
    zones: [
      { name: 'Billing Counter Queue', color: '#0050dc' }
    ]
  }
};

export const CameraFeed: React.FC<CameraFeedProps> = ({
  apiBase,
  storeId,
  selectedCam,
  onCameraChange,
}) => {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [localSelected, setLocalSelected] = useState<string | null>(null);
  const selected = selectedCam || localSelected;

  const setSelected = (val: string | null) => {
    setLocalSelected(val);
    if (onCameraChange && val) {
      onCameraChange(val);
    }
  };

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [yoloStats, setYoloStats] = useState<{ people: number; frame: number; fps: number } | null>(null);
  const [speed] = useState(1.0);
  const [switching, setSwitching] = useState(false);
  const [streamKey, setStreamKey] = useState(Date.now());
  
  const [streamError, setStreamError] = useState(false);

  // Reset stream error and refresh key when camera changes
  useEffect(() => {
    setStreamError(false);
    setStreamKey(Date.now());
  }, [selected]);

  // Poll backend stats for the selected camera
  useEffect(() => {
    let active = true;

    const fetchBackendStats = async () => {
      if (!selected) return;
      try {
        const r = await fetch(`${apiBase}/cameras/stats/${selected}`);
        if (r.ok && active) {
          const data = await r.json();
          setYoloStats(data);
        }
      } catch {
        // ignore
      }
    };

    fetchBackendStats();
    const interval = setInterval(fetchBackendStats, 1000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [selected, apiBase]);

  // Fetch cameras list whenever store changes
  useEffect(() => {
    setLoading(true);
    setSwitching(true);
    fetch(`${apiBase}/cameras?store_id=${storeId}`)
      .then((r) => r.json())
      .then((d) => {
        const cams: Camera[] = d.cameras ?? [];
        setCameras(cams);
        setLoading(false);
        // Auto-select first available camera for this store
        const firstAvailable = cams.find(c => c.available);
        if (firstAvailable) {
          setSelected(firstAvailable.cam_id);
          setStreamKey(Date.now());
        }
        setTimeout(() => setSwitching(false), 400);
      })
      .catch(() => {
        setError('Cannot reach camera API. Is the backend running?');
        setLoading(false);
        setSwitching(false);
      });
  }, [apiBase, storeId]);

  const handleCameraChange = (camId: string) => {
    setSwitching(true);
    setSelected(camId);
    setStreamKey(Date.now());
    setTimeout(() => setSwitching(false), 400);
  };



  const handleRestartSimulation = async () => {
    if (!selected) return;
    try {
      await fetch(`${apiBase}/simulation/start?speed=${speed}&cam_id=${selected}`, { method: 'POST' });
    } catch (err) {
      console.warn('Failed to restart simulation:', err);
    }
  };

  const currentCamConfig = selected ? CAM_ZONES_CONFIG[selected] : null;

  if (loading) {
    return (
      <div className="cam-loading">
        <div className="cam-spinner" />
        <span>Connecting to camera feeds...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="cam-error">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
          <path d="M23 7l-7 5 7 5V7z" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
          <line x1="1" y1="1" x2="23" y2="23" />
        </svg>
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className="cam-feed-layout">
      {/* Premium Toggle Bar */}
      <div className="cam-control-header">
        <div className="cam-title-badge">
          <span className="ai-badge-dot animate-pulse" />
          <span className="ai-badge-text">⚡ YOLOv8 LIVE CV STREAM</span>
        </div>

        <div className="cam-speed-selector" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem', color: '#00ffc8', fontWeight: 700, letterSpacing: '0.05em', background: 'rgba(0,255,200,0.06)', padding: '4px 10px', borderRadius: '20px', border: '1px solid rgba(0,255,200,0.15)' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#00ffc8', display: 'inline-block', animation: 'pulse 1.2s infinite' }} />
            REAL-TIME MODE
          </div>
          
          <button
            onClick={handleRestartSimulation}
            className="speed-btn restart-btn"
            title="Reset database and sync playback from the beginning"
            style={{
              border: '1px dashed rgba(255,255,255,0.2)',
              color: '#94a3b8',
              background: 'transparent',
              padding: '4px 12px',
              borderRadius: '4px',
              fontSize: '0.7rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              fontWeight: 600,
            }}
          >
            🔄 Sync & Restart
          </button>
        </div>
      </div>

      {/* Main player + Telemetry panel layout */}
      <div className="cam-display-container">
        <div className="cam-main-player">
          {switching && (
            <div className="cam-switching-overlay">
              <div className="cam-spinner" />
              <span>Switching YOLO inference stream...</span>
            </div>
          )}

          {!streamError ? (
            <div className="cam-video-wrap">
              <div className="cam-overlay-badge live">
                <span className="cam-live-dot green-pulse" />
                YOLO LIVE (ACTIVE)
              </div>
              <div className="cam-overlay-label">
                <span className="cam-overlay-icon">⚡</span>
                {selected && CAM_LABELS[selected]}
                <span className="cam-overlay-zone">AI-Powered</span>
              </div>
              {selected && (
                <img
                  key={`${selected}-${streamKey}`}
                  src={`${apiBase}/cameras/stream/${selected}?t=${streamKey}`}
                  alt="YOLO Object Detection Stream"
                  className="cam-video-el img-stream"
                  onError={() => setStreamError(true)}
                />
              )}
            </div>
          ) : (
            <div className="cam-no-signal yolo-offline">
              <div className="yolo-offline-card">
                <h3>📵 Camera Feed Unavailable</h3>
                <p>Could not connect to the backend stream for camera <strong>{selected}</strong>. Make sure the backend API is running:</p>
                <code>docker compose up -d</code>
                <button className="retry-btn" onClick={() => { setStreamError(false); setStreamKey(Date.now()); }}>
                  Retry Connection
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Telemetry Sidebar */}
        {yoloStats && yoloStats.frame > 0 && (
          <div className="cam-telemetry-sidebar">
            <div className="sidebar-section">
              <div className="section-title">Model Specifications</div>
              <div className="spec-grid">
                <div className="spec-label">Detector:</div>
                <div className="spec-val cyan">YOLOv8n (Nano)</div>
                <div className="spec-label">Tracker:</div>
                <div className="spec-val cyan">ByteTrack</div>
                <div className="spec-label">Classes:</div>
                <div className="spec-val">Person [class_id: 0]</div>
                <div className="spec-label">Hardware:</div>
                <div className="spec-val green">CPU/GPU Inference</div>
              </div>
            </div>

            <div className="sidebar-section">
              <div className="section-title">Real-Time Telemetry</div>
              <div className="telemetry-grid">
                <div className="telemetry-card">
                  <div className="card-lbl">Person Count</div>
                  <div className="card-val pulse-val">{yoloStats?.people ?? 0}</div>
                  <div className="card-sub">Current detections</div>
                </div>
                <div className="telemetry-card">
                  <div className="card-lbl">Inference Speed</div>
                  <div className={`card-val ${yoloStats && yoloStats.fps > 20 ? 'fps-fast' : 'fps-slow'}`}>
                    {yoloStats?.fps ?? 0} <span className="fps-unit">FPS</span>
                  </div>
                  <div className="card-sub">Strided processing (2/1)</div>
                </div>
              </div>
              <div className="frame-counter">
                <span>Processed Frames:</span>
                <span className="frame-no">{yoloStats?.frame ?? 0}</span>
              </div>
            </div>

            <div className="sidebar-section">
              <div className="section-title">Active Overlays ({currentCamConfig?.zones.length ?? 0})</div>
              <div className="overlay-list">
                {currentCamConfig?.zones.map((zone) => (
                  <div key={zone.name} className="overlay-item">
                    <span className="zone-color-dot" style={{ backgroundColor: zone.color }} />
                    <span className="zone-name">{zone.name}</span>
                    <span className="zone-badge">Active Polygon</span>
                  </div>
                ))}
                {selected && (selected === 'CAM_1' || selected === 'CAM_4') && (
                  <div className="overlay-item">
                    <span className="zone-color-dot" style={{ backgroundColor: '#00ffc8' }} />
                    <span className="zone-name">Entry Crossing Line</span>
                    <span className="zone-badge">Line Crossing</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Camera thumbnail grid (all cameras belong to active store from API) */}
      <div className="cam-thumb-grid">
        {cameras
          .map((cam) => (
            <button
              key={cam.cam_id}
              className={`cam-thumb ${selected === cam.cam_id ? 'active' : ''} ${!cam.available ? 'offline' : ''}`}
              onClick={() => cam.available && handleCameraChange(cam.cam_id)}
              title={cam.available ? `Switch to ${CAM_LABELS[cam.cam_id] ?? cam.name}` : 'Feed unavailable'}
            >
              <div className="cam-thumb-inner">
                <div className={`cam-thumb-placeholder ${cam.available ? 'active-indicator' : 'offline'}`}>
                  {cam.available ? (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" width="20" height="20">
                      <path d="M23 7l-7 5 7 5V7z" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                    </svg>
                  ) : (
                    <span style={{ fontSize: '1.2rem' }}>📵</span>
                  )}
                </div>
              </div>
              <div className="cam-thumb-label">
                <span className={`cam-thumb-status-dot ${cam.available ? 'online' : 'offline'}`} />
                {CAM_LABELS[cam.cam_id] ?? cam.name}
              </div>
            </button>
          ))}
      </div>
    </div>
  );
};

export default CameraFeed;
