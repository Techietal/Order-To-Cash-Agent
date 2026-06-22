import React from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer
} from 'recharts'
import { ShoppingCart, FileText, AlertTriangle, UserCheck, TrendingUp, Activity, Bot } from 'lucide-react'
import { analyticsApi, fraudApi, hitlApi, arApi, ordersApi, complianceApi } from '../lib/api'
import { usePipelineStore } from '../store'

const COLORS = ['#3b82f6','#22c55e','#f59e0b','#ef4444','#8b5cf6','#06b6d4']

function KpiCard({ label, value, delta, icon: Icon, color, prefix = '' }) {
  return (
    <div className={`kpi-card`}>
      <div className="kpi-accent" style={{ background: color }} />
      <div className="kpi-icon" style={{ background: `${color}20` }}>
        <Icon size={17} style={{ color }} />
      </div>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{prefix}{typeof value === 'number' ? value.toLocaleString('en-IN') : (value ?? '—')}</div>
      {delta && <div className={`kpi-delta ${delta.startsWith('+') ? 'up' : 'down'}`}>{delta} vs last week</div>}
    </div>
  )
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="tooltip-box">
      <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color, fontWeight: 600 }}>{p.name}: {typeof p.value === 'number' ? p.value.toLocaleString() : p.value}</div>
      ))}
    </div>
  )
}

export default function DashboardPage() {
  const { events, connected } = usePipelineStore()

  const { data: kpiData } = useQuery({
    queryKey: ['analytics-kpis'],
    queryFn: () => analyticsApi.kpis().then(r => r.data),
    refetchInterval: 30000,
  })

  const { data: fraudData } = useQuery({
    queryKey: ['fraud-stats'],
    queryFn: () => fraudApi.stats().then(r => r.data),
    refetchInterval: 60000,
  })

  const { data: hitlData } = useQuery({
    queryKey: ['hitl-stats'],
    queryFn: () => hitlApi.stats().then(r => r.data),
    refetchInterval: 15000,
  })

  // Real data for charts
  const { data: dsoRaw } = useQuery({
    queryKey: ['dso-trend'],
    queryFn: () => analyticsApi.dsoTrend().then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: agingRaw } = useQuery({
    queryKey: ['ar-aging'],
    queryFn: () => arApi.aging().then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: orderSummary } = useQuery({
    queryKey: ['orders-summary'],
    queryFn: () => ordersApi.summary().then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: auditRaw } = useQuery({
    queryKey: ['audit-log-recent'],
    queryFn: () => complianceApi.auditLog({ limit: 20 }).then(r => r.data),
    refetchInterval: 15000,
  })

  const kpis = kpiData || {}
  const totalAR = kpis.total_ar_outstanding_inr || 0
  const dsoData = dsoRaw?.trend || []
  const agingData = (agingRaw?.aging || []).map(a => ({ bucket: a.aging_bucket, amount: +(a.total_outstanding || 0) }))
  // Build channel breakdown from order summary
  const channelData = orderSummary?.by_channel
    ? Object.entries(orderSummary.by_channel).map(([name, value]) => ({ name, value }))
    : []
  const auditLog = auditRaw?.audit_log || []

  return (
    <div className="page-content animate-fade">
      {/* Header */}
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">O2C Command Center</h1>
          <p className="page-subtitle">Real-time Order-to-Cash pipeline — 11 specialist agents</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div className="live-label">
            <div className="live-dot" style={{ background: connected ? 'var(--accent-green)' : 'var(--accent-red)' }} />
            {connected ? 'Pipeline Live' : 'Connecting…'}
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="kpi-grid">
        <KpiCard label="Total Orders" value={kpis.total_orders || 0} icon={ShoppingCart} color="var(--accent-blue)" />
        <KpiCard label="Open Invoices" value={kpis.total_invoices || 0} icon={FileText} color="var(--accent-cyan)" />
        <KpiCard label="AR Outstanding" value={totalAR} prefix="₹" icon={TrendingUp} color="var(--accent-violet)" />
        <KpiCard label="Fraud Flagged" value={fraudData?.fraud_flagged || 0} icon={AlertTriangle} color="var(--accent-red)" />
        <KpiCard label="HITL Pending" value={hitlData?.pending || 0} icon={UserCheck} color="var(--accent-amber)" />
        <KpiCard label="Auto-Process Rate" value={`${((kpis.auto_process_rate || 0) * 100).toFixed(0)}%`} icon={Bot} color="var(--accent-green)" />
      </div>

      {/* Charts Row 1 */}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        {/* DSO Trend */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">DSO Trend</div>
              <div className="card-subtitle">Days Sales Outstanding — last 6 months</div>
            </div>
            <span className="badge badge-green">↓ Improving</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={dsoData}>
              <defs>
                <linearGradient id="dsoGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="month" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} domain={[20, 40]} />
              <Tooltip content={<CustomTooltip />} />
              <Area type="monotone" dataKey="dso" name="DSO (days)" stroke="#3b82f6" fill="url(#dsoGrad)" strokeWidth={2} dot={{ fill: '#3b82f6', r: 3 }} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* AR Aging */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">AR Aging Breakdown</div>
              <div className="card-subtitle">Outstanding balance by bucket</div>
            </div>
            <span className="badge badge-amber">₹{(agingData.reduce((s, d) => s + d.amount, 0) / 100000).toFixed(1)}L</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={agingData} barSize={32}>
              <XAxis dataKey="bucket" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `₹${(v/100000).toFixed(0)}L`} />
              <Tooltip content={<CustomTooltip />} formatter={(v) => `₹${v.toLocaleString()}`} />
              <Bar dataKey="amount" name="Amount" radius={[4,4,0,0]}>
                {agingData.map((_, i) => (
                  <Cell key={i} fill={['#22c55e','#f59e0b','#ef4444','#7f1d1d'][i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        {/* Order channels */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Order Channels</div>
            <span className="badge badge-blue">Agent 1</span>
          </div>
          <div style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
            <ResponsiveContainer width={150} height={150}>
              <PieChart>
                <Pie data={channelData} dataKey="value" cx="50%" cy="50%" innerRadius={45} outerRadius={65} paddingAngle={3}>
                  {channelData.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
              </PieChart>
            </ResponsiveContainer>
            <div style={{ flex: 1 }}>
              {channelData.map((d, i) => (
                <div key={d.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: COLORS[i] }} />
                    <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{d.name}</span>
                  </div>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{d.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Agent Activity Feed — from real audit_log */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Agent Activity Feed</div>
            <div className="live-label">
              <div className="live-dot" />
              Live audit log
            </div>
          </div>
          <div style={{ maxHeight: 170, overflowY: 'auto' }}>
            {auditLog.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 12, textAlign: 'center', padding: '20px 0' }}>
                No events yet — submit an order to start the pipeline
              </div>
            ) : (
              auditLog.map((e, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, padding: '7px 0', borderBottom: '1px solid var(--border)' }}>
                  <Activity size={12} style={{ color: 'var(--accent-blue)', marginTop: 3, flexShrink: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 12, color: 'var(--text-primary)', fontWeight: 600 }}>{e.action || e.event_type}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{e.created_at ? new Date(e.created_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}</span>
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--accent-cyan)' }}>{e.agent_name} {e.customer_id ? `· ${e.customer_id}` : ''}</div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Pipeline Status */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">11-Agent Pipeline Status</div>
          <span className="badge badge-blue">MAF 1.0 Hybrid Orchestration</span>
        </div>
        <div className="pipeline-steps">
          {[
            { num: 1, label: 'Order\nIngestion',  status: 'done',    icon: '📥' },
            { num: 2, label: 'Credit\nCheck',      status: 'done',    icon: '💳' },
            { num: 3, label: 'Fraud\nDetection',   status: 'done',    icon: '🛡️' },
            { num: 4, label: 'Inventory\nCheck',   status: 'active',  icon: '📦' },
            { num: 5, label: 'Fulfillment\nMgr',   status: 'pending', icon: '🚚' },
            { num: 6, label: 'Invoice\nGen',        status: 'pending', icon: '📄' },
            { num: 7, label: 'Payment\nMonitor',    status: 'pending', icon: '💰' },
            { num: 8, label: 'Collections\nAgent', status: 'hitl',   icon: '📞' },
            { num: 9, label: 'Cash\nApplication',  status: 'pending', icon: '🏦' },
            { num: 10, label: 'Dispute\nResolver', status: 'pending', icon: '⚖️' },
            { num: 11, label: 'Anomaly\nWatchdog', status: 'active',  icon: '👁️' },
          ].map((step, i, arr) => (
            <React.Fragment key={step.num}>
              <div className="pipe-step">
                <div className={`pipe-icon ${step.status}`} title={`Agent ${step.num}`}>
                  {step.icon}
                </div>
                <div className="pipe-label">{step.label}</div>
              </div>
              {i < arr.length - 1 && (
                <div className={`pipe-connector ${step.status === 'done' ? 'done' : step.status === 'active' ? 'active' : ''}`} />
              )}
            </React.Fragment>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
          {[['done','var(--accent-green)','Complete'],['active','var(--accent-blue)','Active'],['hitl','var(--accent-amber)','HITL Required'],['pending','var(--border-light)','Pending']].map(([s, c, l]) => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-muted)' }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: c }} />
              {l}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
