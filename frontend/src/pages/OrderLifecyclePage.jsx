import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../lib/api'
import { CheckCircle, AlertTriangle, Clock, XCircle, ShieldAlert, CreditCard, FileText, Package, Zap, DollarSign } from 'lucide-react'

function orderStatusBadge(status) {
  if (['fulfilled', 'approved', 'closed', 'credit_approved'].includes(status)) return 'badge-green'
  if (['cancelled', 'fraud_review'].includes(status)) return 'badge-red'
  if (['partially_reserved', 'pending_credit'].includes(status) || status?.includes('hitl')) return 'badge-amber'
  if (status === 'backordered') return 'badge-violet'
  return 'badge-gray'
}

const stepApi = {
  trace: (orderId) => api.get(`/compliance/audit-log`, { params: { order_id: orderId, limit: 50 } }),
  order: (orderId) => api.get(`/orders/${orderId}`),
  fraud: (orderId) => api.get(`/fraud`, { params: { order_id: orderId } }),
  credit: (orderId) => api.get(`/compliance/ecoa-report`),
}

const AGENT_META = {
  'agent_01_order_ingestion':      { label: 'Agent 1 — Order Ingestion',      icon: Package,      color: '#3b82f6', model: 'GLiNER NER + Groq' },
  'agent_02_credit_assessment':    { label: 'Agent 2 — Credit Check',          icon: CreditCard,   color: '#06b6d4', model: 'XGBoost Credit + PD Logistic Reg' },
  'agent_03_fraud_detection':      { label: 'Agent 3 — Fraud Detection',       icon: ShieldAlert,  color: '#ef4444', model: 'Isolation Forest + XGBoost Fraud' },
  'agent_04_demand_forecasting':   { label: 'Agent 4 — Demand Forecast',       icon: Zap,          color: '#8b5cf6', model: 'Prophet' },
  'agent_05_fulfillment':          { label: 'Agent 5 — Fulfillment',           icon: CheckCircle,  color: '#22c55e', model: 'Rule-based' },
  'agent_06_invoice_generation':   { label: 'Agent 6 — Invoice Generation',    icon: FileText,     color: '#f59e0b', model: 'Template engine' },
  'agent_07_payment_monitoring':   { label: 'Agent 7 — Payment Monitor',       icon: Clock,        color: '#f59e0b', model: 'XGBoost Delay' },
  'agent_08_collections':          { label: 'Agent 8 — Collections',           icon: AlertTriangle, color: '#f59e0b', model: 'K-Means + Groq Dunning' },
  'agent_09_cash_application':     { label: 'Agent 9 — Cash Application',      icon: DollarSign,   color: '#22c55e', model: 'MiniLM Semantic Matching' },
  'COMPLIANCE':                    { label: 'Policy Engine / Compliance',       icon: AlertTriangle, color: '#8b5cf6', model: 'Rule Engine (RULE-001 to RULE-008)' },
  'CASH_APPLICATION':              { label: 'Cash Application',                 icon: DollarSign,   color: '#22c55e', model: 'MiniLM Sentence Transformer' },
}

function getAgentMeta(entry) {
  const agent = entry.agent_name || entry.source_agent || ''
  if (AGENT_META[agent]) return AGENT_META[agent]
  // Try prefix match
  for (const key of Object.keys(AGENT_META)) {
    if (agent.startsWith(key.slice(0, 8))) return AGENT_META[key]
  }
  return { label: agent || entry.event_type || 'System', icon: CheckCircle, color: 'var(--accent-blue)', model: '' }
}

function TimelineStep({ entry, idx, isLast }) {
  const [expanded, setExpanded] = useState(false)
  const meta = getAgentMeta(entry)
  const Icon = meta.icon
  const hasDetails = entry.details && entry.details !== '{}'

  return (
    <div style={{ display: 'flex', gap: 0 }}>
      {/* Left connector */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 40, flexShrink: 0 }}>
        <div style={{
          width: 32, height: 32, borderRadius: '50%', background: `${meta.color}22`,
          border: `2px solid ${meta.color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0
        }}>
          <Icon size={14} style={{ color: meta.color }} />
        </div>
        {!isLast && <div style={{ width: 2, flex: 1, background: 'var(--border)', margin: '4px 0' }} />}
      </div>

      {/* Content */}
      <div style={{ flex: 1, paddingBottom: isLast ? 0 : 16, paddingLeft: 12 }}>
        <div
          onClick={() => hasDetails && setExpanded(p => !p)}
          style={{ cursor: hasDetails ? 'pointer' : 'default', marginBottom: 4 }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: meta.color }}>{meta.label}</span>
            {meta.model && <span className="badge badge-gray" style={{ fontSize: 9 }}>{meta.model}</span>}
            {hasDetails && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{expanded ? '▲' : '▼'}</span>}
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 3 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{entry.action || entry.event_type}</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {entry.created_at ? new Date(entry.created_at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}
            </span>
          </div>
        </div>

        {expanded && hasDetails && (
          <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: '10px 14px', marginTop: 6 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 6 }}>Details</div>
            {(() => {
              try {
                const parsed = typeof entry.details === 'string' ? JSON.parse(entry.details) : entry.details
                return Object.entries(parsed).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', gap: 10, marginBottom: 4, fontSize: 12 }}>
                    <span style={{ color: 'var(--accent-cyan)', minWidth: 140 }}>{k}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                  </div>
                ))
              } catch {
                return <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{entry.details}</div>
              }
            })()}
          </div>
        )}
      </div>
    </div>
  )
}

export default function OrderLifecyclePage() {
  const [orderId, setOrderId] = useState('ORD-001-A')
  const [inputVal, setInputVal] = useState('ORD-001-A')

  const { data: traceData, isLoading, refetch } = useQuery({
    queryKey: ['order-trace', orderId],
    queryFn: () => stepApi.trace(orderId).then(r => r.data),
    enabled: !!orderId,
  })
  const { data: orderData } = useQuery({
    queryKey: ['order-detail', orderId],
    queryFn: () => stepApi.order(orderId).then(r => r.data),
    enabled: !!orderId,
  })
  const { data: fraudData } = useQuery({
    queryKey: ['order-fraud', orderId],
    queryFn: () => api.get('/fraud', { params: { order_id: orderId } }).then(r => r.data),
    enabled: !!orderId,
  })
  const { data: recentOrdersData } = useQuery({
    queryKey: ['recent-orders-list'],
    queryFn: () => api.get('/orders', { params: { limit: 10 } }).then(r => r.data),
  })

  const auditLog = traceData?.audit_log || []
  const order = orderData?.order || orderData || {}
  const fraudRecord = (fraudData?.fraud_records || [])[0]
  const recentOrdersList = (recentOrdersData?.orders || []).map(o => o.order_id)

  const handleSearch = () => {
    if (inputVal.trim()) {
      setOrderId(inputVal.trim().toUpperCase())
    }
  }

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Order Lifecycle Tracker</h1>
          <p className="page-subtitle">End-to-end audit trail — every agent step, ML score, and decision for any order</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="form-input"
            style={{ width: 200 }}
            placeholder="Order ID e.g. ORD-001-A"
            value={inputVal}
            onChange={e => setInputVal(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
          />
          <button className="btn btn-primary btn-sm" onClick={handleSearch}>Trace</button>
        </div>
      </div>

      {/* Order Summary Card */}
      {order?.order_id && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Order</div>
              <div style={{ fontFamily: 'monospace', fontWeight: 800, color: 'var(--accent-blue)', fontSize: 16 }}>{order.order_id}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Customer</div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{order.customer_id}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Amount</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-cyan)' }}>₹{(+(order.total_amount_inr || 0)).toLocaleString('en-IN')}</div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Status</div>
              <span className={`badge ${orderStatusBadge(order.status)}`}>
                {order.status}
              </span>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Channel</div>
              <span className="badge badge-gray">{order.channel}</span>
            </div>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Fraud Score</div>
              <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 13, color: (+order.fraud_score) > 0.7 ? 'var(--accent-red)' : (+order.fraud_score) > 0.4 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                {order.fraud_score != null ? `${((+order.fraud_score) * 100).toFixed(1)}%` : '—'}
              </div>
            </div>
            {fraudRecord && (
              <div>
                <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>IF Score</div>
                <div style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 13, color: (+fraudRecord.isolation_forest_score) > 0.55 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                  {(+(fraudRecord.isolation_forest_score || 0)).toFixed(3)}
                </div>
              </div>
            )}
            {order.hitl_required && <span className="badge badge-amber">⚠ HITL Required</span>}
            {['partially_reserved', 'backordered', 'fulfilled', 'cancelled'].includes(order.status) && <span className={`badge ${orderStatusBadge(order.status)}`}>Inventory: {order.status}</span>}
          </div>
        </div>
      )}

      {/* Timeline */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Agent Execution Timeline</div>
          <span className="badge badge-blue">{auditLog.length} events</span>
        </div>
        {isLoading ? (
          <div className="loading-wrap"><div className="spinner" /></div>
        ) : auditLog.length === 0 ? (
          <div className="empty-state">
            <Clock size={28} style={{ color: 'var(--text-muted)', opacity: 0.4 }} />
            <div className="empty-title">No audit trail found</div>
            <div className="empty-text">Enter an Order ID and click Trace · Audit log is populated as orders flow through the system</div>
          </div>
        ) : (
          <div style={{ padding: '8px 0' }}>
            {auditLog.map((entry, i) => (
              <TimelineStep
                key={i}
                entry={entry}
                idx={i}
                isLast={i === auditLog.length - 1}
              />
            ))}
          </div>
        )}
      </div>

      {/* Shortcut list of recent orders */}
      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-header"><div className="card-title">Quick Jump — Recent Orders</div></div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '4px 0' }}>
          {(recentOrdersList).map(id => (
            <button
              key={id}
              onClick={() => { setInputVal(id); setOrderId(id) }}
              style={{
                padding: '5px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 600, transition: 'all .15s',
                background: orderId === id ? 'var(--accent-blue)' : 'var(--surface-2)',
                color: orderId === id ? 'white' : 'var(--text-muted)',
              }}
            >{id}</button>
          ))}
        </div>
      </div>
    </div>
  )
}
