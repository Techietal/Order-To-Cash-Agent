import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, RefreshCw, CheckCircle, PackageCheck } from 'lucide-react'
import { purchaseOrdersApi } from '../lib/api'

const emptyLine = { sku_id: '', quantity_ordered: 1, unit_cost_inr: 0 }

export default function PurchaseOrdersPage() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ supplier_id: '', expected_arrival_date: '', items: [{ ...emptyLine }] })
  const [receive, setReceive] = useState(null)
  const { data, isLoading, error, refetch } = useQuery({ queryKey: ['purchase-orders'], queryFn: () => purchaseOrdersApi.list({ limit: 100 }).then(r => r.data) })
  const createMut = useMutation({ mutationFn: purchaseOrdersApi.create, onSuccess: () => { setShowCreate(false); setForm({ supplier_id: '', expected_arrival_date: '', items: [{ ...emptyLine }] }); qc.invalidateQueries({ queryKey: ['purchase-orders'] }) } })
  const confirmMut = useMutation({ mutationFn: purchaseOrdersApi.confirm, onSuccess: () => qc.invalidateQueries({ queryKey: ['purchase-orders'] }) })
  const receiveMut = useMutation({ mutationFn: ({ poId, payload }) => purchaseOrdersApi.receive(poId, payload), onSuccess: () => { setReceive(null); qc.invalidateQueries({ queryKey: ['purchase-orders'] }); qc.invalidateQueries({ queryKey: ['inventory-dashboard-summary'] }) } })

  const orders = data?.purchase_orders || []
  const setLine = (idx, key, value) => setForm(f => ({ ...f, items: f.items.map((l, i) => i === idx ? { ...l, [key]: value } : l) }))
  const addLine = () => setForm(f => ({ ...f, items: [...f.items, { ...emptyLine }] }))

  return (
    <div className="page-content animate-fade">
      <div className="page-header"><div className="page-header-left"><h1 className="page-title">Purchase Orders</h1><p className="page-subtitle">Draft, confirm, and receive replenishment POs</p></div><div className="page-actions"><button className="btn btn-secondary btn-sm" onClick={() => refetch()}><RefreshCw size={13} /> Refresh</button><button className="btn btn-primary btn-sm" onClick={() => setShowCreate(v => !v)}><Plus size={13} /> New PO</button></div></div>
      {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>Could not load purchase orders.</div>}
      {createMut.isError && <div className="alert alert-error" style={{ marginBottom: 16 }}>{createMut.error?.response?.data?.detail || 'Create failed'}</div>}
      {confirmMut.isError && <div className="alert alert-error" style={{ marginBottom: 16 }}>{confirmMut.error?.response?.data?.detail || 'Confirm failed'}</div>}
      {receiveMut.isError && <div className="alert alert-error" style={{ marginBottom: 16 }}>{receiveMut.error?.response?.data?.detail || 'Receive failed'}</div>}

      {showCreate && <div className="card animate-slide" style={{ marginBottom: 16 }}><div className="card-header"><div className="card-title">Create Draft PO</div></div>
        <div className="grid-2"><div className="form-group"><label className="form-label">Supplier ID</label><input className="form-input" value={form.supplier_id} onChange={e => setForm(f => ({ ...f, supplier_id: e.target.value }))} /></div><div className="form-group"><label className="form-label">Expected arrival</label><input className="form-input" type="date" value={form.expected_arrival_date} onChange={e => setForm(f => ({ ...f, expected_arrival_date: e.target.value }))} /></div></div>
        {form.items.map((line, idx) => <div key={idx} className="grid-3"><div className="form-group"><label className="form-label">SKU</label><input className="form-input" value={line.sku_id} onChange={e => setLine(idx, 'sku_id', e.target.value)} /></div><div className="form-group"><label className="form-label">Quantity</label><input className="form-input" type="number" min="1" value={line.quantity_ordered} onChange={e => setLine(idx, 'quantity_ordered', +e.target.value)} /></div><div className="form-group"><label className="form-label">Unit cost</label><input className="form-input" type="number" value={line.unit_cost_inr} onChange={e => setLine(idx, 'unit_cost_inr', +e.target.value)} /></div></div>)}
        <div style={{ display: 'flex', gap: 8 }}><button className="btn btn-secondary btn-sm" onClick={addLine}>Add line</button><button className="btn btn-primary btn-sm" onClick={() => createMut.mutate(form)} disabled={createMut.isPending}>Create PO</button></div>
      </div>}

      {receive && <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setReceive(null)}><div className="card" style={{ width: 'min(720px, 96vw)' }}><div className="card-header"><div className="card-title">Receive {receive.po_id}</div><button className="btn btn-secondary btn-sm" onClick={() => setReceive(null)}>Close</button></div>
        {(receive.items || []).map((line, idx) => <div key={line.sku_id} className="grid-3"><div className="form-group"><label className="form-label">SKU</label><input className="form-input" value={line.sku_id} disabled /></div><div className="form-group"><label className="form-label">Open qty</label><input className="form-input" value={(line.quantity_ordered || 0) - (line.quantity_received || 0)} disabled /></div><div className="form-group"><label className="form-label">Receive qty</label><input className="form-input" type="number" min="0" value={line.quantity_to_receive || 0} onChange={e => setReceive(po => ({ ...po, items: po.items.map((l, i) => i === idx ? { ...l, quantity_to_receive: +e.target.value } : l) }))} /></div></div>)}
        <button className="btn btn-primary" onClick={() => receiveMut.mutate({ poId: receive.po_id, payload: { idempotency_key: `recv-${Date.now()}`, items: receive.items.filter(l => (l.quantity_to_receive || 0) > 0).map(l => ({ sku_id: l.sku_id, quantity_received: l.quantity_to_receive })) } })}><PackageCheck size={14} /> Receive</button>
      </div></div>}

      <div className="card">{isLoading ? <div className="loading-wrap"><div className="spinner" /></div> : <div className="table-wrap"><table><thead><tr><th>PO</th><th>Supplier</th><th>Status</th><th>Expected</th><th>Lines</th><th>Actions</th></tr></thead><tbody>
        {orders.length === 0 ? <tr><td colSpan={6}><div className="empty-state"><div className="empty-title">No purchase orders</div></div></td></tr> : orders.map(po => <tr key={po.po_id}><td style={{ fontFamily: 'monospace', color: 'var(--accent-blue)' }}>{po.po_id}</td><td>{po.supplier_id || '—'}</td><td><span className="badge badge-gray">{po.status}</span></td><td>{po.expected_arrival_date ? new Date(po.expected_arrival_date).toLocaleDateString() : '—'}</td><td>{(po.items || []).map(i => <div key={i.sku_id} style={{ fontSize: 12 }}>{i.sku_id}: {i.quantity_received}/{i.quantity_ordered}</div>)}</td><td><div style={{ display: 'flex', gap: 6 }}>{po.status === 'draft' && <button className="btn btn-success btn-sm" onClick={() => confirmMut.mutate(po.po_id)}><CheckCircle size={12} /> Confirm</button>}{['confirmed', 'partially_received'].includes(po.status) && <button className="btn btn-primary btn-sm" onClick={() => setReceive({ ...po, items: (po.items || []).map(i => ({ ...i, quantity_to_receive: Math.max(0, (i.quantity_ordered || 0) - (i.quantity_received || 0)) })) })}>Receive</button>}</div></td></tr>)}
      </tbody></table></div>}</div>
    </div>
  )
}
