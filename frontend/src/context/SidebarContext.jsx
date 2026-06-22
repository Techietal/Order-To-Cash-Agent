import React, { createContext, useContext, useState } from 'react'

const SidebarCtx = createContext({ collapsed: false, setCollapsed: () => {} })

export function SidebarProvider({ children }) {
  const [collapsed, setCollapsed] = useState(false)
  return <SidebarCtx.Provider value={{ collapsed, setCollapsed }}>{children}</SidebarCtx.Provider>
}

export function useSidebar() { return useContext(SidebarCtx) }
