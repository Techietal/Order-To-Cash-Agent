import React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { portalApi, cashAppApi } from '../lib/api'
import { AlertCircle, CheckCircle } from 'lucide-react'

function getDaysColor(days) {
  if (days > 30) return { color: '#dc2626', bg: '#fef2f2' }
  if (days > 15) return { color: '#f59e0b', bg: '#fffbeb' }
  return { color: '#2563eb', bg: '#eff6ff' }
}

export default function PortalOutstandingPage() {
  const queryClient = useQueryClient()
  
  const { data, isLoading } = useQuery({
    queryKey: ['portal-outstanding'],
    queryFn: () => portalApi.outstanding().then(r => r.data),
  })

  const payMutation = useMutation({
    mutationFn: (inv) => cashAppApi.processPayment({
      remittance_text: `Portal payment for ${inv.invoice_id} amount Rs ${inv.balance_due_inr}`,
      expected_invoice_id: inv.invoice_id,
      payment_token: inv.payment_token,   // 12-digit token stored with invoice — required for authorization
    }),
    onSuccess: (res) => {
      if (res.data.success) {
        alert(`✅ ${res.data.agent_reason}`)
        queryClient.invalidateQueries(['portal-outstanding'])
        queryClient.invalidateQueries(['portal-payments'])
      } else {
        alert(`❌ Payment not processed: ${res.data.agent_reason}`)
      }
    },
    onError: (err) => {
      alert(`Payment failed: ${err.response?.data?.detail || err.message}`)
    }
  })

  const invoices = data?.invoices || []
  const total = data?.total_outstanding_inr || 0

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Outstanding Invoices</h1>
          <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>{invoices.length} unpaid invoice(s)</p>
        </div>
        {total > 0 && (
          <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, padding: '12px 20px', textAlign: 'right' }}>
            <div style={{ fontSize: 12, color: '#7f1d1d', fontWeight: 600 }}>TOTAL OUTSTANDING</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: '#dc2626' }}>₹{total.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</div>
          </div>
        )}
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>Loading...</div>
      ) : invoices.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <CheckCircle size={40} style={{ color: '#10b981', margin: '0 auto 12px' }} />
          <div style={{ fontSize: 16, fontWeight: 600, color: '#14532d' }}>All caught up! No outstanding invoices.</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {invoices.map(inv => {
            const { color, bg } = getDaysColor(inv.days_overdue || 0)
            return (
              <div key={inv.invoice_id} style={{
                background: 'white', borderRadius: 12, padding: '16px 20px',
                boxShadow: '0 2px 8px rgba(0,0,0,0.05)', border: `1px solid ${inv.days_overdue > 0 ? '#fecaca' : '#f1f5f9'}`,
                borderLeft: `4px solid ${color}`,
                display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap',
              }}>
                <div style={{ flex: 1, minWidth: 150 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>{inv.invoice_id}</span>
                    <span style={{ background: bg, color, fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4 }}>
                      {inv.payment_status?.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>
                    Due: {new Date(inv.due_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                  </div>
                </div>

                <div style={{ textAlign: 'center', minWidth: 100 }}>
                  <div style={{ fontSize: 13, fontWeight: 800, color, display: 'flex', alignItems: 'center', gap: 4 }}>
                    {inv.days_overdue > 0 && <AlertCircle size={13} />}
                    {inv.days_overdue > 0 ? `${inv.days_overdue} days overdue` : 'Due soon'}
                  </div>
                </div>

                <div style={{ textAlign: 'right', minWidth: 120 }}>
                  <div style={{ fontSize: 16, fontWeight: 800, color: '#0f172a' }}>
                    ₹{Number(inv.balance_due_inr).toLocaleString('en-IN')}
                  </div>
                  <div style={{ fontSize: 11, color: '#94a3b8' }}>Balance due</div>
                </div>

                <div>
                  <button
                    onClick={() => payMutation.mutate(inv)}
                    disabled={payMutation.isPending && payMutation.variables?.invoice_id === inv.invoice_id}
                    style={{
                      padding: '8px 16px', borderRadius: 8, border: 'none',
                      background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
                      color: 'white', fontWeight: 600, fontSize: 12, cursor: 'pointer',
                      opacity: (payMutation.isPending && payMutation.variables?.invoice_id === inv.invoice_id) ? 0.7 : 1
                    }}
                  >
                    {payMutation.isPending && payMutation.variables?.invoice_id === inv.invoice_id ? 'Processing via Agent...' : 'Pay Now →'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
