import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api, { ordersApi } from '../lib/api'
import { ActionGuard } from './RoleGuard'
import {
  X, CheckCircle, AlertTriangle, Clock, XCircle, ShieldAlert,
  CreditCard, FileText, Package, Zap, DollarSign
} from 'lucide-react'

// ── Agent metadata (mirrors OrderLifecyclePage) ─────────────────────────────
const AGENT_META = {
  'agent_01_order_ingestion':    { label: 'Agent 1 — Order Ingestion',    color: '#3b82f6', model: 'GLiNER NER + Groq',              icon: Package },
  'agent_02_credit_assessment':  { label: 'Agent 2 — Credit Check',       color: '#06b6d4', model: 'XGBoost Credit + PD Logistic',   icon: CreditCard },
  'agent_03_fraud_detection':    { label: 'Agent 3 — Fraud Detection',    color: '#ef4444', model: 'Isolation Forest + XGBoost',     icon: ShieldAlert },
  'agent_04_demand_forecasting': { label: 'Agent 4 — Demand Forecast',    color: '#8b5cf6', model: 'Prophet',                        icon: Zap },
  'agent_05_fulfillment':        { label: 'Agent 5 — Fulfillment',        color: '#22c55e', model: 'Rule-based',                     icon: CheckCircle },
  'agent_06_invoice_generation': { label: 'Agent 6 — Invoice',            color: '#f59e0b', model: 'Template engine',               icon: FileText },
  'agent_07_payment_monitoring': { label: 'Agent 7 — Payment Monitor',    color: '#f59e0b', model: 'XGBoost Delay',                  icon: Clock },
  'agent_08_collections':        { label: 'Agent 8 — Collections',        color: '#f59e0b', model: 'K-Means + Groq Dunning',         icon: AlertTriangle },
  'COMPLIANCE':                  { label: 'Policy Engine / Compliance',   color: '#8b5cf6', model: 'Rule Engine RULE-001 to RULE-008', icon: AlertTriangle },
}

function getAgentMeta(entry) {
  const agent = entry.agent_name || entry.source_agent || ''
  if (AGENT_META[agent]) return AGENT_META[agent]
  for (const key of Object.keys(AGENT_META)) {
    if (agent.startsWith(key.slice(0, 8))) return AGENT_META[key]
  }
  return { label: agent || entry.event_type || 'System', icon: CheckCircle, color: 'var(--brand)', model: '' }
}

// ── Timeline step ─────────────────────────────────────────────────────────────
function TimelineStep({ entry, isLast }) {
  const [expanded, setExpanded] = useState(false)
  const meta = getAgentMeta(entry)
  const Icon = meta.icon
  const hasDetails = entry.details && entry.details !== '{}'

  return (
    <div style={{ display: 'flex', gap: 0 }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 36, flexShrink: 0 }}>
        <div style={{
          width: 28, height: 28, borderRadius: '50%',
          background: `${meta.color}22`, border: `2px solid ${meta.color}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}>
          <Icon size={12} style={{ color: meta.color }} />
        </div>
        {!isLast && <div style={{ width: 2, flex: 1, background: 'var(--border)', margin: '3px 0' }} />}
      </div>
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : 14, paddingLeft: 10 }}>
        <div
          onClick={() => hasDetails && setExpanded(p => !p)}
          style={{ cursor: hasDetails ? 'pointer' : 'default' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: meta.color }}>{meta.label}</span>
            {meta.model && <span className="badge badge-gray" style={{ fontSize: 9 }}>{meta.model}</span>}
            {hasDetails && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{expanded ? '▲' : '▼'}</span>}
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 2 }}>
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{entry.action || entry.event_type}</span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
              {entry.created_at ? new Date(entry.created_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''}
            </span>
          </div>
        </div>
        {expanded && hasDetails && (
          <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 5, padding: '8px 12px', marginTop: 5 }}>
            {(() => {
              try {
                const parsed = typeof entry.details === 'string' ? JSON.parse(entry.details) : entry.details
                return Object.entries(parsed).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', gap: 8, marginBottom: 3, fontSize: 11 }}>
                    <span style={{ color: 'var(--brand)', minWidth: 130 }}>{k}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                  </div>
                ))
              } catch {
                return <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{entry.details}</div>
              }
            })()}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Overlay backdrop ──────────────────────────────────────────────────────────
const BACKDROP = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
  zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  padding: '20px',
}
const MODAL = {
  background: 'var(--surface)', border: '1px solid var(--border)',
  borderRadius: 8, width: '100%', maxWidth: 860,
  maxHeight: '88vh', display: 'flex', flexDirection: 'column',
  boxShadow: 'var(--shadow-32)',
}
const TABS = ['Lifecycle', 'Fraud Detail']

// ── OrderDetailModal (exported) ───────────────────────────────────────────────
export default function OrderDetailModal({ orderId, onClose }) {
  const [tab, setTab] = useState('Lifecycle')
  const qc = useQueryClient()

  const { data: traceData, isLoading: traceLoading } = useQuery({
    queryKey: ['order-trace', orderId],
    queryFn: () => api.get('/compliance/audit-log', { params: { order_id: orderId, limit: 50 } }).then(r => r.data),
    enabled: !!orderId,
  })
  const { data: orderData } = useQuery({
    queryKey: ['order-detail', orderId],
    queryFn: () => api.get(`/orders/${orderId}`).then(r => r.data),
    enabled: !!orderId,
  })
  const { data: fraudData } = useQuery({
    queryKey: ['order-fraud-modal', orderId],
    queryFn: () => api.get('/fraud', { params: { order_id: orderId } }).then(r => r.data),
    enabled: !!orderId,
  })

const auditLog     = traceData?.audit_log || []
  const order        = orderData?.order || orderData || {}
  const reservations = order?.reservations || (order?.reservation ? [order.reservation] : [])
  const reservation  = reservations[0] || null
  const fraudRecord  = (fraudData?.fraud_records || [])[0]
  const fulfillMut = useMutation({ mutationFn: () => ordersApi.fulfill(orderId, { idempotency_key: `fulfill-${Date.now()}` }), onSuccess: () => { qc.invalidateQueries({ queryKey: ['order-detail', orderId] }); qc.invalidateQueries({ queryKey: ['orders'] }) } })
  const cancelMut = useMutation({ mutationFn: () => ordersApi.cancel(orderId), onSuccess: () => { qc.invalidateQueries({ queryKey: ['order-detail', orderId] }); qc.invalidateQueries({ queryKey: ['orders'] }) } })

  const statusColor = (s) => {
    if (['fulfilled', 'approved', 'closed', 'credit_approved', 'invoiced'].includes(s)) return 'var(--success)'
    if (['fraud_review', 'cancelled'].includes(s)) return 'var(--danger)'
    if (s?.includes('hitl') || s === 'pending_credit') return 'var(--warning)'
    return 'var(--text-muted)'
  }

  return (
    <div style={BACKDROP} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={MODAL}>
        {/* Modal Header */}
        <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 2 }}>Order Lifecycle</div>
            <div style={{ fontSize: 17, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: 'var(--brand)' }}>{orderId}</div>
          </div>
          {/* Quick stats */}
          {order?.order_id && (
            <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Customer</div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{order.customer_id}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Amount</div>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--success)' }}>₹{(+(order.total_amount_inr || 0)).toLocaleString('en-IN')}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Status</div>
                <div style={{ fontSize: 12, fontWeight: 700, color: statusColor(order.status) }}>{order.status}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Fraud Score</div>
                <div style={{ fontSize: 12, fontWeight: 700, color: (+order.fraud_score) > 0.7 ? 'var(--accent-red)' : (+order.fraud_score) > 0.4 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                  {order.fraud_score != null ? `${((+order.fraud_score)*100).toFixed(1)}%` : '—'}
                </div>
              </div>
            </div>
          )}
          <button
            onClick={onClose}
            style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: 6, cursor: 'pointer', color: 'var(--text-secondary)', transition: 'all .15s', flexShrink: 0 }}
          >
            <X size={16} />
          </button>
        </div>

<ActionGuard allowed={['admin', 'controller', 'inventory_manager']}>
          <div style={{ display: 'flex', gap: 8, padding: '10px 24px', borderBottom: '1px solid var(--border)' }}>
            {order.status !== 'fulfilled' && <button className="btn btn-success btn-sm" onClick={() => fulfillMut.mutate()} disabled={fulfillMut.isPending || order.status === 'cancelled'}>Mark Fulfilled</button>}
            {order.status !== 'cancelled' && <button className="btn btn-danger btn-sm" onClick={() => cancelMut.mutate()} disabled={cancelMut.isPending || order.status === 'fulfilled'}>Cancel Order</button>}
            {fulfillMut.isError && <span className="badge badge-red">Fulfill failed</span>}
            {cancelMut.isError && <span className="badge badge-red">Cancel failed</span>}
          </div>
        </ActionGuard>

        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', paddingLeft: 20 }}>
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '10px 16px', fontSize: 13, fontWeight: tab === t ? 700 : 500,
                color: tab === t ? 'var(--brand)' : 'var(--text-muted)',
                borderBottom: tab === t ? '2px solid var(--brand)' : '2px solid transparent',
                marginBottom: -1, transition: 'all .15s',
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {/* Tab Content — scrollable body */}
        <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>

          {/* ── LIFECYCLE TAB ─────────────────────────────── */}
          {tab === 'Lifecycle' && (
            traceLoading ? (
              <div className="loading-wrap"><div className="spinner" /></div>
            ) : (
              <div>
{reservations.map((res, idx) => (
                  <div key={res.reservation_id || idx} className="card" style={{ marginBottom: 14, padding: 14 }}>
                    <div className="card-title" style={{ marginBottom: 10 }}>Inventory Reservation{reservations.length > 1 ? ` #${idx + 1}` : ''}</div>
                    <div className="grid-4">
                      <div><div className="kpi-label">Reserved</div><div className="stat-val">{res.quantity_reserved}</div></div>
                      <div><div className="kpi-label">Backordered</div><div className="stat-val">{res.quantity_backordered}</div></div>
                      <div><div className="kpi-label">ETA</div><div className="stat-val">{res.expected_availability_date ? new Date(res.expected_availability_date).toLocaleDateString() : '—'}</div></div>
                      <div><div className="kpi-label">Status</div><span className="badge badge-blue">{res.status}</span></div>
                    </div>
                  </div>
                ))}
                {auditLog.length === 0 ? (
                  <div className="empty-state"><Clock size={28} style={{ opacity: 0.3 }} /><div className="empty-title">No audit trail yet</div><div className="empty-text">Audit log is populated as the order flows through the pipeline.</div></div>
                ) : (
                  <div style={{ padding: '4px 0' }}>{auditLog.map((entry, i) => <TimelineStep key={i} entry={entry} isLast={i === auditLog.length - 1} />)}</div>
                )}
              </div>
            )
          )}

          {/* ── FRAUD DETAIL TAB ──────────────────────────── */}
          {tab === 'Fraud Detail' && (
            fraudRecord ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  {[
                    ['Verdict',        fraudRecord.fraud_verdict,  fraudRecord.fraud_verdict === 'FRAUD' ? 'var(--danger)' : 'var(--success)'],
                    ['IF Score',       (+fraudRecord.isolation_forest_score||0).toFixed(4), (+fraudRecord.isolation_forest_score||0) > 0.55 ? 'var(--warning)' : 'var(--success)'],
                    ['XGB Probability',`${((+(fraudRecord.xgboost_fraud_probability||0))*100).toFixed(1)}%`, (+fraudRecord.xgboost_fraud_probability||0) > 0.7 ? 'var(--danger)' : 'var(--success)'],
                    ['Top SHAP',       fraudRecord.shap_top_feature || '—', 'var(--brand)'],
                  ].map(([k, v, c]) => (
                    <div key={k} style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 16px', flex: '1 1 120px' }}>
                      <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>{k}</div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: c }}>{v}</div>
                    </div>
                  ))}
                </div>
                {fraudRecord.shap_values && (
                  <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, padding: '14px 18px' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: 10 }}>SHAP Feature Importance</div>
                    {(() => {
                      try {
                        const shap = typeof fraudRecord.shap_values === 'string' ? JSON.parse(fraudRecord.shap_values) : fraudRecord.shap_values
                        return Object.entries(shap).sort(([,a],[,b]) => Math.abs(b) - Math.abs(a)).map(([feat, val]) => (
                          <div key={feat} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 7 }}>
                            <span style={{ fontSize: 11, color: 'var(--text-secondary)', minWidth: 160 }}>{feat}</span>
                            <div style={{ flex: 1, height: 5, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                              <div style={{ width: `${Math.min(Math.abs(+val) * 300, 100)}%`, height: '100%', background: +val > 0 ? 'var(--danger)' : 'var(--success)', borderRadius: 3 }} />
                            </div>
                            <span style={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: +val > 0 ? 'var(--danger)' : 'var(--success)', minWidth: 50, textAlign: 'right' }}>{(+val).toFixed(4)}</span>
                          </div>
                        ))
                      } catch { return null }
                    })()}
                  </div>
                )}
              </div>
            ) : (
              <div className="empty-state">
                <ShieldAlert size={28} style={{ opacity: 0.3 }} />
                <div className="empty-title">No fraud record</div>
                <div className="empty-text">This order has not been scored by the fraud detection pipeline yet.</div>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  )
}
