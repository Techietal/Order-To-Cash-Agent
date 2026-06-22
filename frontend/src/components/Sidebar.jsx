import React from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, ShoppingCart, FileText, BookOpen, ShieldAlert,
  UserCheck, Users, Scale, BarChart2, ScrollText, LogOut,
  User, Cpu, Shield, History, ChevronLeft, ChevronRight, Boxes, PackageSearch, Truck
} from 'lucide-react'
import { useAuthStore, usePipelineStore } from '../store'
import { useSidebar } from '../context/SidebarContext'

const ROLE_LABELS = {
  admin: 'ADMIN',
  controller: 'CONTROLLER',
  dispute_manager: 'DISPUTES MANAGER',
  collections_analyst: 'COLLECTIONS ANALYST',
  inventory_manager: 'INVENTORY MANAGER',
}

/**
 * Collapsible sidebar rail.
 * - Expanded (240px): shows icon + label + section headers
 * - Collapsed (58px): shows icons only with tooltip titles
 * Each nav item declares `roles` — filtered for the logged-in role.
 */
const NAV_ITEMS = [
  {
    section: 'Main',
    items: [
      { to: '/',            icon: LayoutDashboard, label: 'Dashboard',        roles: ['admin', 'controller'] },
      { to: '/orders',      icon: ShoppingCart,    label: 'Orders',           roles: ['admin', 'dispute_manager', 'controller', 'inventory_manager'] },
      { to: '/invoices',    icon: FileText,        label: 'Invoices',         roles: ['admin', 'dispute_manager'] },
      { to: '/ar-ledger',   icon: BookOpen,        label: 'AR Ledger',        roles: ['admin', 'dispute_manager', 'collections_analyst', 'controller'] },
    ]
  },
  {
    section: 'Risk & Control',
    items: [
      { to: '/fraud',       icon: ShieldAlert,     label: 'Fraud Detection',  roles: ['admin', 'controller'] },
      { to: '/hitl',        icon: UserCheck,       label: 'HITL Queue',       roles: ['admin', 'controller'], badge: 'hitl' },
      { to: '/disputes',    icon: Scale,           label: 'Disputes',         roles: ['admin', 'dispute_manager'] },
    ]
  },
  {
    section: 'Inventory',
    items: [
      { to: '/inventory',       icon: Boxes,         label: 'Inventory Dashboard', roles: ['admin', 'controller', 'inventory_manager'] },
      { to: '/products',        icon: PackageSearch, label: 'Products',            roles: ['admin', 'controller', 'inventory_manager'] },
      { to: '/purchase-orders', icon: Truck,         label: 'Purchase Orders',     roles: ['admin', 'controller', 'inventory_manager'] },
    ]
  },
  {
    section: 'Collections',
    items: [
      { to: '/collections', icon: Users, label: 'Collections', roles: ['admin', 'collections_analyst'] },
    ]
  },

  {
    section: 'Intelligence',
    items: [
      { to: '/analytics',      icon: BarChart2,  label: 'Analytics',         roles: ['admin', 'controller', 'collections_analyst'] },
      { to: '/customer-360',   icon: User,       label: 'Customer 360',      roles: ['admin', 'dispute_manager', 'collections_analyst'] },
      { to: '/credit-history', icon: History,    label: 'Credit History',    roles: ['admin', 'dispute_manager', 'collections_analyst'] },
    ]
  },
  {
    section: 'Control Room',
    items: [
      { to: '/compliance',       icon: ScrollText, label: 'Compliance Audit', roles: ['admin', 'controller'] },
      { to: '/human-action-log', icon: Shield,     label: 'Human Action Log', roles: ['admin', 'controller'] },
      { to: '/ml-monitor',       icon: Cpu,        label: 'ML Monitor',       roles: ['admin'] },
    ]
  },
]

export default function Sidebar() {
  const { user, logout } = useAuthStore()
  const { hitlCount, connected } = usePipelineStore()
  const navigate = useNavigate()
  const role = user?.role || ''
  const { collapsed, setCollapsed } = useSidebar()

  const W = collapsed ? 58 : 240

  const visibleSections = NAV_ITEMS
    .map(s => ({ ...s, items: s.items.filter(item => item.roles.includes(role)) }))
    .filter(s => s.items.length > 0)

  return (
    <aside style={{
      width: W, minWidth: W,
      background: 'var(--surface)',
      borderRight: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column',
      position: 'fixed', top: 0, left: 0, bottom: 0,
      zIndex: 100, overflowY: 'auto', overflowX: 'hidden',
      scrollbarWidth: 'none',
      transition: 'width 0.2s ease',
      boxShadow: 'var(--shadow-2)',
    }}>

      {/* Logo row */}
      <div style={{
        padding: collapsed ? '0' : '0 16px',
        height: 48,
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center',
        gap: collapsed ? 0 : 10,
        justifyContent: collapsed ? 'center' : 'flex-start',
        flexShrink: 0, paddingLeft: collapsed ? 0 : 16, paddingRight: collapsed ? 0 : 16,
      }}>
        <div style={{
          width: 30, height: 30,
          background: 'var(--brand)',
          borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 11, color: 'white', flexShrink: 0, letterSpacing: '.02em',
        }}>O2C</div>
        {!collapsed && (
          <div style={{ overflow: 'hidden' }}>
            <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>O2C Agent</div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>v2.0</div>
          </div>
        )}
      </div>

      {/* Nav sections */}
      <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'none', paddingBottom: 8 }}>
        {visibleSections.map((section, si) => (
          <div key={section.section}>
            {/* Section label — hidden when collapsed */}
            {!collapsed && (
              <div style={{
                fontSize: 10, fontWeight: 600, color: 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '.08em',
                padding: si === 0 ? '10px 10px 4px' : '12px 10px 4px',
              }}>
                {section.section}
              </div>
            )}
            {/* Zone divider between sections when collapsed */}
            {collapsed && si > 0 && (
              <div style={{ height: 1, background: 'var(--border)', margin: '4px 8px' }} />
            )}
            {section.items.map(({ to, icon: Icon, label, badge }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                title={collapsed ? label : undefined}
                style={({ isActive }) => ({
                  display: 'flex',
                  alignItems: 'center',
                  gap: collapsed ? 0 : 8,
                  justifyContent: collapsed ? 'center' : 'flex-start',
                  padding: collapsed ? '8px 0' : '7px 10px',
                  margin: collapsed ? '1px 6px' : '1px 8px',
                  borderRadius: 6,
                  color: isActive ? 'var(--brand)' : 'var(--text-secondary)',
                  background: isActive ? 'var(--brand-light)' : 'transparent',
                  textDecoration: 'none',
                  fontSize: 13,
                  fontWeight: isActive ? 500 : 400,
                  cursor: 'pointer',
                  transition: 'all .1s',
                  position: 'relative',
                  boxShadow: isActive ? 'inset 3px 0 0 var(--brand)' : 'none',
                })}
              >
                {({ isActive }) => (
                  <>
                    <Icon size={15} style={{ flexShrink: 0 }} />
                    {!collapsed && <span style={{ overflow: 'hidden', whiteSpace: 'nowrap' }}>{label}</span>}
                    {badge === 'hitl' && hitlCount > 0 && (
                      <span style={{
                        marginLeft: 'auto',
                        background: 'var(--danger)', color: 'white',
                        fontSize: 10, fontWeight: 600, padding: '1px 6px',
                        borderRadius: 10, minWidth: 18, textAlign: 'center',
                        display: collapsed ? 'none' : 'block',
                      }}>
                        {hitlCount}
                      </span>
                    )}
                    {badge === 'hitl' && hitlCount > 0 && collapsed && (
                      <span style={{
                        position: 'absolute', top: 3, right: 3,
                        width: 8, height: 8, borderRadius: '50%',
                        background: 'var(--danger)',
                      }} />
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </div>
        ))}
      </div>

      {/* Bottom — collapse toggle + user + WS status */}
      <div style={{ borderTop: '1px solid var(--border)', flexShrink: 0, background: 'var(--surface)' }}>
        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(c => !c)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            width: '100%', padding: '8px 0',
            background: 'none', border: 'none', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
            color: 'var(--text-muted)', fontSize: 11, transition: 'all .1s',
          }}
        >
          {collapsed ? <ChevronRight size={14} /> : <><ChevronLeft size={14} /><span style={{ whiteSpace: 'nowrap' }}>Collapse</span></>}
        </button>

        {/* WS status */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'flex-start',
          gap: 6, padding: collapsed ? '6px 0' : '6px 16px',
        }}>
          <div style={{
            width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
            background: connected ? 'var(--success)' : 'var(--danger)',
          }} />
          {!collapsed && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{connected ? 'Live' : 'Offline'}</span>}
        </div>

        {/* User row */}
        {user && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'flex-start',
            gap: collapsed ? 0 : 8,
            padding: collapsed ? '8px 0 12px' : '6px 12px 12px',
          }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: 'var(--brand)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, fontWeight: 700, color: 'white', flexShrink: 0,
            }}>
              {user.name?.charAt(0) || 'U'}
            </div>
            {!collapsed && (
              <>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{user.name}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase' }}>{ROLE_LABELS[user.role] || user.role}</div>
                </div>
                <button
                  className="btn-icon"
                  onClick={() => { logout(); navigate('/login') }}
                  title="Logout"
                  style={{ padding: 5, flexShrink: 0 }}
                >
                  <LogOut size={13} />
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
