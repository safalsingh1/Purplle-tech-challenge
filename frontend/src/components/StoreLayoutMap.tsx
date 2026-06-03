import React, { useState, useEffect, useRef, useCallback } from 'react';

interface StoreLayoutMapProps {
  apiBase: string;
  storeId: string;
  metrics: {
    store_id: string;
    unique_visitors: number;
    conversion_rate: number;
    avg_dwell_per_zone: { zone_id: string; avg_dwell_seconds: number; visit_count: number }[];
    queue_depth: number;
    abandonment_rate: number;
    computed_at: string;
  } | null;
  speed: number;
  onRestartSimulation: () => Promise<void>;
  hideCCTV?: boolean;
  selectedCam?: string;
}

interface ZoneDef {
  id: string;
  label: string;
  sublabel?: string;
  icon: string;
  x: number; y: number; w: number; h: number; // 0-1 fractions of canvas
  color: string;
  glowColor: string;
  type: 'entry' | 'floor' | 'billing' | 'queue' | 'impulse';
}

interface Person {
  id: number;
  x: number; y: number;
  tx: number; ty: number;
  zoneId: string;
  speed: number;
  color: string;
  size: number;
  opacity: number;
  dwellTimer: number;
  dwellMax: number;
}

// ─── Store Zone Definitions ───────────────────────────────────────────────────
// Coordinates calibrated to match the actual store layout PNG images.
// Store 1 (STORE_BLR_002): Horizontal layout. Entry on left, Cash Counter on right.
// Store 2 (ST1008): Vertical L-shape. Entry at bottom-center, Cash Counter at center-top.

const STORE_ZONES: Record<string, ZoneDef[]> = {
  STORE_BLR_002: [
    // Entry — far left, the curved glass entry
    {
      id: 'ENTRY',
      label: 'Entrance',
      sublabel: 'Entry / Exit',
      icon: '🚪',
      x: 0.01, y: 0.28, w: 0.09, h: 0.60,
      color: '#00dc64',
      glowColor: 'rgba(0,220,100,0.12)',
      type: 'entry',
    },
    // Top wall shelf brands (Salm, TFS, unnamed, Minimalis, Aqualogi, Foxtal, JC)
    {
      id: 'WALL_TOP',
      label: 'Top Wall Brands',
      sublabel: 'Salm · TFS · Minimalis · Aqualogi',
      icon: '💆',
      x: 0.10, y: 0.03, w: 0.76, h: 0.16,
      color: '#ff6b3d',
      glowColor: 'rgba(255,107,61,0.10)',
      type: 'floor',
    },
    // Center FOH — Fragrance gondola + Nail Unit (left of FOH)
    {
      id: 'GONDOLA_FOH',
      label: 'Fragrance & Nail',
      sublabel: 'F.O.H Gondola',
      icon: '🧴',
      x: 0.20, y: 0.26, w: 0.18, h: 0.46,
      color: '#ffd93d',
      glowColor: 'rgba(255,217,61,0.10)',
      type: 'floor',
    },
    // Center FOH — Main Makeup Unit (center island)
    {
      id: 'MAKEUP_FOH',
      label: 'Makeup F.O.H',
      sublabel: 'Makeup Units · Demo Area',
      icon: '✨',
      x: 0.40, y: 0.22, w: 0.24, h: 0.54,
      color: '#c855ff',
      glowColor: 'rgba(200,85,255,0.10)',
      type: 'floor',
    },
    // Billing queue area (just left of cash counter)
    {
      id: 'BILLING_QUEUE',
      label: 'Queue',
      sublabel: 'Checkout queue',
      icon: '⏳',
      x: 0.68, y: 0.26, w: 0.10, h: 0.50,
      color: '#0055cc',
      glowColor: 'rgba(0,85,200,0.14)',
      type: 'queue',
    },
    // Cash counter — far right
    {
      id: 'BILLING_COUNTER',
      label: 'Cash Counter',
      sublabel: 'POS · 55" Panel',
      icon: '🏷️',
      x: 0.79, y: 0.20, w: 0.16, h: 0.58,
      color: '#008cff',
      glowColor: 'rgba(0,140,255,0.14)',
      type: 'billing',
    },
    // Bottom wall shelf brands (Fac, Mars+Nybae, Mens, Lo'real, Beaut)
    {
      id: 'WALL_BOTTOM',
      label: 'Bottom Wall Brands',
      sublabel: 'Fac · Mens · Lo\'real · Beaut',
      icon: '🌸',
      x: 0.13, y: 0.80, w: 0.65, h: 0.17,
      color: '#3cc8ff',
      glowColor: 'rgba(60,200,255,0.10)',
      type: 'floor',
    },
  ],

  ST1008: [
    // Entry — bottom center (as labeled in the layout)
    {
      id: 'ENTRY',
      label: 'Entrance',
      sublabel: 'Main Entry',
      icon: '🚪',
      x: 0.36, y: 0.87, w: 0.26, h: 0.10,
      color: '#00dc64',
      glowColor: 'rgba(0,220,100,0.12)',
      type: 'entry',
    },
    // Left wall units (Wall Unit 1-5)
    {
      id: 'WALL_LEFT',
      label: 'Left Wall Units',
      sublabel: 'Wall Unit 1–5',
      icon: '🧴',
      x: 0.03, y: 0.38, w: 0.10, h: 0.48,
      color: '#ff6b3d',
      glowColor: 'rgba(255,107,61,0.10)',
      type: 'floor',
    },
    // MK Gondolas — diagonal center-left area
    {
      id: 'FOH_GONDOLA',
      label: 'MK Gondolas',
      sublabel: 'Gondola 1 & 2',
      icon: '🛒',
      x: 0.15, y: 0.45, w: 0.23, h: 0.38,
      color: '#ffb83d',
      glowColor: 'rgba(255,184,61,0.10)',
      type: 'floor',
    },
    // F.O.H main floor area (center)
    {
      id: 'FOH_MAIN',
      label: 'F.O.H Floor',
      sublabel: 'Main shopping area',
      icon: '✨',
      x: 0.38, y: 0.52, w: 0.24, h: 0.34,
      color: '#c855ff',
      glowColor: 'rgba(200,85,255,0.10)',
      type: 'floor',
    },
    // Makeup Units — center right
    {
      id: 'FOH_MAKEUP',
      label: 'Makeup Units',
      sublabel: 'Demo Chairs · MU Area',
      icon: '💄',
      x: 0.64, y: 0.48, w: 0.18, h: 0.36,
      color: '#ff6bc8',
      glowColor: 'rgba(255,107,200,0.10)',
      type: 'floor',
    },
    // Right wall units (Wall Unit 13-19)
    {
      id: 'WALL_RIGHT',
      label: 'Right Wall Units',
      sublabel: 'Wall Unit 13–19',
      icon: '🌸',
      x: 0.84, y: 0.38, w: 0.10, h: 0.48,
      color: '#3cc8ff',
      glowColor: 'rgba(60,200,255,0.10)',
      type: 'floor',
    },
    // Top wall units (Wall Unit 7-12) — upper store area
    {
      id: 'WALL_TOP',
      label: 'Top Wall Units',
      sublabel: 'Wall Unit 7–12',
      icon: '💆',
      x: 0.10, y: 0.30, w: 0.74, h: 0.10,
      color: '#a78bfa',
      glowColor: 'rgba(167,139,250,0.10)',
      type: 'floor',
    },
    // Cash counter — center-top area
    {
      id: 'BILLING_COUNTER',
      label: 'Cash Counter',
      sublabel: '85" LED Screen · POS',
      icon: '🏷️',
      x: 0.38, y: 0.36, w: 0.20, h: 0.12,
      color: '#008cff',
      glowColor: 'rgba(0,140,255,0.14)',
      type: 'billing',
    },
    // Queue zone — just below cash counter
    {
      id: 'BILLING_QUEUE',
      label: 'Queue',
      sublabel: 'Checkout line',
      icon: '⏳',
      x: 0.39, y: 0.49, w: 0.18, h: 0.08,
      color: '#0055cc',
      glowColor: 'rgba(0,85,200,0.14)',
      type: 'queue',
    },
  ],
};

const PERSON_COLORS = [
  '#00ffc8', '#ff6b6b', '#ffd93d', '#6bcb77', '#4d96ff',
  '#ff6bc8', '#c8ff6b', '#ffa96b', '#6bffff', '#ff9fdf',
  '#b4f0ff', '#ffca80', '#c0ff80', '#ff80c0', '#80c0ff',
];

function randomInZone(zone: ZoneDef, cw: number, ch: number) {
  const pad = 0.06;
  const xMin = zone.x + pad;
  const xMax = zone.x + zone.w - pad;
  const yMin = zone.y + pad;
  const yMax = zone.y + zone.h - pad;
  return {
    x: (xMin + Math.random() * Math.max(0, xMax - xMin)) * cw,
    y: (yMin + Math.random() * Math.max(0, yMax - yMin)) * ch,
  };
}

function pickZone(zones: ZoneDef[]): ZoneDef {
  // Weight towards floor zones, less towards billing
  const floorZones = zones.filter(z => z.type !== 'billing' && z.type !== 'queue');
  const pool = floorZones.length > 0 ? floorZones : zones;
  return pool[Math.floor(Math.random() * pool.length)];
}

function getQueuePos(index: number, cw: number, ch: number, activeZones: ZoneDef[]) {
  const qZone = activeZones.find(z => z.id === 'BILLING_QUEUE') || activeZones[activeZones.length - 1];
  const qx = (qZone.x + qZone.w / 2) * cw;
  const qyStart = (qZone.y + qZone.h * 0.15) * ch;
  const spacing = (qZone.h / 6) * ch;
  return {
    x: qx + (Math.sin(index * 2.1 + Date.now() / 2000) * 4),
    y: qyStart + index * spacing,
  };
}

export const StoreLayoutMap: React.FC<StoreLayoutMapProps> = ({
  storeId,
  metrics,
  speed,
  onRestartSimulation,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const personsRef = useRef<Person[]>([]);

  const [zoneCounts, setZoneCounts] = useState<Record<string, number>>({});
  const [hovered, setHovered] = useState<string | null>(null);
  const canvasSize = useRef({ w: 800, h: 520 });

  const activeZones = STORE_ZONES[storeId] || STORE_ZONES['STORE_BLR_002'];
  const layoutImage = storeId === 'ST1008' ? '/store-2-layout.png' : '/store-1-layout.png';

  // ── Sync persons to live visitor count ─────────────────────────────────────
  useEffect(() => {
    const active = (metrics as any)?.active_visitors ?? 0;
    const count = Math.max(0, Math.min(28, active));

    const cw = canvasSize.current.w;
    const ch = canvasSize.current.h;
    const existing = personsRef.current;
    const zones = STORE_ZONES[metrics?.store_id ?? 'STORE_BLR_002'] || STORE_ZONES['STORE_BLR_002'];

    while (existing.length < count) {
      const zone = pickZone(zones);
      const pos = randomInZone(zone, cw, ch);
      const tgt = randomInZone(pickZone(zones), cw, ch);
      existing.push({
        id: existing.length,
        x: pos.x, y: pos.y,
        tx: tgt.x, ty: tgt.y,
        zoneId: zone.id,
        speed: 0.010 + Math.random() * 0.014,
        color: PERSON_COLORS[existing.length % PERSON_COLORS.length],
        size: 4.5 + Math.random() * 2,
        opacity: 0.80 + Math.random() * 0.20,
        dwellTimer: 0,
        dwellMax: 900 + Math.random() * 2000,
      });
    }
    if (existing.length > count) existing.splice(count);

    // Lock queue persons
    const qd = metrics?.queue_depth ?? 0;
    existing.forEach((p, idx) => {
      if (idx < qd) {
        p.zoneId = 'BILLING_QUEUE';
        const qPos = getQueuePos(idx, cw, ch, zones);
        p.tx = qPos.x;
        p.ty = qPos.y;
        if (Math.abs(p.x - p.tx) > 100 || Math.abs(p.y - p.ty) > 100) {
          p.x = p.tx;
          p.y = p.ty;
        }
      } else {
        if (p.zoneId === 'BILLING_QUEUE') {
          const newZone = pickZone(zones);
          const pos = randomInZone(newZone, cw, ch);
          p.tx = pos.x;
          p.ty = pos.y;
          p.zoneId = newZone.id;
          p.dwellTimer = 0;
        }
      }
    });
  }, [metrics]);

  // ── Zone count updater ─────────────────────────────────────────────────────
  const updateZoneCounts = useCallback((zones: ZoneDef[]) => {
    const cw = canvasSize.current.w;
    const ch = canvasSize.current.h;
    const counts: Record<string, number> = {};
    for (const p of personsRef.current) {
      const nx = p.x / cw, ny = p.y / ch;
      for (const z of zones) {
        if (nx >= z.x && nx <= z.x + z.w && ny >= z.y && ny <= z.y + z.h) {
          counts[z.id] = (counts[z.id] ?? 0) + 1;
          break;
        }
      }
    }
    setZoneCounts(counts);
  }, []);

  // Stable refs
  const hoveredRef = useRef<string | null>(null);
  hoveredRef.current = hovered;
  const zoneCountsRef = useRef<Record<string, number>>({});
  zoneCountsRef.current = zoneCounts;
  const metricsRef = useRef<any>(null);
  metricsRef.current = metrics;
  const speedRef = useRef<number>(1.0);
  speedRef.current = speed;
  const storeIdRef = useRef<string>(storeId);
  storeIdRef.current = storeId;
  const animFrameIdRef = useRef<number>(0);
  const frameCountRef = useRef<number>(0);

  // ── Canvas animation loop ──────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;

    const draw = () => {
      const cw = canvas.width;
      const ch = canvas.height;
      canvasSize.current = { w: cw, h: ch };

      // Transparent canvas — layout PNG shows through
      ctx.clearRect(0, 0, cw, ch);

      const zones = STORE_ZONES[storeIdRef.current] || STORE_ZONES['STORE_BLR_002'];

      // ── Draw zone overlays ─────────────────────────────────────────────────
      for (const zone of zones) {
        const x = zone.x * cw, y = zone.y * ch;
        const w = zone.w * cw, h = zone.h * ch;
        const isHovered = hoveredRef.current === zone.id;
        const count = zoneCountsRef.current[zone.id] ?? 0;
        const heat = Math.min(count / 6, 1);

        ctx.save();

        // Translucent base fill
        ctx.fillStyle = zone.glowColor;
        ctx.fillRect(x, y, w, h);

        // Heat layer — more people = warmer tint
        if (heat > 0) {
          ctx.fillStyle = `rgba(255,60,60,${heat * 0.15})`;
          ctx.fillRect(x, y, w, h);
        }

        // Hover highlight
        if (isHovered) {
          ctx.fillStyle = 'rgba(255,255,255,0.06)';
          ctx.fillRect(x, y, w, h);
        }

        // Zone border
        ctx.strokeStyle = isHovered ? '#ffffff' : zone.color;
        ctx.lineWidth = isHovered ? 2 : 1;
        ctx.globalAlpha = isHovered ? 0.85 : 0.45;
        ctx.strokeRect(x + 1, y + 1, w - 2, h - 2);
        ctx.globalAlpha = 1;

        // Inner dashed line
        ctx.setLineDash([4, 5]);
        ctx.strokeStyle = zone.color;
        ctx.globalAlpha = 0.10;
        ctx.lineWidth = 1;
        ctx.strokeRect(x + 5, y + 5, w - 10, h - 10);
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;

        // Corner dots
        const corners = [[x+3,y+3],[x+w-3,y+3],[x+3,y+h-3],[x+w-3,y+h-3]];
        for (const [cx2, cy2] of corners) {
          ctx.beginPath();
          ctx.arc(cx2, cy2, 2, 0, Math.PI * 2);
          ctx.fillStyle = zone.color;
          ctx.globalAlpha = 0.45;
          ctx.fill();
          ctx.globalAlpha = 1;
        }

        // Zone label — only if zone is large enough
        if (w > 55 && h > 35) {
          const midX = x + w / 2;
          const midY = y + h / 2;
          const iconSize = Math.min(w, h) > 70 ? 16 : 11;

          ctx.font = `${iconSize}px sans-serif`;
          ctx.textAlign = 'center';
          ctx.globalAlpha = 0.9;
          ctx.fillText(zone.icon, midX, midY - (h > 55 ? 14 : 6));

          ctx.font = `600 ${Math.min(10, w / 7)}px "Inter", sans-serif`;
          ctx.fillStyle = zone.color;
          ctx.globalAlpha = 0.92;
          ctx.fillText(zone.label, midX, midY + (h > 55 ? 2 : 4));
          ctx.globalAlpha = 1;

          // Person count badge
          if (count > 0) {
            const bw = count > 9 ? 26 : 20;
            const bh = 15;
            const bx = x + w - bw - 3;
            const by = y + 3;
            ctx.fillStyle = zone.color;
            ctx.globalAlpha = 0.88;
            ctx.beginPath();
            ctx.roundRect(bx, by, bw, bh, 7);
            ctx.fill();
            ctx.globalAlpha = 1;
            ctx.font = `700 8.5px "Inter", sans-serif`;
            ctx.fillStyle = '#000';
            ctx.fillText(`${count}`, bx + bw / 2, by + 10.5);
          }
        }
        ctx.restore();
      }

      // ── Move & draw persons ────────────────────────────────────────────────
      frameCountRef.current = (frameCountRef.current + 1) % 10000;
      const frameCount = frameCountRef.current;

      const activeNow = (metricsRef.current as any)?.active_visitors ?? 0;
      const isLive = activeNow > 0;

      const qd = metricsRef.current?.queue_depth ?? 0;
      personsRef.current.forEach((p, idx) => {
        if (idx < qd) {
          const qPos = getQueuePos(idx, cw, ch, zones);
          p.tx = qPos.x;
          p.ty = qPos.y;
          p.zoneId = 'BILLING_QUEUE';
        }
      });

      for (const p of personsRef.current) {
        // Freeze movement when simulation is not live
        if (!isLive) {
          // just draw, don't move
        } else {
          const dx = p.tx - p.x;
          const dy = p.ty - p.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < 3) {
            p.dwellTimer += speedRef.current;
            if (p.dwellTimer >= p.dwellMax) {
              const isQueued = personsRef.current.indexOf(p) < qd;
              if (!isQueued) {
                const newZone = pickZone(zones);
                const tgt = randomInZone(newZone, cw, ch);
                p.tx = tgt.x;
                p.ty = tgt.y;
                p.zoneId = newZone.id;
                p.dwellTimer = 0;
                p.dwellMax = 900 + Math.random() * 2000;
              }
            }
          } else {
            const spd = p.speed * 1.0;
            p.x += (dx / dist) * spd;
            p.y += (dy / dist) * spd;
          }
        }

        // Draw person
        ctx.save();

        // Drop shadow
        ctx.shadowColor = 'rgba(0,0,0,0.7)';
        ctx.shadowBlur = 8;
        ctx.shadowOffsetY = 2;

        // White border ring
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 1.35, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();

        // Inner colored circle
        ctx.shadowColor = 'transparent';
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();

        // Inner highlight
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size * 0.38, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.globalAlpha = 0.75;
        ctx.fill();

        ctx.restore();

        // Pulsing ring
        const phase = (Date.now() / 18 + p.id * 37) % 100;
        const pulseR = p.size * 1.35 + (phase / 100) * 11;
        const pulseA = Math.max(0, 0.7 - (phase / 100) * 0.7);
        ctx.beginPath();
        ctx.arc(p.x, p.y, pulseR, 0, Math.PI * 2);
        ctx.strokeStyle = p.color;
        ctx.globalAlpha = pulseA * 0.65;
        ctx.lineWidth = 1.2;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      if (frameCount % 12 === 0) updateZoneCounts(zones);

      animFrameIdRef.current = requestAnimationFrame(draw);
    };

    animFrameIdRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animFrameIdRef.current);
  }, [updateZoneCounts]);

  // ── Canvas hover ──────────────────────────────────────────────────────────
  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const nx = (e.clientX - rect.left) / rect.width;
    const ny = (e.clientY - rect.top) / rect.height;
    const zones = STORE_ZONES[storeId] || STORE_ZONES['STORE_BLR_002'];
    let found: string | null = null;
    for (const zone of zones) {
      if (nx >= zone.x && nx <= zone.x + zone.w && ny >= zone.y && ny <= zone.y + zone.h) {
        found = zone.id;
        break;
      }
    }
    setHovered(found);
  }, [storeId]);

  // Use active_visitors from API — this is the true "currently in store" count
  // and goes to 0 when the simulation ends (ingested_at 2-min window expires)
  const activeVisitors = (metrics as any)?.active_visitors ?? 0;
  const queueDepth = metrics?.queue_depth ?? 0;
  const convRate = metrics ? (metrics.conversion_rate * 100).toFixed(1) : '—';

  // Dwell data from metrics for legend enrichment
  const dwellMap: Record<string, number> = {};
  metrics?.avg_dwell_per_zone?.forEach(d => { dwellMap[d.zone_id] = d.avg_dwell_seconds; });

  return (
    <div className="store-layout-container">
      {/* Header */}
      <div className="cam-control-header">
        <div className="cam-title-badge">
          <span className="ai-badge-dot animate-pulse" />
          <span className="ai-badge-text">
            🏪 LIVE SPATIAL TRACKING — {storeId === 'ST1008' ? 'Brigade Road' : 'Bengaluru Central'}
          </span>
        </div>

        <div className="cam-speed-selector" style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem', color: activeVisitors > 0 ? '#00ffc8' : '#475569', fontWeight: 700, letterSpacing: '0.05em', background: activeVisitors > 0 ? 'rgba(0,255,200,0.06)' : 'rgba(71,85,105,0.1)', padding: '4px 10px', borderRadius: '20px', border: `1px solid ${activeVisitors > 0 ? 'rgba(0,255,200,0.15)' : 'rgba(71,85,105,0.2)'}` }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: activeVisitors > 0 ? '#00ffc8' : '#475569', display: 'inline-block', animation: activeVisitors > 0 ? 'pulse 1.2s infinite' : 'none' }} />
            {activeVisitors > 0 ? `${activeVisitors} IN STORE` : 'STREAM ENDED'}
          </div>

          <button
            onClick={onRestartSimulation}
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
            🔄 Sync &amp; Restart
          </button>
        </div>
      </div>

      {/* Main layout: floor plan + legend */}
      <div style={{ display: 'flex', gap: '16px', flexDirection: 'row', width: '100%', alignItems: 'flex-start' }}>

        {/* Floor plan canvas */}
        <div style={{
          position: 'relative',
          flex: 1,
          minWidth: 0,
          height: '520px',
          backgroundImage: `url(${layoutImage})`,
          backgroundSize: 'contain',
          backgroundPosition: 'center',
          backgroundRepeat: 'no-repeat',
          backgroundColor: '#0a0a12',
          borderRadius: '12px',
          border: '1px solid rgba(255,255,255,0.06)',
          overflow: 'hidden',
        }}>
          <canvas
            ref={canvasRef}
            width={800}
            height={520}
            style={{
              width: '100%',
              height: '100%',
              cursor: hovered ? 'crosshair' : 'default',
              display: 'block',
              background: 'transparent',
            }}
            onMouseMove={handleMouseMove}
            onMouseLeave={() => setHovered(null)}
          />

          {/* HUD overlay chips */}
          <div className="map-hud-overlay">
            <div className="hud-chip">
              <span className="hud-chip-dot" style={{ background: activeVisitors > 0 ? '#00ffc8' : '#475569' }} />
              <span className="hud-chip-val">{activeVisitors}</span>
              <span className="hud-chip-lbl">{activeVisitors > 0 ? 'In Store' : 'Idle'}</span>
            </div>
            <div className="hud-chip">
              <span className="hud-chip-dot" style={{ background: '#008cff' }} />
              <span className="hud-chip-val">{queueDepth}</span>
              <span className="hud-chip-lbl">Queue</span>
            </div>
            <div className="hud-chip">
              <span className="hud-chip-dot" style={{ background: '#c855ff' }} />
              <span className="hud-chip-val">{convRate}%</span>
              <span className="hud-chip-lbl">Conv.</span>
            </div>
          </div>

          {/* Zone hover tooltip */}
          {hovered && (() => {
            const z = activeZones.find(z => z.id === hovered);
            if (!z) return null;
            const count = zoneCounts[hovered] ?? 0;
            const dwell = dwellMap[hovered];
            return (
              <div style={{
                position: 'absolute',
                bottom: '12px',
                left: '50%',
                transform: 'translateX(-50%)',
                background: 'rgba(8,12,24,0.95)',
                border: `1px solid ${z.color}44`,
                borderRadius: '10px',
                padding: '8px 14px',
                pointerEvents: 'none',
                backdropFilter: 'blur(12px)',
                display: 'flex',
                gap: '16px',
                alignItems: 'center',
                boxShadow: `0 0 20px ${z.color}22`,
                zIndex: 10,
              }}>
                <span style={{ fontSize: '1.2rem' }}>{z.icon}</span>
                <div>
                  <div style={{ color: z.color, fontWeight: 700, fontSize: '0.75rem', letterSpacing: '0.04em' }}>{z.label}</div>
                  {z.sublabel && <div style={{ color: '#64748b', fontSize: '0.62rem', marginTop: '1px' }}>{z.sublabel}</div>}
                </div>
                <div style={{ display: 'flex', gap: '12px' }}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: '1.1rem', fontFamily: 'JetBrains Mono, monospace' }}>{count}</div>
                    <div style={{ color: '#64748b', fontSize: '0.58rem' }}>People</div>
                  </div>
                  {dwell !== undefined && (
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ color: '#ffd93d', fontWeight: 800, fontSize: '1.1rem', fontFamily: 'JetBrains Mono, monospace' }}>{Math.round(dwell)}s</div>
                      <div style={{ color: '#64748b', fontSize: '0.58rem' }}>Avg Dwell</div>
                    </div>
                  )}
                </div>
              </div>
            );
          })()}
        </div>

        {/* Legend sidebar */}
        <div style={{ width: '175px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '7px' }}>
          <div style={{ fontSize: '0.62rem', letterSpacing: '0.09em', color: '#475569', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase' }}>
            Zone Traffic
          </div>

          {activeZones.filter(z => z.id !== 'ENTRY').map(zone => {
            const count = zoneCounts[zone.id] ?? 0;
            const dotCount = personsRef.current.length;
            const pct = dotCount > 0 ? (count / dotCount) * 100 : 0;
            const dwell = dwellMap[zone.id];
            const isQ = hovered === zone.id;

            return (
              <div
                key={zone.id}
                onMouseEnter={() => setHovered(zone.id)}
                onMouseLeave={() => setHovered(null)}
                style={{
                  padding: '6px 9px',
                  background: isQ ? `${zone.color}12` : 'rgba(15, 20, 40, 0.5)',
                  border: `1px solid ${isQ ? zone.color + '44' : 'rgba(255,255,255,0.04)'}`,
                  borderRadius: '8px',
                  cursor: 'default',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '4px' }}>
                  <span style={{ fontSize: '8px' }}>{zone.icon}</span>
                  <span style={{ color: zone.color, fontSize: '0.67rem', fontWeight: 600, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{zone.label}</span>
                  <span style={{ fontSize: '0.68rem', fontWeight: 800, color: '#e2e8f0', fontFamily: 'JetBrains Mono, monospace' }}>{count}</span>
                </div>

                {/* Bar */}
                <div style={{ height: '3px', background: 'rgba(255,255,255,0.05)', borderRadius: '2px', overflow: 'hidden', marginBottom: dwell !== undefined ? '3px' : '0' }}>
                  <div style={{
                    width: `${Math.max(pct, count > 0 ? 6 : 0)}%`,
                    background: zone.color,
                    boxShadow: `0 0 5px ${zone.color}55`,
                    height: '100%',
                    borderRadius: '2px',
                    transition: 'width 0.5s ease-out',
                  }} />
                </div>

                {/* Avg dwell tag */}
                {dwell !== undefined && (
                  <div style={{ color: '#475569', fontSize: '0.58rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '2px' }}>
                    <span>avg dwell</span>
                    <span style={{ color: '#ffd93d', fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>{Math.round(dwell)}s</span>
                  </div>
                )}
              </div>
            );
          })}

          {/* Queue status card */}
          {queueDepth > 0 && (
            <div style={{
              marginTop: '4px',
              padding: '7px 10px',
              background: 'rgba(0,85,200,0.12)',
              border: '1px solid rgba(0,140,255,0.25)',
              borderRadius: '8px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginBottom: '3px' }}>
                <span style={{ fontSize: '9px' }}>⏳</span>
                <span style={{ color: '#008cff', fontSize: '0.68rem', fontWeight: 700 }}>Queue Active</span>
              </div>
              <div style={{ color: '#e2e8f0', fontSize: '1.0rem', fontWeight: 800, fontFamily: 'JetBrains Mono, monospace' }}>
                {queueDepth} <span style={{ color: '#475569', fontSize: '0.6rem', fontWeight: 400 }}>waiting</span>
              </div>
              {metrics && metrics.abandonment_rate > 0 && (
                <div style={{ color: '#f87171', fontSize: '0.6rem', marginTop: '2px' }}>
                  {(metrics.abandonment_rate * 100).toFixed(0)}% abandonment
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default StoreLayoutMap;
