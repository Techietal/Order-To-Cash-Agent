import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export const useAuthStore = create(
  persist(
    (set) => ({
      user: null,
      token: null,
      setAuth: (user, token) => {
        localStorage.setItem('o2c_token', token)
        set({ user, token })
      },
      logout: () => {
        localStorage.removeItem('o2c_token')
        set({ user: null, token: null })
      },
    }),
    { name: 'o2c-auth' }
  )
)

export const usePipelineStore = create((set) => ({
  events: [],
  connected: false,
  hitlCount: 0,
  addEvent: (e) => set((s) => ({ events: [e, ...s.events].slice(0, 100) })),
  setConnected: (connected) => set({ connected }),
  setHitlCount: (hitlCount) => set({ hitlCount }),
}))

// Separate customer portal store
export const usePortalStore = create(
  persist(
    (set) => ({
      customer: null,
      portalToken: null,
      setPortalAuth: (customer, token) => {
        localStorage.setItem('o2c_portal_token', token)
        set({ customer, portalToken: token })
      },
      logout: () => {
        localStorage.removeItem('o2c_portal_token')
        set({ customer: null, portalToken: null })
      },
    }),
    { name: 'o2c-portal-auth' }
  )
)
