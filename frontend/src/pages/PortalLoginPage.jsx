import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { portalApi } from '../lib/api'
import { usePortalStore } from '../store'
import { LogIn, Eye, EyeOff } from 'lucide-react'

export default function PortalLoginPage() {
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPwd, setShowPwd] = useState(false)
  const { setPortalAuth } = usePortalStore()
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await portalApi.login(form)
      const d = res.data
      setPortalAuth(d, d.token)
      navigate('/portal/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh', background: 'linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 50%, #f0fdf4 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
      fontFamily: 'Inter, system-ui, sans-serif'
    }}>
      <div style={{ width: '100%', maxWidth: 420 }}>
        {/* Brand */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{
            width: 56, height: 56, borderRadius: 14,
            background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 18, fontWeight: 800, color: 'white', margin: '0 auto 12px'
          }}>O2C</div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: 0 }}>Customer Portal</h1>
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>MAQ Manufacturing · B2B Ordering System</p>
        </div>

        {/* Card */}
        <div style={{ background: 'white', borderRadius: 16, padding: 32, boxShadow: '0 4px 24px rgba(0,0,0,0.08)' }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: '#0f172a', margin: '0 0 24px' }}>Sign In</h2>
          
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
                Email Address
              </label>
              <input
                type="email"
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                placeholder="billing@yourcompany.com"
                required
                style={{
                  width: '100%', padding: '10px 12px', borderRadius: 8,
                  border: '1.5px solid #e2e8f0', fontSize: 14, outline: 'none',
                  boxSizing: 'border-box', color: '#0f172a',
                }}
              />
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 6 }}>
                Password
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type={showPwd ? 'text' : 'password'}
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  placeholder="••••••••••"
                  required
                  style={{
                    width: '100%', padding: '10px 40px 10px 12px', borderRadius: 8,
                    border: '1.5px solid #e2e8f0', fontSize: 14, outline: 'none',
                    boxSizing: 'border-box', color: '#0f172a',
                  }}
                />
                <button type="button" onClick={() => setShowPwd(s => !s)} style={{
                  position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8'
                }}>
                  {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {error && (
              <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '10px 12px', fontSize: 13, color: '#dc2626', marginBottom: 16 }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{
                width: '100%', padding: '11px', borderRadius: 8, border: 'none',
                background: loading ? '#93c5fd' : 'linear-gradient(135deg, #3b82f6, #6366f1)',
                color: 'white', fontSize: 14, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              }}
            >
              <LogIn size={15} />
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          <div style={{ marginTop: 20, textAlign: 'center', fontSize: 13, color: '#64748b' }}>
            New customer?{' '}
            <Link to="/portal/register" style={{ color: '#3b82f6', fontWeight: 600, textDecoration: 'none' }}>
              Apply for an account →
            </Link>
          </div>
        </div>

        <p style={{ textAlign: 'center', marginTop: 16, fontSize: 12, color: '#94a3b8' }}>
          Need help? Contact <a href="mailto:helpdesk@maqsoftware.com" style={{ color: '#3b82f6' }}>helpdesk@maqsoftware.com</a>
        </p>
      </div>
    </div>
  )
}
