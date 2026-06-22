import React from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Truck } from 'lucide-react'
import { inventoryApi, productsApi } from '../lib/api'

function Card({ label, value, tone = 'var(--accent-blue)' }) {
  return <div className="card" style={{ padding: 16 }}><div className="kpi-label">{label}</div><div style={{ fontSize: 24, fontWeight: 800, color: tone }}>{value ?? '—'}</div></div>
}

export default function ProductDetailPage() {
  const { skuId } = useParams()
  const { data: product, isLoading, error } = useQuery({ queryKey: ['product', skuId], queryFn: () => productsApi.get(skuId).then(r => r.data), enabled: !!skuId })
  const { data: forecast } = useQuery({ queryKey: ['inventory-forecast', skuId], queryFn: () => inventoryApi.forecast(skuId, { days: 30 }).then(r => r.data), enabled: !!skuId })
  const { data: txns } = useQuery({ queryKey: ['inventory-transactions', skuId], queryFn: () => inventoryApi.transactions({ sku_id: skuId, limit: 20 }).then(r => r.data), enabled: !!skuId })

  if (isLoading) return <div className="page-content"><div className="loading-wrap"><div className="spinner" /></div></div>

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left"><Link to="/products" className="btn btn-secondary btn-sm" style={{ marginBottom: 10 }}><ArrowLeft size={13} /> Products</Link><h1 className="page-title">{skuId}</h1><p className="page-subtitle">{product?.product_name || 'Product detail'}</p></div>
        <Link to="/purchase-orders" className="btn btn-primary btn-sm"><Truck size={13} /> Purchase Orders</Link>
      </div>
      {error && <div className="alert alert-error">Could not load product.</div>}
      {product && <>
        <div className="grid-4" style={{ marginBottom: 16 }}>
          <Card label="Available" value={product.available_stock} tone="var(--accent-green)" />
          <Card label="On Hand" value={product.stock_on_hand} />
          <Card label="Reserved" value={product.reserved_stock} tone="var(--accent-amber)" />
          <Card label="Incoming" value={product.incoming_stock} tone="var(--accent-cyan)" />
        </div>
        <div className="grid-2" style={{ marginBottom: 16 }}>
          <div className="card"><div className="card-header"><div><div className="card-title">Product & Stock Summary</div><div className="card-subtitle">Category {product.category || '—'} · {product.unit_of_measure || 'unit'}</div></div><span className={`badge ${product.reorder_status === 'URGENT' ? 'badge-red' : product.reorder_status === 'REORDER' ? 'badge-amber' : 'badge-green'}`}>{product.reorder_status}</span></div>
            <div className="stat-row"><span className="stat-label">Base price</span><span className="stat-val">₹{Number(product.base_price_inr || 0).toLocaleString('en-IN')}</span></div>
            <div className="stat-row"><span className="stat-label">Reorder level</span><span className="stat-val">{product.reorder_level}</span></div>
            <div className="stat-row"><span className="stat-label">Safety stock</span><span className="stat-val">{product.safety_stock}</span></div>
            <div className="stat-row"><span className="stat-label">Lead time</span><span className="stat-val">{product.lead_time_days || 0} days</span></div>
          </div>
          <div className="card"><div className="card-header"><div className="card-title">Forecast Summary</div>{forecast?.reorder_needed && <span className="badge badge-amber">Reorder suggested</span>}</div>
            <div className="stat-row"><span className="stat-label">Projected demand</span><span className="stat-val">{Math.round(forecast?.projected_30d_demand || 0)}</span></div>
            <div className="stat-row"><span className="stat-label">Avg daily demand</span><span className="stat-val">{(forecast?.average_daily_demand || 0).toFixed(1)}</span></div>
            <div className="stat-row"><span className="stat-label">Depletion date</span><span className="stat-val">{forecast?.depletion_date || '—'}</span></div>
            <div className="stat-row"><span className="stat-label">Recommended reorder qty</span><span className="stat-val">{Math.ceil(forecast?.recommended_reorder_qty || 0)}</span></div>
          </div>
        </div>
        <div className="grid-2">
          <div className="card"><div className="card-header"><div className="card-title">Incoming PO Lines</div></div><div className="table-wrap"><table><thead><tr><th>PO</th><th>Status</th><th>ETA</th><th>Remaining</th></tr></thead><tbody>{(product.incoming_po_lines || []).length === 0 ? <tr><td colSpan={4}>No open incoming lines.</td></tr> : product.incoming_po_lines.map(l => <tr key={`${l.po_id}-${l.sku_id}`}><td>{l.po_id}</td><td>{l.status}</td><td>{l.expected_arrival_date ? new Date(l.expected_arrival_date).toLocaleDateString() : '—'}</td><td>{l.remaining_incoming}</td></tr>)}</tbody></table></div></div>
          <div className="card"><div className="card-header"><div className="card-title">Recent Transactions</div></div><div className="table-wrap"><table><thead><tr><th>Type</th><th>Delta</th><th>Field</th><th>When</th></tr></thead><tbody>{(txns?.transactions || product.recent_transactions || []).length === 0 ? <tr><td colSpan={4}>No recent transactions.</td></tr> : (txns?.transactions || product.recent_transactions || []).map(t => <tr key={t.txn_id}><td>{t.txn_type}</td><td>{t.quantity_delta}</td><td>{t.field_affected}</td><td>{t.created_at ? new Date(t.created_at).toLocaleDateString() : '—'}</td></tr>)}</tbody></table></div></div>
        </div>
      </>}
    </div>
  )
}
