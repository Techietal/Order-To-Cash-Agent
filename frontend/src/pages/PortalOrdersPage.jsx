import React, { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { portalApi } from '../lib/api'
import { RotateCcw, Edit3, CheckCircle, Clock, AlertCircle, Package } from 'lucide-react'

const STATUS_COLOR = {
  pending_credit: ['#f59e0b', '#fffbeb'],
  approved: ['#10b981', '#f0fdf4'],
  fulfilled: ['#3b82f6', '#eff6ff'],
  partially_reserved: ['#f59e0b', '#fffbeb'],
  backordered: ['#8b5cf6', '#f5f3ff'],
  cancelled: ['#ef4444', '#fef2f2'],
  fraud_review: ['#ef4444', '#fef2f2'],
  rejected: ['#ef4444', '#fef2f2'],
  pending: ['#94a3b8', '#f8fafc'],
}

const StatusBadge = ({ status }) => {
  const [color, bg] = STATUS_COLOR[status] || ['#94a3b8', '#f8fafc']
  return (
    <span style={{ background: bg, color, fontSize: 11, fontWeight: 600, padding: '3px 8px', borderRadius: 4, whiteSpace: 'nowrap' }}>
      {status?.replace(/_/g, ' ').toUpperCase()}
    </span>
  )
}

function RepeatModal({ order, onClose, onConfirm }) {
  const [qty, setQty] = useState(order.quantity)
  const [address, setAddress] = useState(order.delivery_address || '')
  const [date, setDate] = useState('')
  const [loading, setLoading] = useState(false)

  const handle = async () => {
    setLoading(true)
    await onConfirm({ quantity: qty, delivery_address: address, requested_delivery_date: date || undefined })
    setLoading(false)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ background: 'white', borderRadius: 16, padding: 28, width: 420, boxShadow: '0 20px 60px rgba(0,0,0,0.15)' }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Repeat Order</h3>
        <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px' }}>Original: {order.order_id} · {order.product_name}</p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 5 }}>Quantity</label>
            <input type="number" min={1} value={qty} onChange={e => setQty(parseInt(e.target.value))}
              style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, boxSizing: 'border-box' }}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 5 }}>Delivery Address</label>
            <input value={address} onChange={e => setAddress(e.target.value)}
              style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, boxSizing: 'border-box' }}
            />
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 5 }}>Requested Delivery Date (optional)</label>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
              style={{ width: '100%', padding: '9px 12px', borderRadius: 8, border: '1.5px solid #e2e8f0', fontSize: 13, boxSizing: 'border-box' }}
            />
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
          <button onClick={onClose} style={{ flex: 1, padding: '10px', borderRadius: 8, border: '1.5px solid #e2e8f0', background: 'white', color: '#374151', cursor: 'pointer', fontWeight: 600 }}>
            Cancel
          </button>
          <button onClick={handle} disabled={loading} style={{ flex: 1, padding: '10px', borderRadius: 8, border: 'none', background: 'linear-gradient(135deg, #3b82f6, #6366f1)', color: 'white', cursor: 'pointer', fontWeight: 600 }}>
            {loading ? 'Placing...' : 'Confirm & Place'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function PortalOrdersPage() {
  const [repeatOrder, setRepeatOrder] = useState(null)
  const [repeatResult, setRepeatResult] = useState(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['portal-orders'],
    queryFn: () => portalApi.orders().then(r => r.data),
  })

  const repeatMutation = useMutation({
    mutationFn: ({ order_id, ...rest }) => portalApi.repeatOrder(order_id, rest),
    onSuccess: (res) => {
      setRepeatResult({ success: true, order_id: res.data.order_id })
      setRepeatOrder(null)
      refetch()
    },
    onError: (err) => {
      setRepeatResult({ success: false, error: err.response?.data?.detail || 'Failed' })
      setRepeatOrder(null)
    }
  })

  const orders = data?.orders || []

  return (
    <div>
      {repeatOrder && (
        <RepeatModal
          order={repeatOrder}
          onClose={() => setRepeatOrder(null)}
          onConfirm={(payload) => repeatMutation.mutateAsync({ order_id: repeatOrder.order_id, ...payload })}
        />
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>My Orders</h1>
          <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>{orders.length} orders found</p>
        </div>
      </div>

      {repeatResult && (
        <div style={{ background: repeatResult.success ? '#f0fdf4' : '#fef2f2', border: `1px solid ${repeatResult.success ? '#bbf7d0' : '#fecaca'}`, borderRadius: 10, padding: '12px 16px', marginBottom: 16, fontSize: 13, color: repeatResult.success ? '#14532d' : '#7f1d1d' }}>
          {repeatResult.success ? `✅ New order ${repeatResult.order_id} placed successfully!` : `❌ ${repeatResult.error}`}
        </div>
      )}

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>Loading orders...</div>
      ) : orders.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Package size={40} style={{ color: '#cbd5e1', margin: '0 auto 12px' }} />
          <div style={{ color: '#94a3b8', fontSize: 15 }}>No orders yet. Place your first order from the dashboard!</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {orders.map(order => (
            <div key={order.order_id} style={{
              background: 'white', borderRadius: 12, padding: '16px 20px',
              boxShadow: '0 2px 8px rgba(0,0,0,0.05)', border: '1px solid #f1f5f9',
              display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap',
            }}>
              {/* Order info */}
              <div style={{ flex: 1, minWidth: 180 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>{order.order_id}</span>
                  <StatusBadge status={order.status} />
                </div>
                <div style={{ fontSize: 13, color: '#374151', marginBottom: 2 }}>{order.product_name || order.sku_id}</div>
                <div style={{ fontSize: 12, color: '#94a3b8' }}>
                  {new Date(order.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                </div>
              </div>

              {/* Amounts */}
              <div style={{ textAlign: 'right', minWidth: 120 }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>
                  ₹{Number(order.total_amount_inr).toLocaleString('en-IN')}
                </div>
                <div style={{ fontSize: 12, color: '#94a3b8' }}>Qty: {order.quantity}</div>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => setRepeatOrder(order)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '7px 14px', borderRadius: 8, border: '1.5px solid #e2e8f0',
                    background: 'white', color: '#3b82f6', fontWeight: 600, fontSize: 12, cursor: 'pointer',
                  }}
                >
                  <RotateCcw size={12} /> Repeat
                </button>
                <button
                  onClick={() => setRepeatOrder({ ...order, _edit: true })}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '7px 14px', borderRadius: 8, border: 'none',
                    background: 'linear-gradient(135deg, #3b82f6, #6366f1)', color: 'white', fontWeight: 600, fontSize: 12, cursor: 'pointer',
                  }}
                >
                  <Edit3 size={12} /> Edit & Repeat
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
