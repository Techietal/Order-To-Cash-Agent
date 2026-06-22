import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { portalApi } from '../lib/api'
import { Globe } from 'lucide-react'

export default function CustomerPortalPage() {
  const [cid, setCid] = useState('CUST-0001')
  const [sub, setSub] = useState('CUST-0001')

  const { data: invoices } = useQuery({
    queryKey: ['portal-inv', sub],
    queryFn: () => portalApi.invoices(sub).then(r => r.data),
    enabled: !!sub,
  })
  const { data: orders } = useQuery({
    queryKey: ['portal-ord', sub],
    queryFn: () => portalApi.orders(sub).then(r => r.data),
    enabled: !!sub,
  })

  const invList = invoices?.invoices || []
  const ordList = orders?.orders || []

  const statusColor = (s) => {
    if (s === 'paid') return 'badge-green'
    if (s === 'overdue') return 'badge-red'
    return 'badge-amber'
  }

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Customer Self-Service Portal</h1>
          <p className="page-subtitle">B2B customers view their own orders and invoices</p>
        </div>
        <span className="badge badge-blue"><Globe size={11} /> Portal Preview</span>
      </div>

      <div className="card" style={{ marginBottom: 16, maxWidth: 480 }}>
        <div className="card-title" style={{ marginBottom: 12 }}>Customer Lookup</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="form-input"
            placeholder="Customer ID (e.g. CUST-0001)"
            value={cid}
            onChange={e => setCid(e.target.value)}
          />
          <button className="btn btn-primary" onClick={() => setSub(cid)}>View</button>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-header">
            <div className="card-title">My Orders</div>
            <span className="badge badge-blue">{ordList.length}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Order ID</th><th>Date</th><th>Amount</th><th>Status</th></tr></thead>
              <tbody>
                {ordList.length === 0 ? (
                  <tr><td colSpan={4}>
                    <div className="empty-state" style={{ padding: '20px 0' }}>
                      <div className="empty-title">No orders</div>
                    </div>
                  </td></tr>
                ) : ordList.map(o => (
                  <tr key={o.order_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-blue)' }}>{o.order_id}</td>
                    <td style={{ fontSize: 11 }}>{new Date(o.order_date).toLocaleDateString()}</td>
                    <td>₹{(+o.total_amount_inr || 0).toLocaleString('en-IN')}</td>
                    <td><span className="badge badge-gray">{o.status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <div className="card-title">My Invoices</div>
            <span className="badge badge-cyan">{invList.length}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Invoice</th><th>Due</th><th>Total</th><th>Status</th></tr></thead>
              <tbody>
                {invList.length === 0 ? (
                  <tr><td colSpan={4}>
                    <div className="empty-state" style={{ padding: '20px 0' }}>
                      <div className="empty-title">No invoices</div>
                    </div>
                  </td></tr>
                ) : invList.map(inv => (
                  <tr key={inv.invoice_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-cyan)' }}>{inv.invoice_id}</td>
                    <td style={{ fontSize: 11 }}>{new Date(inv.due_date).toLocaleDateString()}</td>
                    <td>₹{(+inv.total_amount_inr || 0).toLocaleString('en-IN')}</td>
                    <td><span className={'badge ' + statusColor(inv.payment_status)}>{inv.payment_status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
