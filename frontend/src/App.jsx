import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'

// Staff layout & pages
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import OrdersPage from './pages/OrdersPage'
import InvoicesPage from './pages/InvoicesPage'
import ARLedgerPage from './pages/ARLedgerPage'
import FraudPage from './pages/FraudPage'
import HITLPage from './pages/HITLPage'
import CollectionsPage from './pages/CollectionsPage'
import DisputesPage from './pages/DisputesPage'
import AnalyticsPage from './pages/AnalyticsPage'
import CompliancePage from './pages/CompliancePage'
import MLMonitorPage from './pages/MLMonitorPage'
import Customer360Page from './pages/Customer360Page'
import ForbiddenPage from './pages/ForbiddenPage'
import HumanActionLogPage from './pages/HumanActionLogPage'
import CreditHistoryPage from './pages/CreditHistoryPage'
import InventoryDashboardPage from './pages/InventoryDashboardPage'
import ProductsPage from './pages/ProductsPage'
import ProductDetailPage from './pages/ProductDetailPage'
import PurchaseOrdersPage from './pages/PurchaseOrdersPage'

// Role guards
import { RoleGuard } from './components/RoleGuard'

// Customer Portal layout & pages
import PortalLayout from './components/PortalLayout'
import PortalLoginPage from './pages/PortalLoginPage'
import PortalRegisterPage from './pages/PortalRegisterPage'
import PortalDashboardPage from './pages/PortalDashboardPage'
import PortalOrdersPage from './pages/PortalOrdersPage'
import PortalPaymentsPage from './pages/PortalPaymentsPage'
import PortalOutstandingPage from './pages/PortalOutstandingPage'
import PortalDisputesPage from './pages/PortalDisputesPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Staff login */}
          <Route path="/login" element={<LoginPage />} />

          {/* 403 Forbidden */}
          <Route path="/403" element={<ForbiddenPage />} />

          {/* Customer Portal — no staff auth needed */}
          <Route path="/portal/login"    element={<PortalLoginPage />} />
          <Route path="/portal/register" element={<PortalRegisterPage />} />
          <Route element={<PortalLayout />}>
            <Route path="/portal/dashboard"   element={<PortalDashboardPage />} />
            <Route path="/portal/orders"      element={<PortalOrdersPage />} />
            <Route path="/portal/payments"    element={<PortalPaymentsPage />} />
            <Route path="/portal/outstanding" element={<PortalOutstandingPage />} />
            <Route path="/portal/disputes"    element={<PortalDisputesPage />} />
            <Route path="/portal" element={<Navigate to="/portal/login" replace />} />
          </Route>

          {/* Staff dashboard — all routes gated by role */}
          <Route element={<Layout />}>
            {/* Dashboard: admin + controller only (narrower roles have a dedicated landing page) */}
            <Route index element={
              <RoleGuard allowed={['admin', 'controller']}>
                <DashboardPage />
              </RoleGuard>
            } />

            {/* Orders: admin/controller/inventory_manager + dispute_manager read-only */}
            <Route path="/orders" element={
              <RoleGuard allowed={['admin', 'dispute_manager', 'controller', 'inventory_manager']}>
                <OrdersPage />
              </RoleGuard>
            } />

            <Route path="/inventory" element={
              <RoleGuard allowed={['admin', 'controller', 'inventory_manager']}>
                <InventoryDashboardPage />
              </RoleGuard>
            } />
            <Route path="/products" element={
              <RoleGuard allowed={['admin', 'controller', 'inventory_manager']}>
                <ProductsPage />
              </RoleGuard>
            } />
            <Route path="/products/:skuId" element={
              <RoleGuard allowed={['admin', 'controller', 'inventory_manager']}>
                <ProductDetailPage />
              </RoleGuard>
            } />
            <Route path="/purchase-orders" element={
              <RoleGuard allowed={['admin', 'controller', 'inventory_manager']}>
                <PurchaseOrdersPage />
              </RoleGuard>
            } />

            {/* Invoices: admin + dispute_manager */}
            <Route path="/invoices" element={
              <RoleGuard allowed={['admin', 'dispute_manager']}>
                <InvoicesPage />
              </RoleGuard>
            } />

            {/* AR Ledger: all 4 roles (write gated per action) */}
            <Route path="/ar-ledger" element={
              <RoleGuard allowed={['admin', 'dispute_manager', 'collections_analyst', 'controller']}>
                <ARLedgerPage />
              </RoleGuard>
            } />

            {/* Fraud Detection: admin + controller */}
            <Route path="/fraud" element={
              <RoleGuard allowed={['admin', 'controller']}>
                <FraudPage />
              </RoleGuard>
            } />

            {/* HITL Queue: admin + controller */}
            <Route path="/hitl" element={
              <RoleGuard allowed={['admin', 'controller']}>
                <HITLPage />
              </RoleGuard>
            } />

            {/* Collections: admin + collections_analyst */}
            <Route path="/collections" element={
              <RoleGuard allowed={['admin', 'collections_analyst']}>
                <CollectionsPage />
              </RoleGuard>
            } />

            {/* Disputes: admin + dispute_manager */}
            <Route path="/disputes" element={
              <RoleGuard allowed={['admin', 'dispute_manager']}>
                <DisputesPage />
              </RoleGuard>
            } />


            {/* Analytics: admin + controller + collections_analyst (own-metrics) */}
            <Route path="/analytics" element={
              <RoleGuard allowed={['admin', 'controller', 'collections_analyst']}>
                <AnalyticsPage />
              </RoleGuard>
            } />

            {/* Compliance Audit: admin + controller */}
            <Route path="/compliance" element={
              <RoleGuard allowed={['admin', 'controller']}>
                <CompliancePage />
              </RoleGuard>
            } />

            {/* Human Action Log (new): admin + controller */}
            <Route path="/human-action-log" element={
              <RoleGuard allowed={['admin', 'controller']}>
                <HumanActionLogPage />
              </RoleGuard>
            } />

            {/* ML Monitor: admin only */}
            <Route path="/ml-monitor" element={
              <RoleGuard allowed={['admin']}>
                <MLMonitorPage />
              </RoleGuard>
            } />

            {/* Customer 360: admin + dispute_manager + collections_analyst */}
            <Route path="/customer-360" element={
              <RoleGuard allowed={['admin', 'dispute_manager', 'collections_analyst']}>
                <Customer360Page />
              </RoleGuard>
            } />

            {/* Credit History: admin + dispute_manager + collections_analyst */}
            <Route path="/credit-history" element={
              <RoleGuard allowed={['admin', 'dispute_manager', 'collections_analyst']}>
                <CreditHistoryPage />
              </RoleGuard>
            } />

            {/* /order-lifecycle removed — merged into OrdersPage popup modal (Section 3) */}
          </Route>

          <Route path="*" element={<Navigate to="/403" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
