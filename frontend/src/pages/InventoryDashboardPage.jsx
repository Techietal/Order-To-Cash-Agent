import React from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Boxes, AlertTriangle, ClipboardList, PackageCheck, RefreshCw, ShoppingBag, Truck } from 'lucide-react'
import { inventoryApi } from '../lib/api'

function Kpi({ label, value, icon: Icon, color }) {
  return (
    <div className="kpi-card">
      <div className="kpi-accent" style={{ background: color }} />
      <div className="kpi-icon" style={{ background: `${color}20` }}><Icon size={17} style={{ color }} /></div>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{typeof value === 'number' ? value.toLocaleString('en-IN') : value ?? '—'}</div>
    </div>
  )
}

export default function InventoryDashboardPage() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['inventory-dashboard-summary'],
    queryFn: () => inventoryApi.dashboardSummary().then(r => r.data),
    refetchInterval: 60000,
  })
  const refreshMut = useMutation({
    mutationFn: () => inventoryApi.refreshForecast({ days: 30 }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['inventory-dashboard-summary'] }),
  })

  if (isLoading) return <div className="page-content"><div className="loading-wrap"><div className="spinner" /><span className="loading-text">Loading inventory…</span></div></div>

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Inventory Dashboard</h1>
          <p className="page-subtitle">Stock position, backorders, incoming POs, and ledger activity</p>
        </div>
        <div className="page-actions">
          <Link className="btn btn-secondary btn-sm" to="/products"><ShoppingBag size={13} /> View Products</Link>
          <Link className="btn btn-secondary btn-sm" to="/purchase-orders"><Truck size={13} /> Purchase Orders</Link>
          <button className="btn btn-primary btn-sm" onClick={() => refreshMut.mutate()} disabled={refreshMut.isPending}>
            <RefreshCw size={13} /> {refreshMut.isPending ? 'Refreshing…' : 'Refresh Forecasts'}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>Could not load inventory dashboard.</div>}
      {refreshMut.isSuccess && <div className="alert alert-success" style={{ marginBottom: 16 }}>Forecast refresh queued/completed.</div>}

      <div className="kpi-grid">
        <Kpi label="Total SKUs" value={data?.total_skus || 0} icon={Boxes} color="var(--accent-blue)" />
        <Kpi label="Urgent" value={data?.urgent_count || 0} icon={AlertTriangle} color="var(--accent-red)" />
        <Kpi label="Reorder" value={data?.reorder_count || 0} icon={ClipboardList} color="var(--accent-amber)" />
        <Kpi label="Backordered Orders" value={data?.backordered_orders_count || 0} icon={PackageCheck} color="var(--accent-violet)" />
        <Kpi label="Incoming POs" value={data?.incoming_pos_count || 0} icon={Truck} color="var(--accent-cyan)" />
        <Kpi label="Available" value={data?.total_available_stock || 0} icon={Boxes} color="var(--accent-green)" />
        <Kpi label="Reserved" value={data?.total_reserved_stock || 0} icon={PackageCheck} color="var(--accent-amber)" />
        <Kpi label="Incoming Stock" value={data?.total_incoming_stock || 0} icon={Truck} color="var(--accent-blue)" />
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-header"><div className="card-title">Top Low-Stock SKUs</div></div>
          <div className="table-wrap"><table><thead><tr><th>SKU</th><th>Product</th><th>Available</th><th>Reserved</th><th>Incoming</th></tr></thead><tbody>
            {(data?.top_low_stock || []).length === 0 ? <tr><td colSpan={5}>No low-stock data.</td></tr> : data.top_low_stock.map(p => (
              <tr key={p.sku_id}><td><Link to={`/products/${p.sku_id}`}>{p.sku_id}</Link></td><td>{p.product_name}</td><td>{p.available_stock}</td><td>{p.reserved_stock}</td><td>{p.incoming_stock}</td></tr>
            ))}
          </tbody></table></div>
        </div>
        <div className="card">
          <div className="card-header"><div className="card-title">Top Backordered SKUs</div></div>
          <div className="table-wrap"><table><thead><tr><th>SKU</th><th>Backordered Qty</th><th>Orders</th></tr></thead><tbody>
            {(data?.top_backordered || []).length === 0 ? <tr><td colSpan={3}>No active backorders.</td></tr> : data.top_backordered.map(p => (
              <tr key={p.sku_id}><td>{p.sku_id}</td><td>{p.quantity_backordered}</td><td>{p.order_count}</td></tr>
            ))}
          </tbody></table></div>
        </div>
      </div>

      <div className="card">
        <div className="card-header"><div className="card-title">Recent Inventory Transactions</div></div>
        <div className="table-wrap"><table><thead><tr><th>Txn</th><th>SKU</th><th>Type</th><th>Field</th><th>Delta</th><th>Balance</th><th>When</th></tr></thead><tbody>
          {(data?.recent_inventory_transactions || []).length === 0 ? <tr><td colSpan={7}>No transactions yet.</td></tr> : data.recent_inventory_transactions.map(t => (
            <tr key={t.txn_id}><td>{t.txn_id}</td><td>{t.sku_id}</td><td><span className="badge badge-gray">{t.txn_type}</span></td><td>{t.field_affected}</td><td>{t.quantity_delta}</td><td>{t.balance_after}</td><td>{t.created_at ? new Date(t.created_at).toLocaleString() : '—'}</td></tr>
          ))}
        </tbody></table></div>
      </div>
    </div>
  )
}
