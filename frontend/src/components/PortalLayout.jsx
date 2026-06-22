import React from 'react'
import { NavLink, useNavigate, Outlet } from 'react-router-dom'
import { ShoppingCart, CreditCard, AlertCircle, LogOut, LayoutDashboard, MessageSquare } from 'lucide-react'
import { usePortalStore } from '../store'

export default function PortalLayout() {
  const { customer, logout } = usePortalStore()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/portal/login')
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc', fontFamily: 'Inter, system-ui, sans-serif' }}>
      {/* Top Nav */}
      <nav style={{
        background: 'white', borderBottom: '1px solid #e2e8f0',
        display: 'flex', alignItems: 'center', padding: '0 32px',
        height: 60, gap: 32, position: 'sticky', top: 0, zIndex: 100,
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)'
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginRight: 16 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8,
            background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 800, color: 'white', letterSpacing: '-0.5px'
          }}>O2C</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', lineHeight: 1 }}>Customer Portal</div>
            <div style={{ fontSize: 10, color: '#94a3b8', lineHeight: 1.2 }}>MAQ Manufacturing</div>
          </div>
        </div>

        {/* Nav Links */}
        {[
          { to: '/portal/dashboard', label: 'Place Order',   icon: LayoutDashboard },
          { to: '/portal/orders',    label: 'My Orders',     icon: ShoppingCart },
          { to: '/portal/payments',  label: 'Payments',      icon: CreditCard },
          { to: '/portal/outstanding', label: 'Outstanding', icon: AlertCircle },
          { to: '/portal/disputes', label: 'Disputes', icon: MessageSquare },
        ].map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            style={({ isActive }) => ({
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 13, fontWeight: 500, padding: '4px 0',
              color: isActive ? '#3b82f6' : '#64748b',
              borderBottom: isActive ? '2px solid #3b82f6' : '2px solid transparent',
              textDecoration: 'none', transition: 'all 0.15s',
            })}
          >
            <Icon size={14} />
            {label}
          </NavLink>
        ))}

        {/* Right side user info */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          {customer && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 32, height: 32, borderRadius: '50%',
                background: 'linear-gradient(135deg, #3b82f6, #6366f1)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 12, fontWeight: 700, color: 'white'
              }}>
                {customer.company_name?.charAt(0) || 'C'}
              </div>
              <div style={{ lineHeight: 1.3 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#0f172a' }}>{customer.company_name}</div>
                <div style={{ fontSize: 10, color: '#94a3b8' }}>Tier {customer.credit_tier || 'B'}</div>
              </div>
            </div>
          )}
          <button
            onClick={handleLogout}
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              background: 'none', border: '1px solid #e2e8f0', borderRadius: 6,
              padding: '5px 10px', fontSize: 12, color: '#64748b', cursor: 'pointer'
            }}
          >
            <LogOut size={12} /> Logout
          </button>
        </div>
      </nav>

      {/* Page content */}
      <main style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>
        <Outlet />
      </main>
    </div>
  )
}
