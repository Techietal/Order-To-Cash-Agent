import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { cashAppApi } from '../lib/api'
import { Zap, Clock, AlertTriangle, CheckCircle, Send, RefreshCw } from 'lucide-react'

const ROUTE_CONFIG = {
  AUTO_POSTED:   { label: 'Auto-Posted',    color: 'var(--accent-green)',  bg: 'rgba(16,185,129,.12)',  icon: Zap },
  LLM_VERIFIED:  { label: 'LLM Verified',   color: 'var(--accent-blue)',   bg: 'rgba(59,130,246,.12)',  icon: CheckCircle },
  LLM_REJECTED:  { label: 'LLM Rejected',   color: 'var(--accent-amber)',  bg: 'rgba(245,158,11,.12)',  icon: AlertTriangle },
  HITL_REQUIRED: { label: 'HITL Required',  color: 'var(--accent-red)',    bg: 'rgba(239,68,68,.12)',   icon: Clock },
  NO_MATCH:      { label: 'No Match',       color: 'var(--text-muted)',    bg: 'rgba(255,255,255,.05)', icon: AlertTriangle },
}

function ConfidenceBar({ score, threshold = 0.78 }) {
  const pct = Math.min(score * 100, 100)
  const color = score >= threshold ? 'var(--accent-green)' : score >= 0.5 ? 'var(--accent-amber)' : 'var(--accent-red)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct.toFixed(0)}%`, height: '100%', background: color, borderRadius: 3, transition: 'width .4s ease' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 36 }}>{pct.toFixed(0)}%</span>
    </div>
  )
}

export default function CashApplicationPage() {
  const qc = useQueryClient()
  const [remittanceText, setRemittanceText] = useState('')
  const [matchResult, setMatchResult] = useState(null)
  const [invoiceId, setInvoiceId] = useState('')

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['cash-stats'],
    queryFn: () => cashAppApi.stats().then(r => r.data),
    refetchInterval: 30000,
  })

  const { data: paymentsData, isLoading: paymentsLoading } = useQuery({
    queryKey: ['cash-payments'],
    queryFn: () => cashAppApi.payments({ limit: 50 }).then(r => r.data),
    refetchInterval: 30000,
  })

  const matchMut = useMutation({
    mutationFn: () => cashAppApi.processPayment({
      remittance_text: remittanceText,
      expected_invoice_id: invoiceId.trim() || undefined,
    }).then(r => r.data),
    onSuccess: (data) => {
      setMatchResult(data)
      qc.invalidateQueries({ queryKey: ['cash-payments'] })
      qc.invalidateQueries({ queryKey: ['cash-stats'] })
    },
    onError: (err) => {
      setMatchResult({ success: false, route: 'NO_MATCH', agent_reason: err.response?.data?.detail || err.message, confidence: 0 })
    }
  })

  const s = stats || {}
  const payments = paymentsData?.payments || []

  const paidCount = s.paid || 0
  const pendingCount = s.pending || 0
  const autoPosted = s.auto_posted || 0
  const autoMatchRate = s.auto_match_rate || 0

  const pieData = [
    { name: 'Auto-Matched', value: autoPosted, color: '#22c55e' },
    { name: 'Manual / HITL', value: Math.max(0, paidCount - autoPosted), color: '#3b82f6' },
    { name: 'Pending', value: pendingCount, color: '#f59e0b' },
  ].filter(d => d.value > 0)

  const routeConf = matchResult ? (ROUTE_CONFIG[matchResult.route] || ROUTE_CONFIG.NO_MATCH) : null
  const RouteIcon = routeConf?.icon

  return (
    <div className="page-content animate-fade">
      {/* Header */}
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Cash Application</h1>
          <p className="page-subtitle">Agent 9 — all-MiniLM-L6-v2 semantic matching · auto-post ≥ 78% · Groq LLM verification 50–77% · HITL below 50%</p>
        </div>
        <span className="badge badge-green"><span className="ml-dot live" />Sentence Transformer: Live</span>
      </div>

      {/* KPI Strip */}
      <div className="kpi-grid" style={{ marginBottom: 20 }}>
        <div className="kpi-card">
          <div className="kpi-label">Auto-Match Rate</div>
          <div className="kpi-value" style={{ color: autoMatchRate >= 0.9 ? 'var(--accent-green)' : 'var(--accent-amber)' }}>
            {(autoMatchRate * 100).toFixed(0)}%
          </div>
          <div className="kpi-delta up">Target ≥ 90%</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Paid Invoices</div>
          <div className="kpi-value" style={{ color: 'var(--accent-green)' }}>{paidCount}</div>
          <div className="kpi-delta">{autoPosted} auto-matched by AI</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Pending Payment</div>
          <div className="kpi-value" style={{ color: 'var(--accent-amber)' }}>{pendingCount}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Confidence Threshold</div>
          <div className="kpi-value">78%</div>
          <div className="kpi-delta">50–77%: Groq verifies · &lt;50%: HITL</div>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        {/* Remittance Matcher */}
        <div className="card">
          <div className="card-header">
            <div className="card-title">Remittance Matcher</div>
            <span className="badge badge-violet">Agent 9 — Live</span>
          </div>
          <div style={{ marginBottom: 10 }}>
            <label className="form-label">Remittance Advice Text</label>
            <textarea
              className="form-input" rows={4}
              placeholder={'e.g. "Pls find attached payment for INV-20260601-P, amount 85000 INR, ref PO-44321"'}
              value={remittanceText}
              onChange={e => setRemittanceText(e.target.value)}
              style={{ resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }}
            />
          </div>
          <div style={{ marginBottom: 12 }}>
            <label className="form-label">Expected Invoice ID (optional — leave blank for auto-search)</label>
            <input className="form-input" placeholder="INV-20260601-P" value={invoiceId} onChange={e => setInvoiceId(e.target.value)} />
          </div>
          <button
            className="btn btn-primary"
            style={{ width: '100%' }}
            onClick={() => matchMut.mutate()}
            disabled={!remittanceText.trim() || matchMut.isPending}
          >
            {matchMut.isPending
              ? <><span className="loading-dot" /> Running Semantic Match…</>
              : <><Send size={14} /> Match & Apply Payment</>}
          </button>

          {/* Match Result */}
          {matchResult && routeConf && (
            <div style={{ marginTop: 14, padding: 14, background: routeConf.bg, borderRadius: 8, border: `1px solid ${routeConf.color}40` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <RouteIcon size={15} style={{ color: routeConf.color }} />
                <span style={{ fontWeight: 700, fontSize: 13, color: routeConf.color }}>{routeConf.label}</span>
                {matchResult.invoice_id && (
                  <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-cyan)' }}>{matchResult.invoice_id}</span>
                )}
              </div>
              {matchResult.confidence > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
                    Cosine Similarity Score (all-MiniLM-L6-v2)
                  </div>
                  <ConfidenceBar score={matchResult.confidence} />
                </div>
              )}
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                {matchResult.agent_reason}
              </div>
            </div>
          )}
        </div>

        {/* Match Rate Chart + How It Works */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="card">
            <div className="card-header"><div className="card-title">Payment Distribution</div></div>
            {statsLoading ? <div className="loading-wrap"><div className="spinner" /></div> : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <ResponsiveContainer width={140} height={140}>
                  <PieChart>
                    <Pie data={pieData} dataKey="value" cx="50%" cy="50%" innerRadius={38} outerRadius={58} paddingAngle={3}>
                      {pieData.map((d, i) => <Cell key={i} fill={d.color} />)}
                    </Pie>
                    <Tooltip formatter={(v, n) => [v, n]} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ flex: 1 }}>
                  {pieData.map(d => (
                    <div key={d.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: d.color }} />
                        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{d.name}</span>
                      </div>
                      <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{d.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="card">
            <div className="card-header"><div className="card-title">Matching Pipeline</div></div>
            {[
              ['≥ 78% similarity', 'Auto-posted to AR immediately — no human touch', 'var(--accent-green)'],
              ['50–77% similarity', 'Groq LLM secondary verification — confirms or rejects', 'var(--accent-blue)'],
              ['< 50% similarity', 'Routed to HITL queue for manual matching', 'var(--accent-red)'],
            ].map(([threshold, desc, color]) => (
              <div key={threshold} style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ width: 3, borderRadius: 2, background: color, flexShrink: 0 }} />
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color, marginBottom: 2 }}>{threshold}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Payment History Table */}
      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Payment History</div>
            <div className="card-subtitle">All paid invoices — AI matched and manually applied</div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="badge badge-green">{payments.length} records</span>
            <button className="btn btn-secondary btn-sm" onClick={() => qc.invalidateQueries({ queryKey: ['cash-payments'] })}>
              <RefreshCw size={12} /> Refresh
            </button>
          </div>
        </div>
        {paymentsLoading ? <div className="loading-wrap"><div className="spinner" /></div> : (
          payments.length === 0 ? (
            <div className="empty-state">
              <CheckCircle size={28} style={{ color: 'var(--accent-green)', opacity: 0.4 }} />
              <div className="empty-title">No paid invoices yet</div>
              <div className="empty-text">Use the matcher above to process a remittance</div>
            </div>
          ) : (
            <div className="table-wrap"><table>
              <thead><tr>
                <th>Invoice</th><th>Customer</th><th>Amount Paid</th><th>Status</th><th>Settled</th>
              </tr></thead>
              <tbody>{payments.map(p => (
                <tr key={p.invoice_id}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-cyan)' }}>{p.invoice_id}</td>
                  <td style={{ fontSize: 12 }}>{p.company_name || p.customer_id}</td>
                  <td style={{ fontWeight: 700, color: 'var(--accent-green)' }}>
                    ₹{(+p.amount_paid_inr || +p.total_amount_inr || 0).toLocaleString('en-IN')}
                  </td>
                  <td><span className="badge badge-green">Paid</span></td>
                  <td style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {p.updated_at ? new Date(p.updated_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'}
                  </td>
                </tr>
              ))}</tbody>
            </table></div>
          )
        )}
      </div>
    </div>
  )
}
