import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend
} from 'recharts'
import { analyticsApi } from '../lib/api'
import { TrendingUp, TrendingDown, BarChart2 } from 'lucide-react'

const SKU_COLORS = ['#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6', '#06b6d4']

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="tooltip-box">
      <div style={{ color: 'var(--text-secondary)', marginBottom: 4, fontSize: 11 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color, fontWeight: 600, fontSize: 12 }}>
          {p.name}: {typeof p.value === 'number' ? p.value.toLocaleString() : p.value}
        </div>
      ))}
    </div>
  )
}

export default function AnalyticsPage() {
  const [activeSku, setActiveSku] = useState('SKU-001')

  const { data: dso } = useQuery({
    queryKey: ['dso'],
    queryFn: () => analyticsApi.dsoTrend().then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: rev } = useQuery({
    queryKey: ['revenue'],
    queryFn: () => analyticsApi.revenueForecast().then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: kpis } = useQuery({
    queryKey: ['analytics-kpis'],
    queryFn: () => analyticsApi.kpis().then(r => r.data),
    refetchInterval: 30000,
  })
  const { data: demand } = useQuery({
    queryKey: ['demand-forecast', activeSku],
    queryFn: () => analyticsApi.demandForecast({ sku_id: activeSku, days: 30 }).then(r => r.data),
    refetchInterval: 300000,
  })

  const dsoData = dso?.trend || []
  const forecastData = rev?.forecast || []
  const demandData = (demand?.forecast || []).map(d => ({
    date: d.date || d.ds,
    yhat: Math.round(d.yhat || 0),
    yhat_lower: Math.round(d.yhat_lower || 0),
    yhat_upper: Math.round(d.yhat_upper || 0),
  }))

  const k = kpis || {}
  const collectionRate = (k.collection_rate || 0) * 100
  const autoRate = (k.auto_process_rate || 0) * 100

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Analytics & Forecasting</h1>
          <p className="page-subtitle">Prophet demand forecast · DSO trend · Revenue forecast · Collection rate — all from live DB</p>
        </div>
        <span className="badge badge-violet"><span className="ml-dot live" />Prophet 1.3.0: Live</span>
      </div>

      {/* Live KPI Strip */}
      <div className="kpi-grid" style={{ marginBottom: 20 }}>
        <div className="kpi-card">
          <div className="kpi-label">Total Invoiced</div>
          <div className="kpi-value" style={{ color: 'var(--accent-blue)' }}>
            ₹{((k.total_invoiced_inr || 0) / 100000).toFixed(1)}L
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Total Collected</div>
          <div className="kpi-value" style={{ color: 'var(--accent-green)' }}>
            ₹{((k.total_collected_inr || 0) / 100000).toFixed(1)}L
          </div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Collection Rate</div>
          <div className="kpi-value" style={{ color: collectionRate >= 80 ? 'var(--accent-green)' : 'var(--accent-amber)' }}>
            {collectionRate.toFixed(1)}%
          </div>
          <div className="kpi-delta">Target ≥ 80%</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Auto-Process Rate</div>
          <div className="kpi-value" style={{ color: autoRate >= 80 ? 'var(--accent-green)' : 'var(--accent-amber)' }}>
            {autoRate.toFixed(0)}%
          </div>
          <div className="kpi-delta">Target ≥ 80%</div>
        </div>
      </div>

      {/* DSO + Revenue Charts */}
      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">DSO Trend</div>
              <div className="card-subtitle">Days Sales Outstanding — from real invoice payment data</div>
            </div>
            <span className="badge badge-green">
              {dsoData.length > 1 && dsoData[dsoData.length - 1]?.dso < dsoData[0]?.dso
                ? <><TrendingDown size={10} /> Improving</>
                : <><TrendingUp size={10} /> Watch</>}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={dsoData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="month" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis domain={[20, 60]} tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <ReferenceLine y={30} stroke="var(--accent-amber)" strokeDasharray="4 2" label={{ value: 'Target 30d', fill: 'var(--accent-amber)', fontSize: 9 }} />
              <Tooltip content={<CustomTooltip />} formatter={v => [`${v} days`, 'DSO']} />
              <Line type="monotone" dataKey="dso" name="DSO (days)" stroke="var(--accent-blue)" strokeWidth={2} dot={{ r: 3, fill: 'var(--accent-blue)' }} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Revenue Forecast (6 months)</div>
              <div className="card-subtitle">Prophet — trained on M5 Walmart dataset</div>
            </div>
            <span className="badge badge-violet">Prophet</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={forecastData} barSize={28}>
              <XAxis dataKey="month" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `₹${(v / 100000).toFixed(0)}L`} />
              <Tooltip content={<CustomTooltip />} formatter={v => [`₹${(+v).toLocaleString('en-IN')}`, 'Forecast']} />
              <Bar dataKey="forecast_inr" name="Revenue" fill="var(--accent-violet)" radius={[4, 4, 0, 0]} opacity={0.85} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* SKU Demand Forecast — Prophet with confidence bands */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">SKU Demand Forecast</div>
            <div className="card-subtitle">30-day Prophet forecast with 95% confidence bands — trained on real M5 Walmart sales data</div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {['SKU-001', 'SKU-002', 'SKU-003', 'SKU-004', 'SKU-005'].map((sku, i) => (
              <button
                key={sku}
                onClick={() => setActiveSku(sku)}
                style={{
                  padding: '4px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                  fontSize: 11, fontWeight: 600, transition: 'all .15s',
                  background: activeSku === sku ? SKU_COLORS[i] : 'var(--surface-2)',
                  color: activeSku === sku ? 'white' : 'var(--text-muted)',
                }}
              >
                {sku}
              </button>
            ))}
          </div>
        </div>

        {demandData.length === 0 ? (
          <div className="loading-wrap"><div className="spinner" /><span className="loading-text">Loading Prophet forecast…</span></div>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
              <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '8px 16px' }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Avg Daily Demand</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent-blue)' }}>
                  {Math.round(demandData.reduce((s, d) => s + d.yhat, 0) / Math.max(demandData.length, 1))} units
                </div>
              </div>
              <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '8px 16px' }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Peak Day</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent-green)' }}>
                  {Math.max(...demandData.map(d => d.yhat))} units
                </div>
              </div>
              <div style={{ background: 'var(--surface-2)', borderRadius: 8, padding: '8px 16px' }}>
                <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Confidence Band</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--accent-amber)' }}>±95%</div>
              </div>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={demandData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                <defs>
                  <linearGradient id="bandGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--accent-blue)" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="var(--accent-blue)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="date" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false}
                  tickFormatter={v => v ? v.slice(5) : ''} interval={4} />
                <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="yhat_upper" name="Upper bound" stroke="transparent" fill="url(#bandGrad)" />
                <Area type="monotone" dataKey="yhat_lower" name="Lower bound" stroke="transparent" fill="white" fillOpacity={0} />
                <Line type="monotone" dataKey="yhat" name="Forecast" stroke="var(--accent-blue)" strokeWidth={2.5} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, textAlign: 'center' }}>
              <BarChart2 size={12} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} />
              Solid line = Prophet point forecast · Shaded band = 95% confidence interval · Model: Prophet 1.3.0 + M5 Walmart training data
            </div>
          </>
        )}
      </div>
    </div>
  )
}
