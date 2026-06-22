import React from 'react'
import { Outlet, Navigate } from 'react-router-dom'
import Sidebar from './Sidebar'
import { useAuthStore } from '../store'
import { usePipelineWS } from '../hooks/usePipelineWS'
import { SidebarProvider, useSidebar } from '../context/SidebarContext'

function Inner() {
  const { user } = useAuthStore()
  const { collapsed } = useSidebar()
  usePipelineWS()

  if (!user) return <Navigate to="/login" replace />

  return (
    <div className="app-layout">
      <Sidebar />
      <div className={`main-content${collapsed ? ' sidebar-collapsed' : ''}`}>
        <Outlet />
      </div>
    </div>
  )
}

export default function Layout() {
  return (
    <SidebarProvider>
      <Inner />
    </SidebarProvider>
  )
}
