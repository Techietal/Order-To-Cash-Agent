import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { User, Clock, ArrowRight, RefreshCcw, Shield } from 'lucide-react'
import { complianceApi } from '../lib/api'

function formatDate(v) {
  if (!v) return '—'
  return new Date(v).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

const ROLE_BADGE = {
  admin:               <span className="badge badge-blue">Admin</span>,
  controller:          <span className="badge badge-violet">Controller</span>,
  dispute_manager:     <span className="badge badge-amber">Dispute Manager</span>,
  collections_analyst: <span className="badge badge-green">Collections Analyst</span>,
}

function DiffCell({ prev, next }) {
  if (!prev && !next) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  const prevStr = prev ? JSON.stringify(prev, null, 0) : null
  const nextStr = next ? JSON.stringify(next, null, 0) : null
  return (
    <div style={{ fontSize: 11, lineHeight: 1.6 }}>
      {prevStr && (
        <div style={{ color: '#f87171', background: 'rgba(248,113,113,0.08)', borderRadius: 4, padding: '2px 6px', marginBottom: 3, fontFamily: 'monospace' }}>
          − {prevStr.slice(0, 80)}{prevStr.length > 80 ? '…' : ''}
        </div>
      )}
      {nextStr && (
        <div style={{ color: '#4ade80', background: 'rgba(74,222,128,0.08)', borderRadius: 4, padding: '2px 6px', fontFamily: 'monospace' }}>
          + {nextStr.slice(0, 80)}{nextStr.length > 80 ? '…' : ''}
        </div>
      )}
    </div>
  )
}

export default function HumanActionLogPage() {
  const [usernameFilter, setUsernameFilter] = useState('')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['human-action-log', usernameFilter],
    queryFn: () => complianceApi.auditLog({
      actor_type: 'human',
      actor_username: usernameFilter || undefined,
      limit: 200,
    }).then(r => r.data),
    refetchInterval: 30000,
  })

  const entries = data?.audit_log || []

  return (
    <div>
      <div className="page-header" style={{ marginTop: 18 }}>
        <div className="page-header-left">
          <h2 className="page-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Shield size={22} color="var(--accent-violet)" />
            Human Action Log
          </h2>
          <p className="page-subtitle">
            Staff decisions only · AI agent events excluded · SOX-compliant identity trail
          </p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={refetch}>
          <RefreshCcw size={13} /> Refresh
        </button>
      </div>

      {/* Filter bar */}
      <div className="card" style={{ marginBottom: 18, padding: '12px 16px' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>Filter by actor:</div>
          <input
            className="form-input"
            placeholder="Username…"
            value={usernameFilter}
            onChange={e => setUsernameFilter(e.target.value)}
            style={{ width: 180, padding: '6px 10px', fontSize: 12 }}
          />
          {usernameFilter && (
            <button className="btn btn-secondary btn-sm" onClick={() => setUsernameFilter('')}>Clear</button>
          )}
          <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
            {entries.length} human actions logged
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div className="card-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <User size={15} /> Staff Decision Trail
          </div>
          <span className="badge badge-violet">{entries.length} entries</span>
        </div>

        {isLoading ? (
          <div className="loading-wrap"><div className="spinner" /></div>
        ) : entries.length === 0 ? (
          <div className="empty-state">
            <Shield size={32} style={{ opacity: 0.25 }} />
            <div className="empty-title">No human actions yet</div>
            <div className="empty-text">Approve an order in the HITL queue or resolve a dispute to see entries here.</div>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Actor</th>
                  <th>Role</th>
                  <th>Event Type</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Before → After</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e, i) => (
                  <tr key={e.log_id || i}>
                    <td style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                      <Clock size={10} style={{ marginRight: 4, verticalAlign: 'middle' }} />
                      {formatDate(e.created_at)}
                    </td>
                    <td style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-primary)' }}>
                      {e.actor_username || <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>
                    <td>{ROLE_BADGE[e.actor_role] || (e.actor_role ? <span className="badge badge-gray">{e.actor_role}</span> : '—')}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-blue)' }}>
                      {e.event_type}
                    </td>
                    <td>
                      <span className="badge badge-gray" style={{ fontFamily: 'monospace', fontSize: 10 }}>
                        {e.action}
                      </span>
                    </td>
                    <td style={{ fontSize: 11 }}>
                      {e.order_id && <div style={{ color: 'var(--text-secondary)' }}>Order: <strong>{e.order_id}</strong></div>}
                      {e.invoice_id && <div style={{ color: 'var(--text-muted)' }}>Invoice: {e.invoice_id}</div>}
                    </td>
                    <td style={{ maxWidth: 300 }}>
                      <DiffCell prev={e.previous_value} next={e.new_value} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
