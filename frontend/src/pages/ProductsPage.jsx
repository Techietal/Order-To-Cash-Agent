import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search, RefreshCw } from 'lucide-react'
import { productsApi } from '../lib/api'

function statusClass(status) {
  return status === 'URGENT' ? 'badge badge-red' : status === 'REORDER' ? 'badge badge-amber' : 'badge badge-green'
}

export default function ProductsPage() {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')
  const [reorderStatus, setReorderStatus] = useState('')
  const params = { search: search || undefined, category: category || undefined, reorder_status: reorderStatus || undefined, limit: 200 }
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['products', params],
    queryFn: () => productsApi.list(params).then(r => r.data),
  })
  const products = data?.products || []
  const categories = [...new Set(products.map(p => p.category).filter(Boolean))]

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left"><h1 className="page-title">Products</h1><p className="page-subtitle">Read-only product stock summary</p></div>
        <button className="btn btn-secondary btn-sm" onClick={() => refetch()}><RefreshCw size={13} /> Refresh</button>
      </div>
      {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>Could not load products.</div>}
      <div className="card">
        <div className="card-header" style={{ gap: 8, flexWrap: 'wrap' }}>
          <div className="search-wrap" style={{ width: 320 }}><Search className="search-icon" size={13} /><input className="form-input" placeholder="Search SKU or product..." value={search} onChange={e => setSearch(e.target.value)} /></div>
          <select className="form-input" style={{ width: 180 }} value={category} onChange={e => setCategory(e.target.value)}><option value="">All categories</option>{categories.map(c => <option key={c} value={c}>{c}</option>)}</select>
          <select className="form-input" style={{ width: 180 }} value={reorderStatus} onChange={e => setReorderStatus(e.target.value)}><option value="">All statuses</option><option>URGENT</option><option>REORDER</option><option>OK</option></select>
        </div>
        {isLoading ? <div className="loading-wrap"><div className="spinner" /></div> : (
          <div className="table-wrap"><table><thead><tr><th>SKU</th><th>Product</th><th>Category</th><th>Available</th><th>On Hand</th><th>Reserved</th><th>Incoming</th><th>Reorder Status</th><th>Lead Time</th></tr></thead><tbody>
            {products.length === 0 ? <tr><td colSpan={9}><div className="empty-state"><div className="empty-title">No products found</div></div></td></tr> : products.map(p => (
              <tr key={p.sku_id}>
                <td><Link style={{ fontFamily: 'monospace', color: 'var(--accent-blue)' }} to={`/products/${p.sku_id}`}>{p.sku_id}</Link></td>
                <td>{p.product_name}</td><td>{p.category}</td><td>{p.available_stock}</td><td>{p.stock_on_hand}</td><td>{p.reserved_stock}</td><td>{p.incoming_stock}</td><td><span className={statusClass(p.reorder_status)}>{p.reorder_status}</span></td><td>{p.lead_time_days || 0}d</td>
              </tr>
            ))}
          </tbody></table></div>
        )}
      </div>
    </div>
  )
}
