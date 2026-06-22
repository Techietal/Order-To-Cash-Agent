import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { portalApi } from '../lib/api'
import { CreditCard, CheckCircle } from 'lucide-react'

export default function PortalPaymentsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['portal-payments'],
    queryFn: () => portalApi.payments().then(r => r.data),
  })

  const payments = data?.payments || []

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>Payment History</h1>
        <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>{payments.length} payments recorded</p>
      </div>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>Loading payments...</div>
      ) : payments.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <CreditCard size={40} style={{ color: '#cbd5e1', margin: '0 auto 12px' }} />
          <div style={{ color: '#94a3b8', fontSize: 15 }}>No payment records found yet.</div>
        </div>
      ) : (
        <div style={{ background: 'white', borderRadius: 14, overflow: 'hidden', boxShadow: '0 2px 12px rgba(0,0,0,0.05)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                {['Payment ID', 'Invoice', 'Amount', 'Method', 'Date', 'Status'].map(h => (
                  <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 12, fontWeight: 700, color: '#374151', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {payments.map((p, i) => (
                <tr key={p.payment_id} style={{ borderBottom: '1px solid #f1f5f9', background: i % 2 === 0 ? 'white' : '#fafafa' }}>
                  <td style={{ padding: '12px 16px', fontSize: 13, fontWeight: 600, color: '#0f172a' }}>{p.payment_id}</td>
                  <td style={{ padding: '12px 16px', fontSize: 13, color: '#374151' }}>{p.invoice_id}</td>
                  <td style={{ padding: '12px 16px', fontSize: 13, fontWeight: 700, color: '#0f172a' }}>₹{Number(p.amount_inr || p.payment_amount_inr).toLocaleString('en-IN')}</td>
                  <td style={{ padding: '12px 16px', fontSize: 13, color: '#374151' }}>{p.payment_method || 'NEFT'}</td>
                  <td style={{ padding: '12px 16px', fontSize: 13, color: '#64748b' }}>{new Date(p.payment_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{ background: '#f0fdf4', color: '#16a34a', fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      <CheckCircle size={10} /> Received
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
