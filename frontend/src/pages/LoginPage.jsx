import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store'
import { authApi } from '../lib/api'
import { ROLE_HOME } from '../components/RoleGuard'

const QUICK_LOGINS = [
  { label: 'Admin',             username: 'admin',              password: 'admin123', icon: '🛡️', desc: 'Full access' },
  { label: 'Controller',        username: 'controller',         password: 'ctrl123',  icon: '📊', desc: 'Finance view' },
  { label: 'Inventory Manager', username: 'inventory_manager',  password: 'inv123',   icon: '📦', desc: 'Stock & orders' },
  { label: 'Disputes Mgr',      username: 'dispute_manager',    password: 'dm123',    icon: '⚖️', desc: 'Dispute queue' },
  { label: 'Collections',       username: 'collections_analyst',password: 'ca123',    icon: '💰', desc: 'AR collections' },
]

export default function LoginPage() {
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { setAuth } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await authApi.login(form)
      const { user, access_token } = res.data
      setAuth(user, access_token)
      // Route to the role's home page, not always '/'
      navigate(ROLE_HOME[user.role] || '/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid credentials')
    } finally {
      setLoading(false)
    }
  }

  const quickLogin = (ql) => {
    setForm({ username: ql.username, password: ql.password })
    setError('')
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg-subtle)',
      padding: '24px',
    }}>
      <div style={{ width: '100%', maxWidth: 460 }}>

        {/* Brand header */}
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{
            width: 52, height: 52, background: 'var(--brand)',
            borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 17, fontWeight: 700, color: 'white', margin: '0 auto 14px',
            letterSpacing: '.03em',
          }}>O2C</div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>O2C Agent v2.0</h1>
          <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>Order-to-Cash Agentic AI</p>
        </div>

        {/* Main card */}
        <div className="card" style={{ padding: 28 }}>

          {/* Quick Demo Login */}
          <div style={{ marginBottom: 24 }}>
            <div style={{
              fontSize: 10, fontWeight: 600, color: 'var(--text-muted)',
              textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 10,
            }}>
              Quick Demo Login
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              {QUICK_LOGINS.map(ql => (
                <button
                  key={ql.username}
                  type="button"
                  onClick={() => quickLogin(ql)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    padding: '10px 12px',
                    background: 'var(--bg-subtle)',
                    border: `1px solid var(--border)`,
                    borderRadius: 6, cursor: 'pointer',
                    transition: 'all .12s', textAlign: 'left',
                    outline: 'none',
                    gridColumn: ql.label === 'Collections' ? 'span 2' : undefined,
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = 'var(--brand-light)'
                    e.currentTarget.style.borderColor = 'var(--brand)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = 'var(--bg-subtle)'
                    e.currentTarget.style.borderColor = 'var(--border)'
                  }}
                >
                  <span style={{ fontSize: 18, lineHeight: 1 }}>{ql.icon}</span>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.3 }}>{ql.label}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', lineHeight: 1.2 }}>{ql.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Divider */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
            <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>or sign in manually</span>
            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Username</label>
              <input
                className="form-input"
                placeholder="Enter username"
                value={form.username}
                onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                autoComplete="username"
              />
            </div>
            <div className="form-group">
              <label className="form-label">Password</label>
              <input
                className="form-input"
                type="password"
                placeholder="Enter password"
                value={form.password}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                autoComplete="current-password"
              />
            </div>
            {error && <div className="alert alert-error" style={{ marginBottom: 16 }}>{error}</div>}
            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', justifyContent: 'center', padding: '10px 16px', fontSize: 14 }}
              disabled={loading}
            >
              {loading ? <span className="spinner" style={{ width: 16, height: 16, borderTopColor: 'white' }} /> : 'Sign In'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
