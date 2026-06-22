import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store'

/**
 * RoleGuard — Route-level role enforcement.
 * Wraps <Route> elements to redirect unauthorized users to /403.
 *
 * Usage:
 *   <RoleGuard allowed={['admin', 'dispute_manager']}>
 *     <DisputesPage />
 *   </RoleGuard>
 */
export function RoleGuard({ allowed, children }) {
  const { user } = useAuthStore()
  if (!user || !allowed.includes(user.role)) {
    return <Navigate to="/403" replace />
  }
  return children
}

/**
 * ActionGuard — Action-level role enforcement inside pages/modals.
 * Renders children if the user has the required role; otherwise renders fallback (default: null).
 *
 * Usage:
 *   <ActionGuard allowed={['admin', 'dispute_manager']}>
 *     <button>Resolve & Credit</button>
 *   </ActionGuard>
 *
 *   <ActionGuard allowed={['admin']} fallback={<span className="badge badge-gray">View Only</span>}>
 *     <button>Create Order</button>
 *   </ActionGuard>
 */
export function ActionGuard({ allowed, children, fallback = null }) {
  const { user } = useAuthStore()
  if (!user || !allowed.includes(user.role)) {
    return fallback
  }
  return children
}

/**
 * useHasRole — hook for imperative role checks inside component logic.
 *
 * Usage:
 *   const canResolve = useHasRole(['admin', 'dispute_manager'])
 */
export function useHasRole(allowed) {
  const { user } = useAuthStore()
  return !!(user && allowed.includes(user.role))
}

/**
 * ROLE_HOME — landing page per role, used for post-login redirect and 403 "Go Home" button.
 */
export const ROLE_HOME = {
  admin:               '/',
  controller:          '/',
  dispute_manager:     '/disputes',
  collections_analyst: '/collections',
  inventory_manager:   '/inventory',
}

export default RoleGuard
