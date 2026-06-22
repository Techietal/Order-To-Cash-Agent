import { ShieldAlert, ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store'
import { ROLE_HOME } from '../components/RoleGuard'

const ROLE_LABELS = {
  admin:               'O2C Admin',
  controller:          'Finance Controller',
  inventory_manager:   'Inventory Manager',
  dispute_manager:     'Disputes Manager',
  collections_analyst: 'Collections Analyst',
}

const ROLE_COLORS = {
  admin:               'var(--accent-blue)',
  controller:          'var(--accent-violet)',
  inventory_manager:   'var(--accent-cyan)',
  dispute_manager:     'var(--accent-amber)',
  collections_analyst: 'var(--accent-green)',
}

export default function ForbiddenPage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const role = user?.role || 'unknown'
  const roleLabel = ROLE_LABELS[role] || role
  const roleColor = ROLE_COLORS[role] || 'var(--text-muted)'
  const homePath = ROLE_HOME[role] || '/'

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'radial-gradient(ellipse at 30% 40%, rgba(239,68,68,0.06) 0%, transparent 55%), var(--bg-900)',
      padding: 24,
    }}>
      <div style={{ textAlign: 'center', maxWidth: 480 }}>
        {/* Icon */}
        <div style={{
          width: 80, height: 80,
          background: 'linear-gradient(135deg, rgba(239,68,68,0.15), rgba(239,68,68,0.05))',
          border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 20,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 28px',
        }}>
          <ShieldAlert size={36} color="#ef4444" />
        </div>

        {/* Error code */}
        <div style={{
          fontSize: 72, fontWeight: 800,
          background: 'linear-gradient(135deg, #ef4444, #f97316)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          lineHeight: 1, marginBottom: 16,
        }}>403</div>

        <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 10 }}>
          Access Denied
        </h1>

        <p style={{ fontSize: 14, color: 'var(--text-muted)', lineHeight: 1.7, marginBottom: 28 }}>
          You are signed in as{' '}
          <span style={{
            background: `${roleColor}22`, color: roleColor,
            border: `1px solid ${roleColor}44`,
            borderRadius: 6, padding: '2px 8px', fontSize: 12, fontWeight: 700,
          }}>{roleLabel}</span>
          {' '}and do not have permission to view this page.
        </p>

        {/* Action */}
        <button
          onClick={() => navigate(homePath)}
          className="btn btn-primary"
          style={{ gap: 8, justifyContent: 'center' }}
        >
          <ArrowLeft size={15} />
          Back to {role === 'dispute_manager' ? 'Disputes' : role === 'collections_analyst' ? 'Collections' : 'Dashboard'}
        </button>

        <div style={{ marginTop: 20, fontSize: 12, color: 'var(--text-muted)' }}>
          If you believe this is an error, contact your system administrator.
        </div>
      </div>
    </div>
  )
}
