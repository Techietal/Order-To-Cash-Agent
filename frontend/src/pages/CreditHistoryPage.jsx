import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { creditMemosApi } from '../lib/api'
import { History, ArrowDownRight, RefreshCcw, Search, CreditCard, ShieldCheck, Building2, Landmark } from 'lucide-react'

// ── Source config — every source gets its own icon, color and label ───────────
const SOURCE_META = {
  dispute_resolution: {
    label: 'Dispute Credit',
    icon:  ShieldCheck,
    color: 'var(--accent-amber)',
    bg:    'rgba(245,158,11,0.12)',
    title: 'Applied as a credit memo after dispute resolution by staff',
  },
  ar_ledger_manual: {
    label: 'AR Ledger (Manual)',
    icon:  Landmark,
    color: 'var(--accent-teal)',
    bg:    'rgba(20,184,166,0.12)',
    title: 'Manually marked as received by admin / collections team in AR Ledger',
  },
  customer_portal: {
    label: 'Customer Portal',
    icon:  CreditCard,
    color: 'var(--accent-blue)',
    bg:    'rgba(59,130,246,0.12)',
    title: 'Customer self-paid via the B2B portal',
  },
  hitl_payment: {
    label: 'HITL Approved',
    icon:  Building2,
    color: 'var(--accent-violet)',
    bg:    'rgba(139,92,246,0.12)',
    title: 'Approved through Human-in-the-Loop queue',
  },
}

function SourceBadge({ source }) {
  const meta = SOURCE_META[source] || {
    label: source || 'Unknown',
    icon:  History,
    color: 'var(--text-muted)',
    bg:    'rgba(255,255,255,0.05)',
    title: '',
  }
  const Icon = meta.icon
  return (
    <span
      title={meta.title}
      style={{
        display:       'inline-flex',
        alignItems:    'center',
        gap:           4,
        background:    meta.bg,
        color:         meta.color,
        border:        `1px solid ${meta.color}44`,
        borderRadius:  5,
        padding:       '2px 7px',
        fontSize:      10,
        fontWeight:    700,
        whiteSpace:    'nowrap',
        cursor:        'default',
      }}
    >
      <Icon size={9} />
      {meta.label}
    </span>
  )
}

const ROLE_BADGE_COLOR = {
  admin:               { bg: 'rgba(59,130,246,0.15)',  color: 'var(--accent-blue)' },
  dispute_manager:     { bg: 'rgba(245,158,11,0.15)',  color: 'var(--accent-amber)' },
  collections_analyst: { bg: 'rgba(34,197,94,0.15)',   color: 'var(--accent-green)' },
  controller:          { bg: 'rgba(139,92,246,0.15)',  color: 'var(--accent-violet)' },
  customer:            { bg: 'rgba(20,184,166,0.15)',  color: 'var(--accent-teal)' },
}

function RoleBadge({ role }) {
  const s = ROLE_BADGE_COLOR[role] || { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)' }
  return (
    <span style={{
      background: s.bg, color: s.color,
      border: `1px solid ${s.color}44`,
      borderRadius: 5, padding: '2px 7px', fontSize: 10, fontWeight: 700,
    }}>
      {role?.replace(/_/g, ' ') || '—'}
    </span>
  )
}

function formatDateTime(v) {
  if (!v) return '—'
  return new Date(v).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: true,
  })
}

// KPI per source
function bySource(memos) {
  const result = {}
  for (const m of memos) {
    const s = m.source || 'dispute_resolution'
    if (!result[s]) result[s] = { count: 0, total: 0 }
    result[s].count++
    result[s].total += +(m.amount_inr || 0)
  }
  return result
}

export default function CreditHistoryPage() {
  const [search,    setSearch]    = useState('')
  const [filterSrc, setFilterSrc] = useState('all')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['credit-memos-all'],
    queryFn:  () => creditMemosApi.list({ limit: 500 }).then(r => r.data),
    refetchInterval: 60000,
  })

  const allMemos = data?.credit_memos || []
  const totalAmt = +(data?.total_amount_inr || 0)
  const srcCounts = bySource(allMemos)

  // Filter by source
  const afterSrc = filterSrc === 'all' ? allMemos : allMemos.filter(m => (m.source || 'dispute_resolution') === filterSrc)

  // Then by search
  const memos = search.trim()
    ? afterSrc.filter(m =>
        [m.customer_id, m.company_name, m.invoice_id, m.dispute_id, m.approved_by, m.memo_id, m.source, m.payment_ref]
          .some(v => v && String(v).toLowerCase().includes(search.toLowerCase()))
      )
    : afterSrc

  return (
    <div className="page-content animate-fade">
      {/* Header */}
      <div className="page-header" style={{ marginTop: 18 }}>
        <div className="page-header-left">
          <h1 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <History size={22} color="var(--accent-violet)" />
            Credit & Payment History
          </h1>
          <p className="page-subtitle">
            Unified ledger — dispute credits · manual payments (AR Ledger) · customer portal payments · sorted newest first
          </p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={refetch}>
          <RefreshCcw size={13} /> Refresh
        </button>
      </div>

      {/* Summary KPIs — one per source + totals */}
      <div className="kpi-grid" style={{ marginBottom: 16 }}>
        <div className="kpi-card" style={{ borderColor: 'rgba(139,92,246,0.3)', background: 'rgba(139,92,246,0.05)' }}>
          <div className="kpi-label" style={{ color: 'var(--accent-violet)' }}>Total Adjusted (All Time)</div>
          <div className="kpi-value" style={{ color: 'var(--accent-violet)' }}>
            ₹{(totalAmt / 100000).toFixed(2)}L
          </div>
          <div className="kpi-delta">{allMemos.length} entries total</div>
        </div>
        {Object.entries(SOURCE_META).map(([key, meta]) => {
          const info = srcCounts[key] || { count: 0, total: 0 }
          const Icon = meta.icon
          return (
            <div key={key} className="kpi-card" onClick={() => setFilterSrc(filterSrc === key ? 'all' : key)}
              style={{
                borderColor: `${meta.color}44`, background: meta.bg, cursor: 'pointer',
                outline: filterSrc === key ? `2px solid ${meta.color}` : 'none', transition: 'all 0.2s',
              }}>
              <div className="kpi-label" style={{ color: meta.color, display: 'flex', alignItems: 'center', gap: 5 }}>
                <Icon size={11} /> {meta.label}
              </div>
              <div className="kpi-value" style={{ color: meta.color }}>
                ₹{(info.total / 100000).toFixed(1)}L
              </div>
              <div className="kpi-delta">{info.count} entr{info.count !== 1 ? 'ies' : 'y'}</div>
            </div>
          )
        })}
      </div>

      {/* Source filter pills */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {['all', ...Object.keys(SOURCE_META)].map(s => {
          const meta = s === 'all' ? { label: 'All Sources', color: 'var(--text-muted)', bg: 'rgba(255,255,255,0.04)', icon: History }
                                   : SOURCE_META[s]
          const Icon = meta.icon
          const active = filterSrc === s
          return (
            <button key={s} onClick={() => setFilterSrc(s)} style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              background: active ? meta.bg : 'transparent',
              color: active ? meta.color : 'var(--text-muted)',
              border: `1px solid ${active ? meta.color + '66' : 'var(--border)'}`,
              borderRadius: 6, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: 'pointer',
              transition: 'all 0.15s',
            }}>
              <Icon size={10} />
              {meta.label}
              {s !== 'all' && <span style={{ opacity: 0.6 }}>({srcCounts[s]?.count || 0})</span>}
            </button>
          )
        })}
      </div>

      {/* Search bar */}
      <div className="card" style={{ marginBottom: 16, padding: '10px 16px' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <Search size={14} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
          <input
            className="form-input"
            placeholder="Search by customer, memo ID, invoice, dispute, approved by, payment ref…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ flex: 1, padding: '6px 10px', fontSize: 12 }}
          />
          {search && (
            <button className="btn btn-secondary btn-sm" onClick={() => setSearch('')}>Clear</button>
          )}
          <span style={{ fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 }}>
            {memos.length} / {allMemos.length} records
          </span>
        </div>
      </div>

      {/* Main table */}
      <div className="card">
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <History size={15} color="var(--accent-violet)" />
            {filterSrc === 'all' ? 'All Credit & Payment Entries' : (SOURCE_META[filterSrc]?.label || filterSrc)}
          </div>
          <span className="badge" style={{ background: 'rgba(139,92,246,0.15)', color: 'var(--accent-violet)', border: '1px solid rgba(139,92,246,0.3)' }}>
            {memos.length} entr{memos.length !== 1 ? 'ies' : 'y'}
          </span>
        </div>

        {isLoading ? (
          <div className="loading-wrap"><div className="spinner" /></div>
        ) : memos.length === 0 ? (
          <div className="empty-state">
            <History size={36} style={{ opacity: 0.15 }} />
            <div className="empty-title">No entries yet</div>
            <div className="empty-text">
              Entries appear here when disputes are resolved, payments are marked received in AR Ledger, or customers pay via the portal.
            </div>
          </div>
        ) : (
          <div className="table-wrap"><table>
            <thead><tr>
              <th>Date & Time</th>
              <th>Source</th>
              <th>Memo ID</th>
              <th>Customer</th>
              <th>Invoice</th>
              <th>Order</th>
              <th>Amount</th>
              <th>Balance Before → After</th>
              <th>Reason / Note</th>
              <th>Ref</th>
              <th>Actioned By</th>
            </tr></thead>
            <tbody>
              {memos.map(m => (
                <tr key={m.memo_id}>
                  <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                    {formatDateTime(m.created_at)}
                  </td>
                  <td><SourceBadge source={m.source || 'dispute_resolution'} /></td>
                  <td style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--accent-violet)' }}>
                    {m.memo_id}
                  </td>
                  <td>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {m.company_name || m.customer_id}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                      {m.customer_id}
                    </div>
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-blue)' }}>
                    {m.invoice_id || '—'}
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-muted)' }}>
                    {m.order_id || '—'}
                  </td>
                  <td style={{ fontWeight: 700, color: 'var(--accent-green)', whiteSpace: 'nowrap' }}>
                    ₹{(+(m.amount_inr || 0)).toLocaleString('en-IN')}
                  </td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                      <span style={{ color: 'var(--accent-amber)' }}>
                        ₹{(+(m.balance_before_inr || 0)).toLocaleString('en-IN')}
                      </span>
                      <ArrowDownRight size={12} color="var(--accent-green)" />
                      <span style={{ color: +(m.balance_after_inr || 0) === 0 ? 'var(--accent-green)' : 'var(--accent-amber)', fontWeight: 600 }}>
                        ₹{(+(m.balance_after_inr || 0)).toLocaleString('en-IN')}
                      </span>
                      {+(m.balance_after_inr || 0) === 0 && (
                        <span className="badge badge-green" style={{ fontSize: 9, padding: '1px 5px' }}>PAID</span>
                      )}
                    </div>
                  </td>
                  <td style={{ fontSize: 11, color: 'var(--text-secondary)', maxWidth: 200 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.reason}>
                      {m.reason || '—'}
                    </div>
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-muted)', maxWidth: 120 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={m.payment_ref}>
                      {m.payment_ref || '—'}
                    </div>
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
                        {m.approved_by}
                      </span>
                      <RoleBadge role={m.approved_by_role} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </div>
    </div>
  )
}
