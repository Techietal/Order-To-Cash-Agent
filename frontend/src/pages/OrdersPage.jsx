import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, RefreshCw, Mail, Activity } from 'lucide-react'
import { ordersApi } from '../lib/api'
import { ActionGuard } from '../components/RoleGuard'
import OrderDetailModal from '../components/OrderDetailModal'

function statusBadge(s) {
  const m = {
    pending_credit: 'badge-amber', credit_approved: 'badge-green',
    fraud_review: 'badge-red', fraud_cleared: 'badge-green',
    in_fulfillment: 'badge-blue', shipped: 'badge-cyan',
    delivered: 'badge-green', invoiced: 'badge-violet', approved: 'badge-green',
    partially_reserved: 'badge-amber', backordered: 'badge-violet', fulfilled: 'badge-green',
    closed: 'badge-gray', cancelled: 'badge-red', hitl_required: 'badge-amber'
  }
  return `badge ${m[s] || 'badge-gray'}`
}

export default function OrdersPage() {
  const [search, setSearch]           = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [showNew, setShowNew]         = useState(false)
  const [showEmail, setShowEmail]     = useState(false)
  const [form, setForm]               = useState({ customer_id: '', sku_id: '', quantity: 1, unit_price_inr: '', channel: 'api' })
  const [emailText, setEmailText]     = useState('')
  const [ingestResult, setIngestResult] = useState(null)
  const [trackOrderId, setTrackOrderId] = useState(null)   // controls modal
  const qc = useQueryClient()

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['orders', statusFilter],
    queryFn: () => ordersApi.list({ status: statusFilter || undefined, limit: 100 }).then(r => r.data),
    refetchInterval: 30000,
  })
  const { data: summary } = useQuery({
    queryKey: ['orders-summary'],
    queryFn: () => ordersApi.summary().then(r => r.data),
  })
  const createMut = useMutation({
    mutationFn: (d) => ordersApi.create(d),
    onSuccess: () => { setShowNew(false); qc.invalidateQueries(['orders']); qc.invalidateQueries(['orders-summary']) }
  })
  const ingestMut = useMutation({
    mutationFn: (text) => ordersApi.ingest({ email_text: text }).then(r => r.data),
    onSuccess: (data) => { setIngestResult(data); qc.invalidateQueries(['orders']) }
  })

  const orders   = data?.orders || []
  const filtered = orders.filter(o =>
    !search ||
    o.order_id?.toLowerCase().includes(search.toLowerCase()) ||
    (o.customer_id || '').toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="page-content animate-fade">
      {/* Order Lifecycle Modal */}
      {trackOrderId && (
        <OrderDetailModal orderId={trackOrderId} onClose={() => setTrackOrderId(null)} />
      )}

      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Orders</h1>
          <p className="page-subtitle">Agent 1 — GLiNER NER · Isolation Forest · Policy Engine</p>
        </div>
        <div className="page-actions">
          <button className="btn btn-secondary btn-sm" onClick={() => refetch()}><RefreshCw size={13} /> Refresh</button>
          {/* Email Ingest — admin only */}
          <ActionGuard allowed={['admin']}>
            <button className="btn btn-secondary btn-sm" onClick={() => setShowEmail(!showEmail)}><Mail size={13} /> Ingest Email</button>
          </ActionGuard>
          {/* New Order — admin only */}
          <ActionGuard allowed={['admin']}>
            <button className="btn btn-primary btn-sm" onClick={() => setShowNew(!showNew)}><Plus size={13} /> New Order</button>
          </ActionGuard>
        </div>
      </div>

      {/* Summary strip */}
      {summary && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
          {[
            ['Total', summary.total_orders, 'badge-blue'],
            ['Pending Credit', summary.pending_credit, 'badge-amber'],
            ['Fraud Review', summary.fraud_review, 'badge-red'],
            ['HITL', summary.hitl_required, 'badge-amber'],
          ].map(([l, v, b]) => (
            <div key={l} className="card" style={{ padding: '12px 18px', display: 'flex', gap: 10, alignItems: 'center', flex: '0 0 auto' }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{l}</span>
              <span className={`badge ${b}`}>{v}</span>
            </div>
          ))}
          <div className="card" style={{ padding: '12px 18px', flex: '0 0 auto' }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Total Value</span>
            <span style={{ marginLeft: 8, fontWeight: 700, color: 'var(--text-primary)', fontSize: 13 }}>
              ₹{((summary.total_value_inr || 0) / 100000).toFixed(1)}L
            </span>
          </div>
        </div>
      )}

      {/* Email Ingest — admin only */}
      <ActionGuard allowed={['admin']}>
        {showEmail && (
          <div className="card animate-slide" style={{ marginBottom: 16 }}>
            <div className="card-header">
              <div className="card-title">Email Order Ingest (Agent 1)</div>
              <span className="badge badge-violet">GLiNER NER</span>
            </div>
            <div className="alert alert-info" style={{ marginBottom: 12 }}>
              Paste a raw order email. GLiNER extracts entities (SKU, qty, customer, delivery date) using zero-shot NER — no training needed.
            </div>
            <textarea className="form-input" rows={5} placeholder="Paste order email here..." value={emailText} onChange={e => setEmailText(e.target.value)} />
            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button className="btn btn-primary" onClick={() => ingestMut.mutate(emailText)} disabled={!emailText || ingestMut.isPending}>
                {ingestMut.isPending ? 'Processing...' : 'Ingest & Parse'}
              </button>
              <button className="btn btn-secondary" onClick={() => { setShowEmail(false); setIngestResult(null) }}>Cancel</button>
            </div>
            {ingestResult && (
              <div className="alert alert-success" style={{ marginTop: 12 }}>
                <div><strong>Order ID:</strong> {ingestResult.order_id} · <strong>Status:</strong> {ingestResult.status}</div>
                <div style={{ marginTop: 4, fontSize: 11 }}>Fraud Score: {ingestResult.fraud_score?.toFixed(3)} · HITL: {ingestResult.hitl_required ? 'Yes' : 'No'}</div>
                {ingestResult.pipeline_events?.map((e, i) => <div key={i} style={{ fontSize: 11, marginTop: 2 }}>→ {e}</div>)}
              </div>
            )}
          </div>
        )}
      </ActionGuard>

      {/* New Order Form — admin only */}
      <ActionGuard allowed={['admin']}>
        {showNew && (
          <div className="card animate-slide" style={{ marginBottom: 16 }}>
            <div className="card-header"><div className="card-title">Create New Order</div></div>
            <div className="grid-3">
              {[
                ['Customer ID', 'customer_id', 'text', 'CUST-0001'],
                ['SKU ID', 'sku_id', 'text', 'SKU-001'],
                ['Quantity', 'quantity', 'number', '1'],
                ['Unit Price (INR)', 'unit_price_inr', 'number', ''],
              ].map(([l, k, t, ph]) => (
                <div className="form-group" key={k}>
                  <label className="form-label">{l}</label>
                  <input className="form-input" type={t} placeholder={ph} value={form[k]} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} />
                </div>
              ))}
              <div className="form-group">
                <label className="form-label">Channel</label>
                <select className="form-input" value={form.channel} onChange={e => setForm(f => ({ ...f, channel: e.target.value }))}>
                  {['api', 'email', 'edi', 'portal', 'csv_upload'].map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-primary" onClick={() => createMut.mutate({ ...form, quantity: +form.quantity, unit_price_inr: +form.unit_price_inr })} disabled={createMut.isPending}>
                {createMut.isPending ? 'Submitting...' : 'Submit Order'}
              </button>
              <button className="btn btn-secondary" onClick={() => setShowNew(false)}>Cancel</button>
            </div>
            {createMut.isSuccess && <div className="alert alert-success" style={{ marginTop: 12 }}>Order created: {createMut.data?.data?.order_id}</div>}
            {createMut.isError   && <div className="alert alert-error"   style={{ marginTop: 12 }}>Error: {createMut.error?.message}</div>}
          </div>
        )}
      </ActionGuard>

      {/* Table */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flex: 1 }}>
            <div className="search-wrap" style={{ flex: 1, maxWidth: 320 }}>
              <Search size={13} className="search-icon" />
              <input className="form-input" placeholder="Search orders..." value={search} onChange={e => setSearch(e.target.value)} />
            </div>
            <select className="form-input" style={{ width: 'auto' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
              <option value="">All Statuses</option>
              {['pending_credit', 'approved', 'partially_reserved', 'backordered', 'fulfilled', 'fraud_review', 'in_fulfillment', 'invoiced', 'closed', 'cancelled'].map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        {isLoading ? (
          <div className="loading-wrap"><div className="spinner" /><span className="loading-text">Loading orders…</span></div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Order ID</th><th>Customer</th><th>SKU</th><th>Qty</th><th>Amount</th>
                <th>Channel</th><th>Status</th><th>Fraud Score</th><th>HITL</th><th>Date</th>
                <th></th>
              </tr></thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={11}>
                    <div className="empty-state">
                      <div className="empty-icon">📦</div>
                      <div className="empty-title">No orders found</div>
                      <div className="empty-text">Submit an order via API or email ingest to see it here</div>
                    </div>
                  </td></tr>
                ) : filtered.map(o => (
                  <tr key={o.order_id}>
                    <td><span style={{ fontFamily: 'monospace', color: 'var(--accent-blue)', fontSize: 12 }}>{o.order_id}</span></td>
                    <td style={{ color: 'var(--text-primary)' }}>{o.customer_id}</td>
                    <td>{o.sku_id}</td>
                    <td>{o.quantity}</td>
                    <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>₹{(+o.total_amount_inr || 0).toLocaleString('en-IN')}</td>
                    <td><span className="badge badge-gray">{o.channel}</span></td>
                    <td><span className={statusBadge(o.status)}>{o.status}</span></td>
                    <td>
                      {o.fraud_score != null && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <div style={{ width: 36, height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                            <div style={{
                              width: `${(o.fraud_score * 100).toFixed(0)}%`, height: '100%', borderRadius: 2,
                              background: o.fraud_score > 0.7 ? 'var(--accent-red)' : o.fraud_score > 0.4 ? 'var(--accent-amber)' : 'var(--accent-green)'
                            }} />
                          </div>
                          <span style={{ fontSize: 11 }}>{(o.fraud_score * 100).toFixed(0)}%</span>
                        </div>
                      )}
                    </td>
                    <td>{o.hitl_required ? <span className="badge badge-amber">⚠ Yes</span> : <span className="badge badge-gray">No</span>}</td>
                    <td style={{ fontSize: 11 }}>{new Date(o.created_at).toLocaleDateString()}</td>
                    {/* Track button — opens OrderDetailModal */}
                    <td>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => setTrackOrderId(o.order_id)}
                        style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 9px', fontSize: 11 }}
                        title="View lifecycle & fraud detail"
                      >
                        <Activity size={11} /> Track
                      </button>
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
