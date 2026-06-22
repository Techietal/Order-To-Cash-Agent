import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: `${BASE_URL}/api`,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

// Attach JWT token from localStorage on every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("o2c_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── Dedicated portal axios instance (uses portal JWT only) ────────────────────
const portalApiClient = axios.create({
  baseURL: `${BASE_URL}/api`,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

portalApiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("o2c_portal_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authApi = {
  login: (form) => api.post("/auth/login", form),
};

// ── Analytics ─────────────────────────────────────────────────────────────────
export const analyticsApi = {
  kpis: () => api.get("/analytics/kpis"),
  dsoTrend: () => api.get("/analytics/dso-trend"),
  revenueForecast: () => api.get("/analytics/revenue-forecast"),
  demandForecast: (params) => api.get("/analytics/demand-forecast", { params }),
};

// ── Fraud ─────────────────────────────────────────────────────────────────────
export const fraudApi = {
  stats: () => api.get("/fraud/stats"),
  list: (params) => api.get("/fraud", { params }),
};

// ── HITL ──────────────────────────────────────────────────────────────────────
export const hitlApi = {
  stats: () => api.get("/hitl/stats"),
  queue: () => api.get("/hitl/queue"),
  decide: (order_id, body) => api.post(`/hitl/${order_id}/decide`, body),
  paymentQueue: () => api.get("/hitl/payment-queue"),
  decidePayment: (hitl_ref, body) => api.post(`/hitl/payment/${hitl_ref}/decide`, body),
};

// ── AR Ledger ─────────────────────────────────────────────────────────────────
export const arApi = {
  list:           (params) => api.get('/ar-ledger', { params }),
  aging:          ()       => api.get('/ar-ledger/aging-summary'),
  refreshAging:   ()       => api.post('/ar-ledger/refresh-aging'),
  outstanding:    (customerId) => api.get(`/ar-ledger/outstanding/${customerId}`),
  manualPayment:  (arId, payload) => api.post(`/ar-ledger/${arId}/mark-received`, payload),
};

// ── Orders ────────────────────────────────────────────────────────────────────
export const ordersApi = {
  summary: () => api.get("/orders/stats/summary"),
  list: (params) => api.get("/orders", { params }),
  create: (body) => api.post("/orders", body),
  ingest: (body) => api.post("/orders/ingest-email", body),
  fulfill: (orderId, payload) => api.post(`/orders/${orderId}/fulfill`, payload),
  cancel: (orderId) => api.post(`/orders/${orderId}/cancel`),
};

// ── Products ─────────────────────────────────────────────────────────────────
export const productsApi = {
  list: (params) => api.get("/products", { params }),
  get: (skuId) => api.get(`/products/${skuId}`),
};

// ── Inventory ────────────────────────────────────────────────────────────────
export const inventoryApi = {
  stockSummary: () => api.get("/inventory/stock-summary"),
  dashboardSummary: () => api.get("/inventory/dashboard-summary"),
  transactions: (params) => api.get("/inventory/transactions", { params }),
  forecast: (skuId, params) => api.get(`/inventory/forecast/${skuId}`, { params }),
  refreshForecast: (payload) => api.post("/inventory/forecast/refresh", payload),
  incoming: (params) => api.get("/inventory/incoming", { params }),
};

// ── Purchase Orders ──────────────────────────────────────────────────────────
export const purchaseOrdersApi = {
  list: (params) => api.get("/purchase-orders", { params }),
  get: (poId) => api.get(`/purchase-orders/${poId}`),
  create: (payload) => api.post("/purchase-orders", payload),
  confirm: (poId) => api.post(`/purchase-orders/${poId}/confirm`),
  receive: (poId, payload) => api.post(`/purchase-orders/${poId}/receive`, payload),
};

// ── Compliance ────────────────────────────────────────────────────────────────
export const complianceApi = {
  auditLog: (params) => api.get("/compliance/audit-log", { params }),
  ecoaReport: () => api.get("/compliance/ecoa-report"),
};

// ── Cash Application ──────────────────────────────────────────────────────────
export const cashAppApi = {
  stats: () => api.get("/cash-app/match-stats"),
  payments: (params) => api.get("/cash-app/payments", { params }),
  processPayment: (body) => api.post("/cash-app/process-payment", body),
};

// ── Collections ───────────────────────────────────────────────────────────────
export const collectionsApi = {
  overdue: () => api.get("/collections/overdue-invoices"),
  generateDunning: (body) => api.post("/collections/generate-dunning", body),
  list: (params) => api.get("/collections", { params }),
};

// ── Credit Memos ──────────────────────────────────────────────────────────────
export const creditMemosApi = {
  list: (params) => api.get("/credit-memos", { params }),
  summary: (params) => api.get("/credit-memos/summary", { params }),
};


// ── Disputes ──────────────────────────────────────────────────────────────────
export const disputesApi = {
  list: (params) => api.get("/disputes", { params }),
  stats: () => api.get("/disputes/stats"),
};

// ── Invoices ──────────────────────────────────────────────────────────────────
export const invoicesApi = {
  list: (params) => api.get("/invoices", { params }),
  summary: () => api.get("/invoices/stats/summary"),
};

// ── ML Monitor ────────────────────────────────────────────────────────────────
export const mlApi = {
  models: () => api.get("/ml/models"),
};

// ── Customer Portal ───────────────────────────────────────────────────────────
export const portalApi = {
  // Public (no auth needed)
  login: (body) => api.post("/customer-portal/login", body),
  sendOtp: (body) => api.post("/customer-portal/kyc-send-otp", body),
  register: (body) => api.post("/customer-portal/register", body),
  // Authenticated — must use portalApiClient so portal JWT is sent
  products: () => portalApiClient.get("/customer-portal/products"),
  outstanding: () => portalApiClient.get("/customer-portal/outstanding"),
  placeOrder: (body) => portalApiClient.post("/customer-portal/orders", body),
  nlpPreview: (body) => portalApiClient.post("/customer-portal/orders/nlp/preview", body),
  orders: () => portalApiClient.get("/customer-portal/orders"),
  repeatOrder: (order_id, body) =>
    portalApiClient.post(`/customer-portal/orders/${order_id}/repeat`, body),
  payments: () => portalApiClient.get("/customer-portal/payments"),
  disputes: () => portalApiClient.get("/customer-portal/disputes"),
  previewDispute: (body) => portalApiClient.post("/customer-portal/disputes/ai/preview", body),
  createDispute: (body) => portalApiClient.post("/customer-portal/disputes", body, {
    headers: { "Content-Type": "multipart/form-data" },
  }),
  getDispute: (dispute_id) => portalApiClient.get(`/customer-portal/disputes/${dispute_id}`),
  replyDispute: (dispute_id, body) =>
    portalApiClient.post(`/customer-portal/disputes/${dispute_id}/messages`, body, {
      headers: { "Content-Type": "multipart/form-data" },
    }),
  withdrawDispute: (dispute_id, reason) =>
    portalApiClient.post(`/customer-portal/disputes/${dispute_id}/withdraw`, { reason }),
};

// ── Admin Portal Disputes (admin staff view — uses admin api) ─────────────────
export const adminPortalDisputesApi = {
  list: (params) => api.get("/portal-disputes", { params }),
  stats: () => api.get("/portal-disputes/stats"),
  get: (dispute_id) => api.get(`/portal-disputes/${dispute_id}`),
  reply: (dispute_id, body) => api.post(`/portal-disputes/${dispute_id}/messages`, body),
  aiSuggest: (dispute_id) => api.get(`/portal-disputes/${dispute_id}/ai-suggest`),
  decide: (dispute_id, body) => api.patch(`/portal-disputes/${dispute_id}/decision`, body),
};

export default api;
