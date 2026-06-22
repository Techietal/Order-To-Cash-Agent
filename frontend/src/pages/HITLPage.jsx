import React, { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { hitlApi } from "../lib/api"
import { UserCheck, CheckCircle, XCircle, AlertTriangle, Building2, ShieldAlert, CreditCard } from "lucide-react"
import api from "../lib/api"

const kycApi = {
  queue: () => api.get("/hitl/kyc-queue"),
  decide: (id, data) => api.post(`/hitl/kyc/${id}/decide`, data),
}

const creditApi = {
  decisions: (orderId) => api.get(`/compliance/credit-decisions`, { params: { order_id: orderId } }),
}

function getFlagReasons(order) {
  const reasons = []
  const fraud = (+order.fraud_score || 0) * 100
  const ifScore = (+order.isolation_forest_score || 0)
  const amount = +(order.total_amount_inr || order.subtotal_inr || 0)
  const status = order.status || ""
  if (fraud >= 70)  reasons.push(`XGBoost fraud probability ${fraud.toFixed(1)}% — exceeds 70% block threshold (RULE-005)`)
  else if (fraud >= 40) reasons.push(`XGBoost fraud probability ${fraud.toFixed(1)}% — in HITL review band 40–70%`)
  if (ifScore > 0.55) reasons.push(`Isolation Forest anomaly score ${ifScore.toFixed(3)} — statistically unusual vs normal orders`)
  if (amount >= 1000000) reasons.push(`Order value ₹${(amount/100000).toFixed(1)}L — exceeds SOX dual-approval gate (RULE-002)`)
  else if (amount >= 500000) reasons.push(`Order value ₹${(amount/100000).toFixed(1)}L — triggers Credit HITL gate (RULE-004)`)
  if (status === "fraud_review")  reasons.push("Dual-model agreement: both IF and XGBoost flagged — auto-blocked, requires HITL override")
  if (status === "hitl_required") reasons.push("Policy Engine escalated — no auto-approval rule matched this risk profile")
  const flags = (() => { try { return JSON.parse(order.policy_engine_flags || "[]") } catch { return [] } })()
  flags.forEach(f => reasons.push(`Policy Engine flag: ${f}`))
  return reasons.length ? reasons : ["Escalated by Policy Engine — manual review required"]
}

function RiskScoreBar({ label, value, max = 1, dangerThreshold = 0.7, warnThreshold = 0.4, formatFn }) {
  const pct = Math.min((value / max) * 100, 100)
  const color = value >= dangerThreshold * max ? 'var(--danger)' : value >= warnThreshold * max ? 'var(--warning)' : 'var(--success)'
  const display = formatFn ? formatFn(value) : value
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 11 }}>
        <span style={{ color: 'var(--text-muted)' }}>{label}</span>
        <span style={{ fontWeight: 700, color }}>{display}</span>
      </div>
      <div style={{ height: 5, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct.toFixed(0)}%`, height: '100%', background: color, borderRadius: 3, transition: 'width .3s' }} />
      </div>
    </div>
  )
}

export default function HITLPage() {
  const [tab, setTab] = useState("orders")
  const [reviewer, setReviewer] = useState("Finance Controller")
  const [kycNotes, setKycNotes] = useState({})
  const [kycReason, setKycReason] = useState({})
  const [paymentCustomer, setPaymentCustomer] = useState({})
  const [paymentNotes, setPaymentNotes] = useState({})
  const qc = useQueryClient()

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["hitl-queue"],
    queryFn: () => hitlApi.queue().then(r => r.data),
    refetchInterval: 15000,
  })
  const { data: stats } = useQuery({
    queryKey: ["hitl-stats"],
    queryFn: () => hitlApi.stats().then(r => r.data),
  })
  const { data: kycData, isLoading: kycLoading, refetch: kycRefetch } = useQuery({
    queryKey: ["kyc-queue"],
    queryFn: () => kycApi.queue().then(r => r.data),
    refetchInterval: 15000,
  })
  const { data: paymentData, isLoading: paymentLoading, refetch: paymentRefetch } = useQuery({
    queryKey: ["payment-queue"],
    queryFn: () => hitlApi.paymentQueue().then(r => r.data),
    refetchInterval: 15000,
  })

  const decideMut = useMutation({
    mutationFn: ({ id, d }) => hitlApi.decide(id, { decision: d, reviewer, notes: "" }),
    onSuccess: () => { qc.invalidateQueries(["hitl-queue"]); qc.invalidateQueries(["hitl-stats"]) },
  })
  const kycMut = useMutation({
    mutationFn: ({ id, decision, notes, rejection_reason }) =>
      kycApi.decide(id, { decision, reviewer, notes: notes || "", rejection_reason: rejection_reason || "" }),
    onSuccess: () => { qc.invalidateQueries(["kyc-queue"]); qc.invalidateQueries(["hitl-stats"]); kycRefetch() },
  })
  const paymentMut = useMutation({
    mutationFn: ({ hitl_ref, decision, customer_id, invoice_id, notes }) =>
      hitlApi.decidePayment(hitl_ref, { decision, reviewer, customer_id: customer_id || "", invoice_id: invoice_id || "", notes: notes || "" }),
    onSuccess: () => { qc.invalidateQueries(["payment-queue"]); qc.invalidateQueries(["hitl-stats"]); paymentRefetch() },
  })

  const queue = data?.queue || []
  const kycQueue = kycData?.queue || []
  const paymentQueue = paymentData?.queue || []
  const s = stats || {}
  const kycPending = kycQueue.filter(k => k.status === "pending")

  const tabStyle = (active) => ({
    padding: "8px 20px", borderRadius: 6, border: "1px solid", cursor: "pointer", fontWeight: 500,
    fontSize: 13, transition: "all 0.1s",
    background: active ? "var(--brand)" : "var(--surface)",
    borderColor: active ? "var(--brand)" : "var(--border-strong)",
    color: active ? "white" : "var(--text-secondary)",
  })

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">HITL Review Queue</h1>
          <p className="page-subtitle">Human-in-the-Loop - Order Holds and Customer KYC approvals</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input className="form-input" style={{ width: 200 }} placeholder="Reviewer name"
            value={reviewer} onChange={e => setReviewer(e.target.value)} />
          <button className="btn btn-secondary btn-sm" onClick={() => { refetch(); kycRefetch(); paymentRefetch() }}>Refresh</button>
        </div>
      </div>

      <div className="kpi-grid" style={{ marginBottom: 20 }}>
        <div className="kpi-card">
          <div className="kpi-label">Order Holds</div>
          <div className="kpi-value" style={{ color: "var(--warning)" }}>{s.orders?.pending ?? queue.length}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Payment Holds</div>
          <div className="kpi-value" style={{ color: "var(--warning)" }}>{s.payment?.pending ?? paymentQueue.length}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">KYC Pending</div>
          <div className="kpi-value" style={{ color: "var(--violet)" }}>{s.kyc?.pending ?? kycPending.length}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">KYC Approved</div>
          <div className="kpi-value" style={{ color: "var(--success)" }}>{s.kyc?.approved ?? 0}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Orders Resolved</div>
          <div className="kpi-value" style={{ color: "var(--success)" }}>{s.orders?.resolved ?? 0}</div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        <button style={tabStyle(tab === "orders")} onClick={() => setTab("orders")}>
          Order Holds ({queue.length})
        </button>
        <button style={tabStyle(tab === "payments")} onClick={() => setTab("payments")}>
          Payment Holds ({paymentQueue.length})
          {paymentQueue.length > 0 && (
            <span style={{ marginLeft: 6, background: "var(--danger)", color: "white", borderRadius: 10, padding: "1px 6px", fontSize: 10 }}>
              {paymentQueue.length}
            </span>
          )}
        </button>
        <button style={tabStyle(tab === "kyc")} onClick={() => setTab("kyc")}>
          KYC Applications ({kycPending.length})
          {kycPending.length > 0 && (
            <span style={{ marginLeft: 6, background: "var(--danger)", color: "white", borderRadius: 10, padding: "1px 6px", fontSize: 10 }}>
              {kycPending.length}
            </span>
          )}
        </button>
      </div>

      {tab === "orders" && (
        isLoading ? <div className="loading-wrap"><div className="spinner" /></div>
        : queue.length === 0 ? (
          <div className="card"><div className="empty-state">
            <CheckCircle size={32} style={{ color: "var(--success)" }} />
            <div className="empty-title">Queue is clear</div>
            <div className="empty-text">No pending order holds</div>
          </div></div>
        ) : queue.map(order => {
          const reasons = getFlagReasons(order)
          const fraud = (+order.fraud_score || 0) * 100
          const ifScore = +(+order.isolation_forest_score || 0)
          const flagColor = fraud >= 70 ? "var(--danger)" : fraud >= 40 ? "var(--warning)" : "var(--brand)"
          return (
            <div key={order.order_id} className="hitl-box animate-slide" style={{ marginBottom: 14 }}>
              <span className="hitl-box-label">HITL REVIEW REQUIRED</span>
              <div style={{ display: "flex", gap: 16, alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap" }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
                    <UserCheck size={16} style={{ color: "var(--warning)" }} />
                    <span style={{ fontFamily: "JetBrains Mono, monospace", color: "var(--brand)", fontWeight: 700 }}>{order.order_id}</span>
                    <span className="badge badge-amber">{order.status}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{order.company_name || order.customer_id}</span>
                  </div>

                  {/* Why Flagged */}
                  <div style={{ background: "var(--warning-bg)", border: "1px solid var(--warning-border)", borderLeft: `3px solid ${flagColor}`, borderRadius: 6, padding: "10px 14px", marginBottom: 14 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, fontSize: 10, fontWeight: 600, color: "var(--warning)", textTransform: "uppercase" }}>
                      <AlertTriangle size={11} /> Why Flagged
                    </div>
                    {reasons.map((r, i) => (
                      <div key={i} style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.7, paddingLeft: 4 }}>- {r}</div>
                    ))}
                  </div>

                  {/* Risk Score Breakdown */}
                  <div className="grid-2" style={{ gap: 12, marginBottom: 14 }}>
                    <div style={{ background: 'var(--bg-subtle)', borderRadius: 6, padding: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--danger)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <ShieldAlert size={12} /> Fraud Risk Scores
                      </div>
                      <RiskScoreBar label="XGBoost Fraud Probability" value={+order.fraud_score || 0} dangerThreshold={0.7} warnThreshold={0.4} formatFn={v => `${(v*100).toFixed(1)}%`} />
                      <RiskScoreBar label="Isolation Forest Anomaly" value={ifScore} dangerThreshold={0.7} warnThreshold={0.55} formatFn={v => v.toFixed(3)} />
                    </div>
                    <div style={{ background: 'var(--bg-subtle)', borderRadius: 6, padding: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--teal)', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                        <CreditCard size={12} /> Order Details
                      </div>
                      {[['Amount', `₹${(+(order.total_amount_inr || 0)).toLocaleString('en-IN')}`], ['Channel', order.channel], ['Credit Tier', order.credit_tier || '—'], ['SKU', order.sku_id || '—']].map(([l, v]) => (
                        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 12 }}>
                          <span style={{ color: 'var(--text-muted)' }}>{l}</span>
                          <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{v || '—'}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, flexShrink: 0, flexDirection: "column", minWidth: 100 }}>
                  <button className="btn btn-success btn-sm" onClick={() => decideMut.mutate({ id: order.order_id, d: "credit_approved" })} disabled={decideMut.isPending}>
                    <CheckCircle size={13} /> Approve
                  </button>
                  <button className="btn btn-danger btn-sm" onClick={() => decideMut.mutate({ id: order.order_id, d: "cancelled" })} disabled={decideMut.isPending}>
                    <XCircle size={13} /> Reject
                  </button>
                </div>
              </div>
            </div>
          )
        })
      )}

      {tab === "kyc" && (
        kycLoading ? <div className="loading-wrap"><div className="spinner" /></div>
        : kycQueue.length === 0 ? (
          <div className="card"><div className="empty-state">
            <CheckCircle size={32} style={{ color: "var(--success)" }} />
            <div className="empty-title">No KYC applications</div>
            <div className="empty-text">New customer registrations will appear here</div>
          </div></div>
        ) : kycQueue.map(kyc => (
          <div key={kyc.kyc_id} className="card" style={{ marginBottom: 14, borderLeft: `3px solid ${kyc.status === "approved" ? "var(--success)" : kyc.status === "rejected" ? "var(--danger)" : "var(--violet)"}` }}>
            <div style={{ display: "flex", gap: 16, alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap" }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
                  <Building2 size={16} style={{ color: "var(--violet)" }} />
                  <span style={{ fontWeight: 700, color: "var(--text-primary)" }}>{kyc.company_name}</span>
                  <span className="badge" style={{ background: kyc.status === "pending" ? "var(--violet-bg)" : kyc.status === "approved" ? "var(--success-bg)" : "var(--danger-bg)", color: kyc.status === "pending" ? "var(--violet)" : kyc.status === "approved" ? "var(--success)" : "var(--danger)" }}>
                    {kyc.status.toUpperCase()}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{kyc.kyc_id}</span>
                </div>
                <div className="grid-4" style={{ gap: 10, marginBottom: 10 }}>
                  {[["Contact", kyc.contact_name], ["Email", kyc.email], ["GSTIN", kyc.gstin], ["PAN", kyc.pan_number], ["Business Type", kyc.business_type], ["State", kyc.state], ["City", kyc.city], ["Turnover", kyc.annual_turnover || "-"]].map(([l, v]) => (
                    <div key={l}>
                      <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 2 }}>{l}</div>
                      <div style={{ fontSize: 12, fontWeight: 500, color: "var(--text-primary)" }}>{v || "-"}</div>
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                  Submitted: {new Date(kyc.submitted_at).toLocaleString("en-IN")}
                </div>
                {kyc.status === "pending" && (
                  <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
                    <input placeholder="Review notes (optional)" value={kycNotes[kyc.kyc_id] || ""}
                      onChange={e => setKycNotes(n => ({ ...n, [kyc.kyc_id]: e.target.value }))}
                      className="form-input" style={{ flex: 1, fontSize: 12 }} />
                    <input placeholder="Rejection reason (if rejecting)" value={kycReason[kyc.kyc_id] || ""}
                      onChange={e => setKycReason(n => ({ ...n, [kyc.kyc_id]: e.target.value }))}
                      className="form-input" style={{ flex: 1, fontSize: 12 }} />
                  </div>
                )}
              </div>
              {kyc.status === "pending" && (
                <div style={{ display: "flex", gap: 8, flexShrink: 0, flexDirection: "column", minWidth: 110 }}>
                  <button className="btn btn-success btn-sm"
                    onClick={() => kycMut.mutate({ id: kyc.kyc_id, decision: "approved", notes: kycNotes[kyc.kyc_id] || "", rejection_reason: "" })}
                    disabled={kycMut.isPending}>
                    <CheckCircle size={13} /> Approve
                  </button>
                  <button className="btn btn-danger btn-sm"
                    onClick={() => kycMut.mutate({ id: kyc.kyc_id, decision: "rejected", notes: kycNotes[kyc.kyc_id] || "", rejection_reason: kycReason[kyc.kyc_id] || "Did not meet onboarding criteria" })}
                    disabled={kycMut.isPending}>
                    <XCircle size={13} /> Reject
                  </button>
                </div>
              )}
            </div>
          </div>
        ))
      )}
      {tab === "payments" && (
        paymentLoading ? <div className="loading-wrap"><div className="spinner" /></div>
        : paymentQueue.length === 0 ? (
          <div className="card"><div className="empty-state">
            <CheckCircle size={32} style={{ color: "var(--success)" }} />
            <div className="empty-title">Queue is clear</div>
            <div className="empty-text">No pending payment holds</div>
          </div></div>
        ) : paymentQueue.map(hold => (
          <div key={hold.hitl_ref} className="hitl-box animate-slide" style={{ marginBottom: 14 }}>
            <span className="hitl-box-label" style={{ background: "var(--surface)", color: "var(--warning)" }}>UNREGISTERED SENDER</span>
            <div style={{ display: "flex", gap: 16, alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap" }}>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
                  <AlertTriangle size={16} style={{ color: "var(--warning)" }} />
                  <span style={{ fontFamily: "monospace", color: "var(--text-primary)", fontWeight: 700 }}>{hold.hitl_ref}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>From: <span style={{ color: 'var(--text-primary)' }}>{hold.email}</span></span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Target Invoice: <span style={{ color: 'var(--text-primary)' }}>{hold.invoice}</span></span>
                </div>

                <div             style={{ background: 'var(--bg-subtle)', borderRadius: 6, padding: 12, marginBottom: 14 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase' }}>
                    Remittance Text
                  </div>
                  <pre style={{ fontSize: 12, color: "var(--text-secondary)", whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>
                    {hold.remittance_text || "No remittance text provided."}
                  </pre>
                  <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-secondary)" }}>
                    <span style={{ color: "var(--text-muted)" }}>Extracted Token:</span> <span style={{ color: "var(--text-primary)", fontWeight: 700 }}>{hold.payment_token || "None"}</span>
                  </div>
                </div>

                <div style={{ display: "flex", gap: 10 }}>
                  <input placeholder="Assign to Customer ID (e.g. CUST-123)" value={paymentCustomer[hold.hitl_ref] || ""}
                    onChange={e => setPaymentCustomer(n => ({ ...n, [hold.hitl_ref]: e.target.value }))}
                    className="form-input" style={{ flex: 1, fontSize: 12 }} />
                  <input placeholder="Review notes or rejection reason" value={paymentNotes[hold.hitl_ref] || ""}
                    onChange={e => setPaymentNotes(n => ({ ...n, [hold.hitl_ref]: e.target.value }))}
                    className="form-input" style={{ flex: 1, fontSize: 12 }} />
                </div>
              </div>

              <div style={{ display: "flex", gap: 8, flexShrink: 0, flexDirection: "column", minWidth: 100 }}>
                <button className="btn btn-success btn-sm"
                  onClick={() => paymentMut.mutate({ hitl_ref: hold.hitl_ref, decision: "approved", customer_id: paymentCustomer[hold.hitl_ref], invoice_id: hold.invoice, notes: paymentNotes[hold.hitl_ref] })}
                  disabled={paymentMut.isPending || !paymentCustomer[hold.hitl_ref]}>
                  <CheckCircle size={13} /> Approve
                </button>
                <button className="btn btn-danger btn-sm"
                  onClick={() => paymentMut.mutate({ hitl_ref: hold.hitl_ref, decision: "rejected", notes: paymentNotes[hold.hitl_ref] })}
                  disabled={paymentMut.isPending}>
                  <XCircle size={13} /> Reject
                </button>
              </div>
            </div>
          </div>
        ))
      )}

    </div>
  )
}
