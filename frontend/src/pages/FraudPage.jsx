import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ScatterChart, Scatter, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid
} from 'recharts'
import { fraudApi } from '../lib/api'
import { ShieldOff, ShieldCheck, ChevronDown, ChevronRight } from 'lucide-react'

const VERDICT_COLOR = { FRAUD: 'var(--accent-red)', CLEAR: 'var(--accent-green)' }

function ScatterDot({ cx, cy, payload }) {
  const isHigh = payload.xgb > 0.7
  const isAnomaly = payload.if_score > 0.55
  const color = isHigh ? '#ef4444' : isAnomaly ? '#f59e0b' : '#22c55e'
  return <circle cx={cx} cy={cy} r={5} fill={color} fillOpacity={0.75} stroke={color} strokeWidth={1} />
}

function ScatterTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div className="tooltip-box">
      <div style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-cyan)', marginBottom: 4 }}>{d.order_id}</div>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>IF Score: <strong style={{ color: d.if_score > 0.55 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>{d.if_score?.toFixed(3)}</strong></div>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>XGB Prob: <strong style={{ color: d.xgb > 0.7 ? 'var(--accent-red)' : 'var(--accent-green)' }}>{(d.xgb * 100).toFixed(1)}%</strong></div>
      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Verdict: <strong style={{ color: VERDICT_COLOR[d.verdict] }}>{d.verdict}</strong></div>
    </div>
  )
}

export default function FraudPage() {
  const [expandedRows, setExpandedRows] = useState({})
  const { data, isLoading } = useQuery({ queryKey: ['fraud'], queryFn: () => fraudApi.list({ limit: 200 }).then(r => r.data) })
  const { data: stats } = useQuery({ queryKey: ['fraud-stats'], queryFn: () => fraudApi.stats().then(r => r.data) })

  const records = data?.fraud_records || []
  const s = stats || {}

  const pie = [
    { name: 'Clear', value: s.clear || 0, color: '#22c55e' },
    { name: 'Fraud', value: s.fraud_flagged || 0, color: '#ef4444' },
  ].filter(d => d.value > 0)

  // Scatter data: IF score vs XGB probability
  const scatterData = records.map(r => ({
    if_score: +(+r.isolation_forest_score || 0).toFixed(3),
    xgb: +(+r.xgboost_fraud_probability || 0),
    verdict: r.fraud_verdict,
    order_id: r.order_id,
  }))

  const toggleRow = (id) => setExpandedRows(p => ({ ...p, [id]: !p[id] }))

  return (
    <div className="page-content animate-fade">
      {/* Header */}
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Fraud Detection</h1>
          <p className="page-subtitle">Agent 3 — Isolation Forest (anomaly) + XGBoost (pattern) — dual-model protection</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className="badge badge-green"><span className="ml-dot live" />Isolation Forest: Live</span>
          <span className="badge badge-green"><span className="ml-dot live" />XGBoost Fraud: Live</span>
        </div>
      </div>

      {/* KPIs */}
      <div className="kpi-grid" style={{ marginBottom: 16 }}>
        <div className="kpi-card">
          <div className="kpi-label">Total Screened</div>
          <div className="kpi-value">{s.total_screened || records.length}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Clear</div>
          <div className="kpi-value" style={{ color: 'var(--accent-green)' }}>{s.clear || 0}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Fraud Flagged</div>
          <div className="kpi-value" style={{ color: 'var(--accent-red)' }}>{s.fraud_flagged || 0}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Flag Rate</div>
          <div className="kpi-value" style={{ color: 'var(--accent-amber)' }}>
            {records.length > 0 ? ((s.fraud_flagged || 0) / records.length * 100).toFixed(1) : '0.0'}%
          </div>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        {/* Verdict Pie */}
        <div className="card">
          <div className="card-header"><div className="card-title">Verdict Distribution</div></div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
            <ResponsiveContainer width={150} height={150}>
              <PieChart>
                <Pie data={pie} dataKey="value" cx="50%" cy="50%" innerRadius={40} outerRadius={60} paddingAngle={4}>
                  {pie.map((d, i) => <Cell key={i} fill={d.color} />)}
                </Pie>
                <Tooltip formatter={(v, n) => [v, n]} />
              </PieChart>
            </ResponsiveContainer>
            <div>
              {pie.map(d => (
                <div key={d.name} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                  <div style={{ width: 10, height: 10, borderRadius: '50%', background: d.color }} />
                  <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{d.name}</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginLeft: 'auto' }}>{d.value}</span>
                </div>
              ))}
              <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                🟢 Both models must agree for auto-block<br/>
                Isolation Forest → anomaly · XGBoost → pattern
              </div>
            </div>
          </div>
        </div>

        {/* Risk Heatmap Scatter */}
        <div className="card">
          <div className="card-header">
            <div>
              <div className="card-title">Risk Heatmap</div>
              <div className="card-subtitle">Isolation Forest score vs XGBoost fraud probability</div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
              {[['#ef4444','High XGB + Anomaly'],['#f59e0b','Anomaly Only'],['#22c55e','Clear']].map(([c,l]) => (
                <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--text-muted)' }}>
                  <div style={{ width: 8, height: 8, borderRadius: '50%', background: c }} />{l}
                </div>
              ))}
            </div>
          </div>
          <ResponsiveContainer width="100%" height={190}>
            <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: -10 }}>
              <CartesianGrid stroke="var(--border)" />
              <XAxis dataKey="if_score" name="IF Score" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} label={{ value: 'IF Anomaly Score', position: 'insideBottom', offset: -5, fill: 'var(--text-muted)', fontSize: 10 }} domain={[0, 1]} />
              <YAxis dataKey="xgb" name="XGB Prob" tick={{ fill: 'var(--text-muted)', fontSize: 10 }} tickFormatter={v => `${(v * 100).toFixed(0)}%`} domain={[0, 1]} />
              <Tooltip content={<ScatterTooltip />} />
              <ReferenceLine x={0.55} stroke="rgba(245,158,11,0.4)" strokeDasharray="4 3" />
              <ReferenceLine y={0.7} stroke="rgba(239,68,68,0.4)" strokeDasharray="4 3" />
              <Scatter data={scatterData} shape={<ScatterDot />} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Fraud Records Table with SHAP Expandable */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Fraud Records</div>
            <div className="card-subtitle">Click a row to see why it was flagged (SHAP explanation)</div>
          </div>
          <span className="badge badge-blue">{records.length}</span>
        </div>
        {isLoading ? <div className="loading-wrap"><div className="spinner" /></div> : (
          records.length === 0 ? (
            <div className="empty-state">
              <ShieldCheck size={28} style={{ color: 'var(--accent-green)', opacity: 0.5 }} />
              <div className="empty-title">No fraud records yet</div>
              <div className="empty-text">Records appear as orders flow through Agent 3</div>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr>
                  <th style={{ width: 24 }}></th>
                  <th>Order</th><th>Customer</th>
                  <th>IF Score</th><th>XGB Prob</th>
                  <th>Anomaly Flag</th><th>Verdict</th><th>Blocked</th>
                </tr></thead>
                <tbody>
                  {records.map(f => {
                    const ifScore = +(+f.isolation_forest_score || 0)
                    const xgbProb = +(+f.xgboost_fraud_probability || 0)
                    const isExpanded = expandedRows[f.fraud_id]
                    const hasShap = f.shap_explanation && f.shap_explanation !== '—'
                    return (
                      <>
                        <tr
                          key={f.fraud_id}
                          onClick={() => hasShap && toggleRow(f.fraud_id)}
                          style={{ cursor: hasShap ? 'pointer' : 'default' }}
                        >
                          <td>
                            {hasShap
                              ? isExpanded
                                ? <ChevronDown size={12} style={{ color: 'var(--text-muted)' }} />
                                : <ChevronRight size={12} style={{ color: 'var(--text-muted)' }} />
                              : null}
                          </td>
                          <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-blue)' }}>{f.order_id}</td>
                          <td style={{ fontSize: 12 }}>{f.customer_id}</td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <div style={{ width: 40, height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                                <div style={{ width: `${(ifScore * 100).toFixed(0)}%`, height: '100%', background: ifScore > 0.55 ? 'var(--accent-amber)' : 'var(--accent-green)', borderRadius: 2 }} />
                              </div>
                              <span style={{ fontSize: 11, fontFamily: 'monospace' }}>{ifScore.toFixed(3)}</span>
                            </div>
                          </td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <div style={{ width: 40, height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                                <div style={{ width: `${(xgbProb * 100).toFixed(0)}%`, height: '100%', background: xgbProb > 0.7 ? 'var(--accent-red)' : xgbProb > 0.4 ? 'var(--accent-amber)' : 'var(--accent-green)', borderRadius: 2 }} />
                              </div>
                              <span style={{ fontSize: 11, fontFamily: 'monospace' }}>{(xgbProb * 100).toFixed(1)}%</span>
                            </div>
                          </td>
                          <td>
                            <span className={`badge ${f.anomaly_flag ? 'badge-amber' : 'badge-green'}`}>
                              {f.anomaly_flag ? '⚠ Anomaly' : '✓ Normal'}
                            </span>
                          </td>
                          <td>
                            <span className={`badge ${f.fraud_verdict === 'FRAUD' ? 'badge-red' : 'badge-green'}`}>
                              {f.fraud_verdict === 'FRAUD' ? <><ShieldOff size={10} /> FRAUD</> : <><ShieldCheck size={10} /> CLEAR</>}
                            </span>
                          </td>
                          <td>{f.order_blocked ? <span className="badge badge-red">Blocked</span> : <span className="badge badge-gray">Passed</span>}</td>
                        </tr>
                        {isExpanded && hasShap && (
                          <tr key={`${f.fraud_id}-shap`}>
                            <td colSpan={8} style={{ padding: '0 16px 12px 40px' }}>
                              <div style={{ background: 'rgba(245,158,11,.07)', border: '1px solid rgba(245,158,11,.25)', borderRadius: 6, padding: '10px 14px', fontSize: 12 }}>
                                <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent-amber)', textTransform: 'uppercase', marginBottom: 6 }}>
                                  Why Flagged (SHAP Explanation)
                                </div>
                                <div style={{ color: 'var(--text-secondary)', lineHeight: 1.7 }}>{f.shap_explanation}</div>
                                {f.shap_top_feature && (
                                  <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                                    Top contributing feature: <strong style={{ color: 'var(--accent-cyan)' }}>{f.shap_top_feature}</strong>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </div>
  )
}
