import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { arApi, ordersApi, collectionsApi, fraudApi, creditMemosApi } from '../lib/api'
import api from '../lib/api'
import {
  User, CreditCard, FileText, ShieldOff, Package, TrendingDown,
  History, CheckCircle2, ArrowDownRight, ShieldCheck, Landmark
} from 'lucide-react'

const customersApi = {
  list: () => api.get('/customers'),
  get: (id) => api.get(`/customers/${id}`),
}

const TIER_COLOR = { A: 'var(--accent-green)', B: 'var(--accent-blue)', C: 'var(--accent-amber)', D: 'var(--accent-red)' }
const SEG_COLOR  = { Premium: '#22c55e', Standard: '#3b82f6', 'At-Risk': '#f59e0b', Problem: '#ef4444' }
const ROLE_BADGE_COLOR = {
  admin:               { bg: 'rgba(59,130,246,0.15)',  color: 'var(--accent-blue)' },
  dispute_manager:     { bg: 'rgba(245,158,11,0.15)',  color: 'var(--accent-amber)' },
  collections_analyst: { bg: 'rgba(34,197,94,0.15)',   color: 'var(--accent-green)' },
  controller:          { bg: 'rgba(139,92,246,0.15)',  color: 'var(--accent-violet)' },
  customer:            { bg: 'rgba(20,184,166,0.15)',  color: 'var(--accent-teal)' },
}

const SOURCE_META_C360 = {
  dispute_resolution: { label: 'Dispute Credit',       icon: ShieldCheck, color: 'var(--accent-amber)', bg: 'rgba(245,158,11,0.12)' },
  ar_ledger_manual:   { label: 'AR Ledger (Manual)',   icon: Landmark,    color: 'var(--accent-teal)',  bg: 'rgba(20,184,166,0.12)' },
  customer_portal:    { label: 'Customer Portal',      icon: CreditCard,  color: 'var(--accent-blue)',  bg: 'rgba(59,130,246,0.12)' },
  hitl_payment:       { label: 'HITL Approved',        icon: History,     color: 'var(--accent-violet)', bg: 'rgba(139,92,246,0.12)' },
}

function SourceBadgeC360({ source }) {
  const meta = SOURCE_META_C360[source] || { label: source || 'Unknown', icon: History, color: 'var(--text-muted)', bg: 'rgba(255,255,255,0.05)' }
  const Icon = meta.icon
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: meta.bg, color: meta.color,
      border: `1px solid ${meta.color}44`, borderRadius: 5, padding: '2px 7px', fontSize: 10, fontWeight: 700, whiteSpace: 'nowrap' }}>
      <Icon size={9} />{meta.label}
    </span>
  )
}

function StatBox({ label, value, color, small }) {
  return (
    <div style={{ flex: 1, minWidth: 100 }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: small ? 13 : 20, fontWeight: 700, color: color || 'var(--text-primary)' }}>{value}</div>
    </div>
  )
}

function RoleBadge({ role }) {
  const s = ROLE_BADGE_COLOR[role] || { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' }
  return (
    <span style={{
      background: s.bg, color: s.color,
      border: `1px solid ${s.color}44`,
      borderRadius: 5, padding: '2px 7px', fontSize: 10, fontWeight: 700,
    }}>
      {role?.replace('_', ' ') || '—'}
    </span>
  )
}

function formatDate(v) {
  if (!v) return '—'
  return new Date(v).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

export default function Customer360Page() {
  const [selectedCustomer, setSelectedCustomer] = useState('CUST-0001')

  const { data: custList } = useQuery({
    queryKey: ['customers-list'],
    queryFn: () => customersApi.list().then(r => r.data),
  })
  const { data: custData } = useQuery({
    queryKey: ['customer-detail', selectedCustomer],
    queryFn: () => customersApi.get(selectedCustomer).then(r => r.data),
    enabled: !!selectedCustomer,
  })
  const { data: arData } = useQuery({
    queryKey: ['customer-ar', selectedCustomer],
    queryFn: () => arApi.list({ customer_id: selectedCustomer }).then(r => r.data),
    enabled: !!selectedCustomer,
  })
  const { data: ordersData } = useQuery({
    queryKey: ['customer-orders', selectedCustomer],
    queryFn: () => ordersApi.list({ customer_id: selectedCustomer, limit: 10 }).then(r => r.data),
    enabled: !!selectedCustomer,
  })
  const { data: fraudData } = useQuery({
    queryKey: ['customer-fraud', selectedCustomer],
    queryFn: () => fraudApi.list({ customer_id: selectedCustomer, limit: 10 }).then(r => r.data),
    enabled: !!selectedCustomer,
  })
  const { data: collectionsData } = useQuery({
    queryKey: ['customer-collections', selectedCustomer],
    queryFn: () => collectionsApi.list({ customer_id: selectedCustomer }).then(r => r.data),
    enabled: !!selectedCustomer,
  })
  const { data: creditData } = useQuery({
    queryKey: ['customer-credit-memos', selectedCustomer],
    queryFn: () => creditMemosApi.list({ customer_id: selectedCustomer }).then(r => r.data),
    enabled: !!selectedCustomer,
  })

  const customers   = custList?.customers || []
  const cust        = custData?.customer || custData || {}
  const arRecords   = arData?.ar_entries || []
  const orders      = ordersData?.orders || []
  const fraudRecords = fraudData?.fraud_records || []
  const collections = collectionsData?.customers || []
  const seg         = collections.find(c => c.customer_id === selectedCustomer)
  const creditMemos = creditData?.credit_memos || []
  const totalCredited = +(creditData?.total_amount_inr || 0)

  const totalOutstanding = arRecords.filter(a => a.payment_status !== 'paid').reduce((s, a) => s + (+(a.outstanding_balance_inr || 0)), 0)
  const overdueCount     = arRecords.filter(a => (a.days_overdue || 0) > 0 && a.payment_status !== 'paid').length
  const fulfilledOrders  = orders.filter(o => ['fulfilled', 'invoiced', 'closed', 'shipped', 'delivered'].includes(o.status)).length
  const fraudCount       = fraudRecords.filter(f => f.fraud_verdict === 'FRAUD').length

  const agingChart = [
    { name: '0-30',  amount: arRecords.filter(a => a.aging_bucket === '0-30'  && a.payment_status !== 'paid').reduce((s, a) => s + (+(a.outstanding_balance_inr || 0)), 0) },
    { name: '31-60', amount: arRecords.filter(a => a.aging_bucket === '31-60' && a.payment_status !== 'paid').reduce((s, a) => s + (+(a.outstanding_balance_inr || 0)), 0) },
    { name: '61-90', amount: arRecords.filter(a => a.aging_bucket === '61-90' && a.payment_status !== 'paid').reduce((s, a) => s + (+(a.outstanding_balance_inr || 0)), 0) },
    { name: '90+',   amount: arRecords.filter(a => a.aging_bucket === '90+'   && a.payment_status !== 'paid').reduce((s, a) => s + (+(a.outstanding_balance_inr || 0)), 0) },
  ]

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Customer 360</h1>
          <p className="page-subtitle">Complete customer profile — credit · AR · orders · fraud · credit history in one view</p>
        </div>
        <div>
          <input
            className="form-input"
            list="customer-search-list"
            style={{ width: 300, fontSize: 13, fontWeight: 600, background: 'var(--surface-1)' }}
            placeholder="Search by customer ID or name..."
            value={selectedCustomer}
            onChange={e => setSelectedCustomer(e.target.value)}
          />
          <datalist id="customer-search-list">
            {customers.map(c => (
              <option key={c.customer_id} value={c.customer_id}>{c.company_name}</option>
            ))}
          </datalist>
        </div>
      </div>

      {/* ── Customer Profile Header ──────────────────────────────────────── */}
      {cust?.customer_id && (
        <div className="card" style={{ marginBottom: 14, borderLeft: `3px solid ${TIER_COLOR[cust.credit_tier] || 'var(--border)'}` }}>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{ width: 52, height: 52, borderRadius: '50%', background: `${TIER_COLOR[cust.credit_tier]}22`, display: 'flex', alignItems: 'center', justifyContent: 'center', border: `2px solid ${TIER_COLOR[cust.credit_tier]}` }}>
                <User size={22} style={{ color: TIER_COLOR[cust.credit_tier] }} />
              </div>
              <div>
                <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary)' }}>{cust.company_name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{cust.contact_name} · {cust.email}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{cust.city}, {cust.state} · {cust.gstin}</div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginLeft: 'auto' }}>
              <StatBox label="Credit Tier"           value={`Tier ${cust.credit_tier || '—'}`}                      color={TIER_COLOR[cust.credit_tier]} />
              <StatBox label="Credit Limit"          value={`₹${((cust.credit_limit_inr || 0) / 100000).toFixed(0)}L`} color="var(--accent-blue)" />
              <StatBox label="Payment Terms"         value={`${cust.payment_terms_days || 30} days`} />
              <StatBox label="Avg DSO"               value={`${cust.avg_dso_days || 0} days`}        color={(cust.avg_dso_days || 0) > 45 ? 'var(--accent-amber)' : 'var(--accent-green)'} />
              <StatBox label="Missed Payments (12m)" value={cust.missed_payments_12m || 0}            color={(cust.missed_payments_12m || 0) > 1 ? 'var(--accent-red)' : 'var(--accent-green)'} />
              {seg && <StatBox label="AI Segment"    value={seg.collection_segment || '—'}            color={SEG_COLOR[seg.collection_segment] || 'var(--text-primary)'} />}
            </div>
          </div>
        </div>
      )}

      {/* ── KPI Strip ───────────────────────────────────────────────────── */}
      <div className="kpi-grid" style={{ marginBottom: 14 }}>
        <div className="kpi-card">
          <div className="kpi-label"><TrendingDown size={10} style={{ display: 'inline' }} /> AR Outstanding</div>
          <div className="kpi-value" style={{ color: totalOutstanding > 0 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
            ₹{(totalOutstanding / 100000).toFixed(1)}L
          </div>
          <div className="kpi-delta">{overdueCount} overdue</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><Package size={10} style={{ display: 'inline' }} /> Total Orders</div>
          <div className="kpi-value">{orders.length}</div>
          <div className="kpi-delta">{fulfilledOrders} fulfilled</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><ShieldOff size={10} style={{ display: 'inline' }} /> Fraud Records</div>
          <div className="kpi-value" style={{ color: fraudCount > 0 ? 'var(--accent-red)' : 'var(--accent-green)' }}>
            {fraudCount}
          </div>
          <div className="kpi-delta">{fraudRecords.length} screened total</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label"><CreditCard size={10} style={{ display: 'inline' }} /> Portal Active</div>
          <div className="kpi-value" style={{ color: cust.portal_active ? 'var(--accent-green)' : 'var(--accent-red)' }}>
            {cust.portal_active ? 'Yes' : 'No'}
          </div>
          <div className="kpi-delta">{cust.industry || '—'}</div>
        </div>
        <div className="kpi-card" style={{ borderColor: 'rgba(139,92,246,0.3)', background: 'rgba(139,92,246,0.05)' }}>
          <div className="kpi-label" style={{ color: 'var(--accent-violet)' }}><History size={10} style={{ display: 'inline' }} /> Total Credited</div>
          <div className="kpi-value" style={{ color: 'var(--accent-violet)' }}>
            ₹{(totalCredited / 100000).toFixed(1)}L
          </div>
          <div className="kpi-delta">{creditMemos.length} memo{creditMemos.length !== 1 ? 's' : ''}</div>
        </div>
      </div>

      {/* ── AR Aging chart + Fraud Screening ────────────────────────────── */}
      <div className="grid-2" style={{ marginBottom: 14 }}>
        <div className="card">
          <div className="card-header">
            <div className="card-title">AR Aging Breakdown</div>
            <span className="badge badge-amber">Outstanding only</span>
          </div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={agingChart} barSize={32}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `₹${(v / 1000).toFixed(0)}K`} />
              <Tooltip formatter={v => [`₹${(+v).toLocaleString('en-IN')}`, 'Outstanding']} />
              <Bar dataKey="amount" name="Outstanding" radius={[4, 4, 0, 0]} fill="var(--accent-amber)" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <div className="card-header"><div className="card-title">Fraud Screening History</div></div>
          {fraudRecords.length === 0 ? (
            <div className="empty-state" style={{ padding: '20px 0' }}>
              <div style={{ fontSize: 13, color: 'var(--accent-green)' }}>✓ No fraud records</div>
            </div>
          ) : (
            <div className="table-wrap"><table>
              <thead><tr><th>Order</th><th>IF Score</th><th>XGB Prob</th><th>Verdict</th></tr></thead>
              <tbody>{fraudRecords.slice(0, 5).map(f => (
                <tr key={f.fraud_id}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-blue)' }}>{f.order_id}</td>
                  <td style={{ fontSize: 11, fontFamily: 'monospace' }}>{(+(f.isolation_forest_score || 0)).toFixed(3)}</td>
                  <td style={{ fontSize: 11, fontFamily: 'monospace' }}>{((+(f.xgboost_fraud_probability || 0)) * 100).toFixed(1)}%</td>
                  <td><span className={`badge ${f.fraud_verdict === 'FRAUD' ? 'badge-red' : 'badge-green'}`}>{f.fraud_verdict}</span></td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </div>
      </div>

      {/* ── Order History ────────────────────────────────────────────────── */}
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-header">
          <div className="card-title">Order History</div>
          <span className="badge badge-blue">{orders.length} orders</span>
        </div>
        {orders.length === 0 ? (
          <div className="empty-state"><div className="empty-title">No orders</div></div>
        ) : (
          <div className="table-wrap"><table>
            <thead><tr>
              <th>Order ID</th><th>SKU</th><th>Amount</th><th>Channel</th><th>Status</th><th>Fraud Score</th><th>Date</th>
            </tr></thead>
            <tbody>{orders.map(o => (
              <tr key={o.order_id}>
                <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-blue)' }}>{o.order_id}</td>
                <td style={{ fontSize: 12 }}>{o.sku_id}</td>
                <td style={{ fontWeight: 600 }}>₹{(+(o.total_amount_inr || 0)).toLocaleString('en-IN')}</td>
                <td><span className="badge badge-gray">{o.channel}</span></td>
                <td><span className={`badge ${['fulfilled', 'approved', 'closed'].includes(o.status) ? 'badge-green' : o.status === 'fraud_review' ? 'badge-red' : 'badge-amber'}`}>{o.status}</span></td>
                <td>{o.fraud_score != null && (
                  <span style={{ fontSize: 11, fontFamily: 'monospace', color: (+o.fraud_score) > 0.7 ? 'var(--accent-red)' : (+o.fraud_score) > 0.4 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                    {((+o.fraud_score) * 100).toFixed(0)}%
                  </span>
                )}</td>
                <td style={{ fontSize: 11, color: 'var(--text-muted)' }}>{o.order_date ? new Date(o.order_date).toLocaleDateString('en-IN') : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      {/* ── AR Ledger (customer-specific) ───────────────────────────────── */}
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="card-header">
          <div className="card-title">AR Ledger</div>
          <span className="badge badge-amber">{arRecords.filter(a => a.payment_status !== 'paid').length} open</span>
        </div>
        {arRecords.length === 0 ? (
          <div className="empty-state"><div className="empty-title">No AR records</div></div>
        ) : (
          <div className="table-wrap"><table>
            <thead><tr>
              <th>AR ID</th><th>Invoice</th><th>Amount</th><th>Outstanding</th><th>Aging</th><th>Days Overdue</th><th>Status</th>
            </tr></thead>
            <tbody>{arRecords.map(a => (
              <tr key={a.ar_id}>
                <td style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-muted)' }}>{a.ar_id}</td>
                <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-cyan)' }}>{a.invoice_id}</td>
                <td>₹{(+(a.amount_inr || 0)).toLocaleString('en-IN')}</td>
                <td style={{ fontWeight: 700, color: (+a.outstanding_balance_inr) > 0 ? 'var(--accent-amber)' : 'var(--accent-green)' }}>
                  ₹{(+(a.outstanding_balance_inr || 0)).toLocaleString('en-IN')}
                </td>
                <td><span className="badge badge-gray">{a.aging_bucket}</span></td>
                <td style={{ color: (+a.days_overdue) > 30 ? 'var(--accent-red)' : 'var(--text-muted)', fontFamily: 'monospace', fontSize: 12 }}>{a.days_overdue || 0}</td>
                <td><span className={`badge ${a.payment_status === 'paid' ? 'badge-green' : a.payment_status === 'overdue' ? 'badge-red' : 'badge-amber'}`}>{a.payment_status}</span></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>

      {/* ── Credit History ───────────────────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <History size={15} color="var(--accent-violet)" />
            Credit &amp; Payment History
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {creditMemos.length > 0 && (
              <span style={{ fontSize: 12, color: 'var(--accent-violet)', fontWeight: 700 }}>
                ₹{totalCredited.toLocaleString('en-IN')} total adjusted
              </span>
            )}
            <span className="badge" style={{ background: 'rgba(139,92,246,0.15)', color: 'var(--accent-violet)', border: '1px solid rgba(139,92,246,0.3)' }}>
              {creditMemos.length} entr{creditMemos.length !== 1 ? 'ies' : 'y'}
            </span>
          </div>
        </div>

        {creditMemos.length === 0 ? (
          <div className="empty-state">
            <History size={32} style={{ opacity: 0.2 }} />
            <div className="empty-title">No credit or payment entries yet</div>
            <div className="empty-text">Entries appear when disputes are resolved, payments are marked received in AR Ledger, or the customer pays via the portal.</div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Source</th>
                <th>Memo ID</th>
                <th>Date</th>
                <th>Invoice</th>
                <th>Amount</th>
                <th>Balance Before → After</th>
                <th>Reason / Note</th>
                <th>Ref</th>
                <th>Actioned By</th>
              </tr></thead>
              <tbody>
                {creditMemos.map(m => (
                  <tr key={m.memo_id}>
                    <td><SourceBadgeC360 source={m.source || 'dispute_resolution'} /></td>
                    <td style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--accent-violet)' }}>{m.memo_id}</td>
                    <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{formatDate(m.created_at)}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-blue)' }}>{m.invoice_id || '—'}</td>
                    <td style={{ fontWeight: 700, color: 'var(--accent-green)' }}>
                      ₹{(+(m.amount_inr || 0)).toLocaleString('en-IN')}
                    </td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                        <span style={{ color: 'var(--accent-amber)' }}>₹{(+(m.balance_before_inr || 0)).toLocaleString('en-IN')}</span>
                        <ArrowDownRight size={12} color="var(--accent-green)" />
                        <span style={{ color: +(m.balance_after_inr || 0) === 0 ? 'var(--accent-green)' : 'var(--accent-amber)', fontWeight: 600 }}>
                          ₹{(+(m.balance_after_inr || 0)).toLocaleString('en-IN')}
                        </span>
                        {+(m.balance_after_inr || 0) === 0 && <span className="badge badge-green" style={{ fontSize: 9, padding: '1px 5px' }}>PAID</span>}
                      </div>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--text-secondary)', maxWidth: 180 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.reason}>
                        {m.reason || '—'}
                      </div>
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-muted)', maxWidth: 110 }}>
                      <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.payment_ref}>
                        {m.payment_ref || '—'}
                      </div>
                    </td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{m.approved_by}</span>
                        <RoleBadge role={m.approved_by_role} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
