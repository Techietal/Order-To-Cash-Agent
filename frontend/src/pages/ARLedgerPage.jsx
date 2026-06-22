import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { arApi, creditMemosApi } from '../lib/api'
import { RefreshCw, Receipt, CheckCircle2, X } from 'lucide-react'
import { ActionGuard } from '../components/RoleGuard'
import { useAuthStore } from '../store'

const AC = { '0-30': '#22c55e', '31-60': '#f59e0b', '61-90': '#ef4444', '90+': '#7f1d1d', current: '#3b82f6' }

function quarterStart() {
  const now = new Date()
  const q = Math.floor(now.getMonth() / 3)
  return new Date(now.getFullYear(), q * 3, 1).toISOString()
}

// ── Mark-as-Received Modal ────────────────────────────────────────────────────
function MarkReceivedModal({ entry, onClose, onSuccess }) {
  const [amount, setAmount]   = useState(String(+(entry.outstanding_balance_inr || 0)))
  const [note, setNote]       = useState('')
  const [result, setResult]   = useState(null)
  const [error, setError]     = useState('')
  const qc = useQueryClient()

  const mut = useMutation({
    mutationFn: () => arApi.manualPayment(entry.ar_id, {
      amount_received: parseFloat(amount),
      note,
    }).then(r => r.data),
    onSuccess: (data) => {
      setResult(data)
      qc.invalidateQueries(['ar-ledger'])
      qc.invalidateQueries(['ar-aging'])
      if (onSuccess) onSuccess(data)
    },
    onError: (e) => setError(e?.response?.data?.detail || e.message),
  })

  const maxAmt = +(entry.outstanding_balance_inr || 0)

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
      backdropFilter: 'blur(4px)', zIndex: 1100,
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
    }} onClick={e => e.target === e.currentTarget && onClose()}>
      <div style={{
        background: 'var(--bg-800)', border: '1px solid var(--border)', borderRadius: 12,
        width: '100%', maxWidth: 460, boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
      }}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Mark as Received</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
              {entry.ar_id} · Invoice {entry.invoice_id}
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 6, padding: 5, cursor: 'pointer', color: 'var(--text-muted)' }}>
            <X size={15} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 20 }}>
          {result ? (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                <CheckCircle2 size={24} color="var(--accent-green)" />
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent-green)' }}>Payment Recorded</div>
              </div>
              <div className="alert alert-success">{result.message}</div>
              <div style={{ marginTop: 14, fontSize: 12, display: 'flex', gap: 24 }}>
                <div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase' }}>Before</div>
                  <div style={{ fontWeight: 700, color: 'var(--accent-amber)' }}>₹{(+(result.balance_before||0)).toLocaleString('en-IN')}</div>
                </div>
                <div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase' }}>After</div>
                  <div style={{ fontWeight: 700, color: result.balance_after === 0 ? 'var(--accent-green)' : 'var(--accent-amber)' }}>₹{(+(result.balance_after||0)).toLocaleString('en-IN')}</div>
                </div>
                <div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase' }}>Status</div>
                  <span className={`badge ${result.payment_status === 'paid' ? 'badge-green' : 'badge-amber'}`}>{result.payment_status}</span>
                </div>
              </div>
              <button className="btn btn-secondary" style={{ marginTop: 16, width: '100%' }} onClick={onClose}>Close</button>
            </div>
          ) : (
            <>
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>Outstanding Balance</div>
                <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent-amber)' }}>₹{maxAmt.toLocaleString('en-IN')}</div>
              </div>

              <div className="form-group">
                <label className="form-label">Amount Received (INR)</label>
                <input
                  className="form-input"
                  type="number"
                  min="1"
                  max={maxAmt}
                  step="0.01"
                  value={amount}
                  onChange={e => setAmount(e.target.value)}
                  placeholder="Enter amount received"
                />
                {parseFloat(amount) > 0 && parseFloat(amount) < maxAmt && (
                  <div style={{ fontSize: 11, color: 'var(--accent-amber)', marginTop: 4 }}>
                    ⚠ Partial payment — ₹{(maxAmt - parseFloat(amount)).toLocaleString('en-IN')} will remain outstanding
                  </div>
                )}
                {parseFloat(amount) >= maxAmt && (
                  <div style={{ fontSize: 11, color: 'var(--accent-green)', marginTop: 4 }}>
                    ✓ Full payment — invoice will be marked paid
                  </div>
                )}
              </div>

              <div className="form-group">
                <label className="form-label">Note (optional)</label>
                <input className="form-input" value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. Wire transfer ref #12345" />
              </div>

              {error && <div className="alert alert-error" style={{ marginBottom: 12 }}>{error}</div>}

              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  className="btn btn-success"
                  style={{ flex: 1 }}
                  onClick={() => mut.mutate()}
                  disabled={mut.isPending || !amount || parseFloat(amount) <= 0}
                >
                  {mut.isPending ? 'Recording...' : 'Confirm Payment'}
                </button>
                <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── AR Ledger Page ────────────────────────────────────────────────────────────
export default function ARLedgerPage() {
  const qc = useQueryClient()
  const { user } = useAuthStore()
  const [refreshing, setRefreshing] = useState(false)
  const [markEntry, setMarkEntry]   = useState(null)  // the AR row to mark paid

  const canMarkPaid = ['admin', 'collections_analyst'].includes(user?.role)

  const { data, isLoading } = useQuery({
    queryKey: ['ar-ledger'],
    queryFn: () => arApi.list({ limit: 200 }).then(r => r.data),
  })
  const { data: agingData } = useQuery({
    queryKey: ['ar-aging'],
    queryFn: () => arApi.aging().then(r => r.data),
  })
  const { data: creditSummary } = useQuery({
    queryKey: ['credit-memos-summary-quarter'],
    queryFn: () => creditMemosApi.summary({ since: quarterStart() }).then(r => r.data),
  })

  const entries   = data?.ar_entries || []
  const aging     = agingData?.aging || []
  const creditedQ = +(creditSummary?.total_amount_inr || 0)
  const creditCnt = +(creditSummary?.total_count || 0)

  const handleRefreshAging = async () => {
    setRefreshing(true)
    try {
      await arApi.refreshAging()
      await qc.invalidateQueries({ queryKey: ['ar-ledger'] })
      await qc.invalidateQueries({ queryKey: ['ar-aging'] })
    } catch (e) { console.error('Refresh aging failed:', e) }
    finally { setRefreshing(false) }
  }

  return (
    <div className="page-content animate-fade">
      {/* Mark-as-received modal */}
      {markEntry && (
        <MarkReceivedModal
          entry={markEntry}
          onClose={() => setMarkEntry(null)}
          onSuccess={() => setTimeout(() => setMarkEntry(null), 2000)}
        />
      )}

      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">AR Ledger</h1>
          <p className="page-subtitle">Agent 7 — XGBoost payment delay scoring · Aging analysis · Collection priority</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary btn-sm" onClick={handleRefreshAging} disabled={refreshing} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <RefreshCw size={14} style={{ animation: refreshing ? 'spin 1s linear infinite' : 'none' }} />
            {refreshing ? 'Refreshing...' : 'Refresh Aging'}
          </button>
        </div>
      </div>

      {/* KPI strip */}
      <div className="kpi-grid" style={{ marginBottom: 14 }}>
        {aging.map(a => (
          <div className="kpi-card" key={a.aging_bucket}>
            <div className="kpi-label" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: AC[a.aging_bucket] || '#3b82f6', display: 'inline-block' }} />
              {a.aging_bucket} days
            </div>
            <div className="kpi-value" style={{ color: AC[a.aging_bucket] || '#3b82f6' }}>
              ₹{(+(a.total_outstanding || 0) / 100000).toFixed(1)}L
            </div>
            <div className="kpi-delta">{a.count} invoices</div>
          </div>
        ))}
        <div className="kpi-card" style={{ borderColor: 'rgba(139,92,246,0.3)', background: 'rgba(139,92,246,0.05)' }}>
          <div className="kpi-label" style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <Receipt size={10} style={{ color: 'var(--accent-violet)' }} />
            Credited This Quarter
          </div>
          <div className="kpi-value" style={{ color: 'var(--accent-violet)' }}>
            ₹{(creditedQ / 100000).toFixed(1)}L
          </div>
          <div className="kpi-delta">{creditCnt} credit memo{creditCnt !== 1 ? 's' : ''}</div>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-header"><div className="card-title">AR Aging</div></div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={aging} barSize={36}>
              <XAxis dataKey="aging_bucket" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => (v / 100000).toFixed(0) + 'L'} />
              <Tooltip formatter={(v) => `₹${v}`} />
              <Bar dataKey="total_outstanding" name="Outstanding" radius={[4, 4, 0, 0]}>
                {aging.map((d, i) => <Cell key={i} fill={AC[d.aging_bucket] || '#3b82f6'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <div className="card-header"><div className="card-title">Bucket Summary</div></div>
          {aging.map(a => (
            <div className="stat-row" key={a.aging_bucket}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: AC[a.aging_bucket] || '#3b82f6' }} />
                <span className="stat-label">{a.aging_bucket} days</span>
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{a.count} inv.</span>
                <span className="stat-val">₹{(+(a.total_outstanding || 0) / 100000).toFixed(1)}L</span>
              </div>
            </div>
          ))}
          <div className="alert alert-success" style={{ marginTop: 12, fontSize: 12 }}>
            XGBoost delay scoring active — runs every 15 min via Agent 7 scheduler.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title">AR Entries</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {canMarkPaid && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Click <strong>Mark Received</strong> on any open row to record a payment
              </span>
            )}
            <span className="badge badge-blue">{entries.length}</span>
          </div>
        </div>
        {isLoading ? <div className="loading-wrap"><div className="spinner" /></div> : (
          <div className="table-wrap"><table>
            <thead><tr>
              <th>AR ID</th><th>Customer</th><th>Invoice</th><th>Amount</th>
              <th>Outstanding</th><th>Aging</th><th>Overdue</th>
              <th>XGB Score</th><th>Priority</th><th>Status</th>
              {canMarkPaid && <th></th>}
            </tr></thead>
            <tbody>{entries.slice(0, 100).map(a => (
              <tr key={a.ar_id}>
                <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-teal)' }}>{a.ar_id}</td>
                <td style={{ fontSize: 12 }}>{a.customer_id}</td>
                <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{a.invoice_id}</td>
                <td>₹{(+a.amount_inr || 0).toLocaleString('en-IN')}</td>
                <td style={{ color: +a.outstanding_balance_inr > 0 ? 'var(--accent-amber)' : 'var(--accent-green)', fontWeight: 600 }}>
                  ₹{(+a.outstanding_balance_inr || 0).toLocaleString('en-IN')}
                </td>
                <td>
                  <span className="badge" style={{ background: `${AC[a.aging_bucket] || '#3b82f6'}20`, color: AC[a.aging_bucket] || '#3b82f6', border: '1px solid #404040' }}>
                    {a.aging_bucket}
                  </span>
                </td>
                <td>{a.days_overdue > 0 ? <span className="badge badge-red">{a.days_overdue}d</span> : '—'}</td>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <div style={{ width: 36, height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ width: `${((+a.xgboost_delay_score || 0) * 100).toFixed(0)}%`, height: '100%', background: (+a.xgboost_delay_score || 0) > 0.6 ? 'var(--accent-red)' : 'var(--accent-green)', borderRadius: 2 }} />
                    </div>
                    <span style={{ fontSize: 10 }}>{((+a.xgboost_delay_score || 0) * 100).toFixed(0)}%</span>
                  </div>
                </td>
                <td><span className="badge badge-gray">{a.collection_priority || '—'}</span></td>
                <td>
                  <span className={`badge ${a.payment_status === 'paid' ? 'badge-green' : a.payment_status === 'overdue' ? 'badge-red' : 'badge-amber'}`}>
                    {a.payment_status}
                  </span>
                </td>
                {/* Mark as Received — admin + collections_analyst only */}
                {canMarkPaid && (
                  <td>
                    {a.payment_status !== 'paid' && +a.outstanding_balance_inr > 0 ? (
                      <ActionGuard allowed={['admin', 'collections_analyst']}>
                        <button
                          className="btn btn-success btn-sm"
                          style={{ fontSize: 11, padding: '3px 8px', display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}
                          onClick={() => setMarkEntry(a)}
                        >
                          <CheckCircle2 size={11} /> Mark Received
                        </button>
                      </ActionGuard>
                    ) : (
                      <span style={{ fontSize: 10, color: 'var(--accent-green)' }}>✓ Paid</span>
                    )}
                  </td>
                )}
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </div>
  )
}
