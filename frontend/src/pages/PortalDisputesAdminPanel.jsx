import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle, CheckCircle, CreditCard, FileText, MessageSquare,
  Paperclip, RefreshCcw, Send, ShieldCheck, Sparkles, X, Mail
} from 'lucide-react'
import api, { adminPortalDisputesApi } from '../lib/api'

const FINAL_STATUSES = ['resolved', 'rejected', 'closed', 'withdrawn']

const SAMPLE_EMAILS = [
  {
    label: 'Damaged Goods',
    text: `Subject: Dispute for Invoice INV-001\n\nHello,\n\nWe are writing to dispute Invoice INV-001 for ₹1,50,000.\nThe Industrial Motors received on 1st May were damaged during transit — 8 out of 20 units were found broken and non-functional.\n\nWe are claiming a credit note for ₹60,000 against this invoice.\n\nPlease resolve this at the earliest.\n\nRegards,\nRajesh Kumar\nAcme Corp`,
  },
  {
    label: 'Pricing Error',
    text: `Subject: Overcharge on Invoice INV-001\n\nHi team,\n\nWe noticed a pricing error on Invoice INV-001. The agreed rate for SKU-001 was ₹12,000 per unit but we were billed ₹15,000 per unit.\n\nThe overcharge amounts to ₹60,000 (20 units × ₹3,000 excess). Please issue a corrected invoice.\n\nThanks,\nFinance Team, Acme Corp`,
  },
  {
    label: 'Short Shipment',
    text: `Subject: Short Shipment — INV-001\n\nDear Sir,\n\nWe placed an order for 20 Industrial Motors (INV-001, ₹1,50,000) but only 15 units were delivered.\n5 units are missing from the shipment. We are disputing ₹37,500 for the undelivered items.\n\nPlease arrange for immediate delivery or issue a credit note.\n\nBest,\nAcme Corp Procurement`,
  },
]

const QUICK_PROMPTS = [
  'Please send photographs of the damaged goods along with a signed delivery receipt.',
  'Kindly provide the original purchase order and agreed price list for this shipment.',
  'Please share the proof of delivery (POD) signed by your receiving team.',
  'We need a copy of the inspection report showing the damaged/missing units.',
  'Please provide the bank remittance reference and payment date for this invoice.',
]

function badgeClass(status) {
  if (status === 'pending_admin') return 'badge badge-amber'
  if (status === 'awaiting_customer') return 'badge badge-blue'
  if (status === 'resolved') return 'badge badge-green'
  if (status === 'rejected') return 'badge badge-red'
  return 'badge badge-gray'
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function nextActorLabel(d) {
  if (d.status === 'withdrawn') return 'Withdrawn'
  if (FINAL_STATUSES.includes(d.status)) return 'Final'
  if (d.next_actor === 'admin') return 'Admin action required'
  if (d.next_actor === 'customer') return 'Waiting for customer'
  return '—'
}

// ── Request Info Modal ─────────────────────────────────────────────────────────
function RequestInfoModal({ dispute, onClose, onSent }) {
  const qc = useQueryClient()
  const [message, setMessage] = useState('')
  const [sent, setSent] = useState(false)

  const mut = useMutation({
    mutationFn: () => adminPortalDisputesApi.reply(dispute.dispute_id, message),
    onSuccess: () => {
      setSent(true)
      qc.invalidateQueries({ queryKey: ['admin-portal-disputes'] })
      qc.invalidateQueries({ queryKey: ['admin-portal-dispute-stats'] })
      onSent?.()
    },
  })

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, width: '100%', maxWidth: 560, boxShadow: 'var(--shadow-32)', color: 'var(--text-primary)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', borderRadius: '12px 12px 0 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <MessageSquare size={16} color="var(--warning)" />
            <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>Request More Information — {dispute.dispute_id}</span>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)' }}><X size={16} /></button>
        </div>

        <div style={{ padding: '16px 18px' }}>
          {sent ? (
            <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--success)' }}>
              <CheckCircle size={40} style={{ marginBottom: 10 }} />
              <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 6 }}>Message sent to customer!</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>The customer will see this in their disputes portal and must reply before Admin can act again.</div>
              <button onClick={onClose} style={{ marginTop: 16, background: 'var(--bg-subtle)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 8, padding: '7px 16px', cursor: 'pointer' }}>Close</button>
            </div>
          ) : (
            <>
              <div style={{ padding: '10px 12px', background: 'var(--warning-bg)', border: '1px solid var(--warning-border)', borderRadius: 8, marginBottom: 14, fontSize: 12, color: 'var(--text-primary)' }}>
                <strong>Customer:</strong> {dispute.company_name} · <strong>Type:</strong> {(dispute.dispute_type || '').replace(/_/g, ' ')} · <strong>Invoice:</strong> {dispute.invoice_id || '—'}
              </div>
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>⚡ Quick prompts:</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {QUICK_PROMPTS.map((p, i) => (
                    <button key={i} onClick={() => setMessage(p)} style={{ fontSize: 10, background: 'var(--bg-subtle)', border: '1px solid var(--border)', color: 'var(--text-secondary)', borderRadius: 6, padding: '4px 8px', cursor: 'pointer', textAlign: 'left', whiteSpace: 'normal', lineHeight: 1.4 }}>
                      {p.slice(0, 48)}…
                    </button>
                  ))}
                </div>
              </div>
              <div style={{ marginBottom: 14 }}>
                <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4, textTransform: 'uppercase' }}>Message to Customer *</label>
                <textarea rows={5} style={{ width: '100%', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', color: 'var(--text-primary)', fontSize: 13, resize: 'vertical' }}
                  placeholder="e.g. Please send photographs of the damaged goods..." value={message} onChange={e => setMessage(e.target.value)} />
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button onClick={onClose} style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 8, padding: '7px 14px', cursor: 'pointer' }}>Cancel</button>
                <button disabled={!message.trim() || mut.isPending} onClick={() => mut.mutate()}
                  style={{ background: 'var(--warning)', color: '#fff', border: 'none', borderRadius: 8, padding: '8px 16px', cursor: 'pointer', fontWeight: 700, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6, opacity: mut.isPending ? 0.6 : 1 }}>
                  <Send size={12} />{mut.isPending ? 'Sending…' : 'Send Request'}
                </button>
              </div>
              {mut.isError && <div style={{ marginTop: 10, color: 'var(--danger)', fontSize: 12 }}>⚠ {mut.error?.response?.data?.detail || 'Failed to send'}</div>}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Resolve & Credit Modal ─────────────────────────────────────────────────────
function ResolveCreditModal({ dispute, onClose, onResolved }) {
  const qc = useQueryClient()
  const [loading, setLoading] = useState(true)
  const [aiData, setAiData] = useState(null)
  const [approvedAmt, setApprovedAmt] = useState(0)
  const [claimAmt, setClaimAmt] = useState(0)
  const [note, setNote] = useState('')
  const [emailTo, setEmailTo] = useState('')
  const [emailSubject, setEmailSubject] = useState('')
  const [emailBody, setEmailBody] = useState('')
  const [returnQty, setReturnQty] = useState(0)
  const [returnSkuId, setReturnSkuId] = useState(dispute.sku_id || '')
  const [done, setDone] = useState(null)
  const [tab, setTab] = useState('credit')

  const isPartial = approvedAmt > 0 && claimAmt > 0 && approvedAmt < claimAmt
  const isFull = claimAmt > 0 && approvedAmt >= claimAmt

  React.useEffect(() => {
    adminPortalDisputesApi.aiSuggest(dispute.dispute_id)
      .then(res => {
        const d = res.data
        setAiData(d)
        setApprovedAmt(d.suggested_amount || 0)
        setClaimAmt(d.claim_amount || 0)
        setNote(d.resolution_note || '')
        setEmailTo(d.customer_email || '')
        setEmailSubject(d.email_subject || '')
        setEmailBody(d.email_body || '')
      })
      .catch(() => setClaimAmt(0))
      .finally(() => setLoading(false))
  }, [dispute.dispute_id])

  const mut = useMutation({
    mutationFn: () => adminPortalDisputesApi.decide(dispute.dispute_id, {
      status: approvedAmt > 0 ? 'resolved' : 'rejected',
      decision_note: note || `Dispute ${dispute.dispute_id} decided by admin.`,
      customer_message: emailBody || `Dear Customer,\n\nYour dispute ${dispute.dispute_id} has been ${approvedAmt > 0 ? 'resolved' : 'rejected'}.\n\nRegards,\nMAQ Finance Disputes Team`,
      credit_amount_inr: approvedAmt > 0 ? approvedAmt : 0,
      return_quantity: Math.max(0, Number(returnQty) || 0),
      return_sku_id: returnSkuId.trim() || null,
    }),
    onSuccess: (res) => {
      setDone(res.data)
      qc.invalidateQueries({ queryKey: ['admin-portal-disputes'] })
      qc.invalidateQueries({ queryKey: ['admin-portal-dispute-stats'] })
      onResolved?.()
    },
  })

  const inp = { width: '100%', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '9px 12px', color: 'var(--text-primary)', fontSize: 13, outline: 'none' }
  const sec = { background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px', marginBottom: 14 }
  const lbl = { fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, width: '100%', maxWidth: 640, maxHeight: '92vh', overflowY: 'auto', boxShadow: 'var(--shadow-32)', color: 'var(--text-primary)' }}>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid var(--border)', background: 'var(--bg-subtle)', borderRadius: '14px 14px 0 0', position: 'sticky', top: 0, zIndex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <CreditCard size={20} color="var(--success)" />
            <div>
              <div style={{ fontWeight: 700, fontSize: 16, color: 'var(--text-primary)' }}>Resolve & Apply Credit</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{dispute.dispute_id} · {dispute.company_name} · {(dispute.dispute_type || '').replace(/_/g, ' ')}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 8px', cursor: 'pointer', color: 'var(--text-secondary)', display: 'flex' }}><X size={16} /></button>
        </div>

        <div style={{ padding: '20px' }}>
          {done ? (
            <div style={{ textAlign: 'center', padding: '32px 0' }}>
              <div style={{ fontSize: 52, marginBottom: 12 }}>✅</div>
              <div style={{ fontWeight: 700, fontSize: 20, color: 'var(--success)', marginBottom: 10 }}>
                {approvedAmt > 0 ? 'Dispute Resolved & Credit Applied!' : 'Dispute Rejected'}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.9, maxWidth: 400, margin: '0 auto' }}>
                {approvedAmt > 0 && (
                  <><strong style={{ color: 'var(--success)' }}>₹{approvedAmt.toLocaleString('en-IN')}</strong> credit decision applied to dispute <strong style={{ color: 'var(--text-primary)' }}>{dispute.dispute_id}</strong>.<br />Customer has been notified in the portal.</>
                )}
                {done.inventory_return && (
                  <><br /><strong style={{ color: 'var(--accent-blue)' }}>{returnQty} returned unit{returnQty === 1 ? '' : 's'}</strong> added back to inventory for SKU <strong style={{ color: 'var(--text-primary)' }}>{done.inventory_return.sku_id}</strong>.</>
                )}
              </div>
              <button onClick={onClose} style={{ marginTop: 20, background: 'var(--success)', color: '#fff', border: 'none', borderRadius: 8, padding: '9px 24px', cursor: 'pointer', fontWeight: 700, fontSize: 14 }}>Done</button>
            </div>
          ) : loading ? (
            <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--text-muted)' }}>
              <div style={{ fontSize: 40, marginBottom: 16 }}>🤖</div>
              <div style={{ fontWeight: 600, fontSize: 16, color: 'var(--text-secondary)', marginBottom: 8 }}>AI is analyzing the dispute thread…</div>
              <div style={{ fontSize: 12 }}>Ollama Cloud is reading the conversation and calculating a fair credit amount</div>
            </div>
          ) : (
            <>
              {/* AI Recommendation banner */}
              {aiData?.rationale && (
                <div style={{ background: 'var(--brand-light)', border: '1px solid var(--brand-mid)', borderRadius: 10, padding: '14px 16px', marginBottom: 18, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                  <span style={{ fontSize: 24, lineHeight: 1 }}>🤖</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 11, color: 'var(--brand)', fontWeight: 700, letterSpacing: '0.05em', marginBottom: 5 }}>AI RECOMMENDATION</div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.65 }}>{aiData.rationale}</div>
                    <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
                      Suggested credit: <strong style={{ color: 'var(--success)', fontSize: 14 }}>₹{approvedAmt.toLocaleString('en-IN')}</strong>
                      {' '}of <strong style={{ color: 'var(--text-secondary)' }}>₹{claimAmt.toLocaleString('en-IN')}</strong> invoice total
                      {claimAmt > 0 && approvedAmt < claimAmt && <span style={{ color: 'var(--warning)' }}> ({Math.round(approvedAmt / claimAmt * 100)}% partial)</span>}
                    </div>
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div style={{ display: 'flex', gap: 3, marginBottom: 18, background: 'var(--bg-subtle)', borderRadius: 10, padding: 4 }}>
                {[['credit', '💳 Credit Details'], ['email', '📧 Customer Message']].map(([t, label]) => (
                  <button key={t} onClick={() => setTab(t)} style={{ flex: 1, padding: '8px 0', borderRadius: 7, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 700, transition: 'all 0.2s', background: tab === t ? 'var(--surface)' : 'transparent', color: tab === t ? 'var(--brand)' : 'var(--text-muted)', boxShadow: tab === t ? 'var(--shadow-2)' : 'none' }}>
                    {label}
                  </button>
                ))}
              </div>

              {tab === 'credit' && (
                <>
                  <div style={sec}>
                    <label style={lbl}>
                      Approved Credit Amount &nbsp;
                      <span style={{ color: isFull ? 'var(--success)' : isPartial ? 'var(--warning)' : 'var(--danger)', textTransform: 'none', fontSize: 12 }}>
                        {isFull ? '✓ Full Credit' : isPartial ? `⬤ Partial (${Math.round(approvedAmt / claimAmt * 100)}%)` : '✗ No Credit — Dispute Rejected'}
                      </span>
                    </label>
                    <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 10 }}>
                      <input type="range" min={0} max={claimAmt || 100000} step={500} value={approvedAmt} onChange={e => setApprovedAmt(Number(e.target.value))}
                        style={{ flex: 1, accentColor: isFull ? 'var(--success)' : isPartial ? 'var(--warning)' : 'var(--danger)', height: 6 }} />
                      <input type="number" value={approvedAmt} onChange={e => setApprovedAmt(Math.max(0, Number(e.target.value)))} style={{ ...inp, width: 130 }} />
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      Invoice total: ₹{claimAmt.toLocaleString('en-IN')} &nbsp;·&nbsp; Approving: <strong style={{ color: isFull ? 'var(--success)' : isPartial ? 'var(--warning)' : 'var(--danger)' }}>₹{approvedAmt.toLocaleString('en-IN')}</strong>
                    </div>
                  </div>

                  <div style={sec}>
                    <label style={lbl}>Resolution Note (SOX Audit Trail)</label>
                    <input style={inp} placeholder="e.g. Full credit approved — pricing error verified against PO" value={note} onChange={e => setNote(e.target.value)} />
                  </div>

                  <div style={sec}>
                    <label style={lbl}>Returned Saleable Units To Restock</label>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                      <input type="number" min={0} step={1} value={returnQty} onChange={e => setReturnQty(Math.max(0, Number(e.target.value) || 0))} style={{ ...inp, width: 150 }} />
                      <input value={returnSkuId} onChange={e => setReturnSkuId(e.target.value.toUpperCase())} placeholder="SKU ID if no order linked" style={{ ...inp, width: 210 }} />
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
                      Use only when physical goods are returned and saleable. If the dispute is not linked to an invoice/order, enter the SKU manually, e.g. SKU-001.
                    </div>
                  </div>
                </>
              )}

              {tab === 'email' && (
                <>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 14, padding: '10px 14px', background: 'var(--bg-subtle)', borderRadius: 8, border: '1px solid var(--border)' }}>
                    📧 This message will be sent to the customer as the admin closing message. AI has pre-drafted it — edit anything below.
                  </div>
                  <div style={sec}>
                    <label style={lbl}>Customer Email Address</label>
                    <input style={inp} placeholder="customer@company.com" value={emailTo} onChange={e => setEmailTo(e.target.value)} />
                  </div>
                  <div style={sec}>
                    <label style={lbl}>Email Subject</label>
                    <input style={inp} value={emailSubject} onChange={e => setEmailSubject(e.target.value)} />
                  </div>
                  <div style={sec}>
                    <label style={lbl}>Customer-Visible Closing Message — AI-drafted, fully editable</label>
                    <textarea rows={13} value={emailBody} onChange={e => setEmailBody(e.target.value)}
                      style={{ ...inp, resize: 'vertical', fontFamily: 'monospace', lineHeight: 1.75, fontSize: 12 }} />
                  </div>
                </>
              )}

              {/* Action row */}
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
                <button onClick={onClose} style={{ background: 'var(--bg-subtle)', color: 'var(--text-secondary)', border: '1px solid var(--border)', borderRadius: 8, padding: '9px 18px', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>Cancel</button>
                <button disabled={mut.isPending} onClick={() => mut.mutate()} style={{
                  background: approvedAmt > 0 ? 'var(--success)' : 'var(--violet)',
                  color: '#fff', border: 'none', borderRadius: 8, padding: '9px 22px', cursor: 'pointer', fontWeight: 700, fontSize: 13,
                  display: 'flex', alignItems: 'center', gap: 8, opacity: mut.isPending ? 0.6 : 1, transition: 'opacity 0.2s',
                }}>
                  {mut.isPending ? '⏳ Processing…' : approvedAmt > 0 ? `✅ Apply ₹${approvedAmt.toLocaleString('en-IN')} Credit & Close` : '🚫 Reject & Close (No Credit)'}
                </button>
              </div>

              {mut.isError && (
                <div style={{ marginTop: 12, color: 'var(--danger)', fontSize: 12, background: 'var(--danger-bg)', border: '1px solid var(--danger-border)', padding: '10px 14px', borderRadius: 8 }}>
                  ⚠ {mut.error?.response?.data?.detail || 'Failed to save decision — check backend logs'}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Dispute Thread Drawer ──────────────────────────────────────────────────────
function PortalDisputeDrawer({ disputeId, onClose }) {
  const qc = useQueryClient()
  const [reply, setReply] = useState('')
  const [decisionStatus, setDecisionStatus] = useState('resolved')
  const [decisionNote, setDecisionNote] = useState('')
  const [customerMessage, setCustomerMessage] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['admin-portal-dispute', disputeId],
    queryFn: () => adminPortalDisputesApi.get(disputeId).then(r => r.data),
    enabled: !!disputeId,
    refetchInterval: 8000,
  })

  const dispute = data?.dispute
  const messages = data?.messages || []
  const attachments = data?.attachments || []
  const canReply = dispute?.next_actor === 'admin' && !FINAL_STATUSES.includes(dispute?.status)
  const canDecide = dispute && !FINAL_STATUSES.includes(dispute.status)

  const replyMut = useMutation({
    mutationFn: () => adminPortalDisputesApi.reply(disputeId, reply),
    onSuccess: () => {
      setReply('')
      qc.invalidateQueries({ queryKey: ['admin-portal-dispute', disputeId] })
      qc.invalidateQueries({ queryKey: ['admin-portal-disputes'] })
      qc.invalidateQueries({ queryKey: ['admin-portal-dispute-stats'] })
    },
  })

  const decideMut = useMutation({
    mutationFn: () => adminPortalDisputesApi.decide(disputeId, {
      status: decisionStatus,
      decision_note: decisionNote,
      customer_message: customerMessage,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-portal-dispute', disputeId] })
      qc.invalidateQueries({ queryKey: ['admin-portal-disputes'] })
      qc.invalidateQueries({ queryKey: ['admin-portal-dispute-stats'] })
      setDecisionNote('')
      setCustomerMessage('')
    },
  })

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 9998, display: 'flex', justifyContent: 'flex-end' }}>
      <div style={{ width: 'min(900px, 100%)', background: 'var(--bg-page)', color: 'var(--text-primary)', height: '100%', overflowY: 'auto', borderLeft: '1px solid var(--border)' }}>
        <div style={{ position: 'sticky', top: 0, background: 'var(--bg-subtle)', borderBottom: '1px solid var(--border)', padding: '14px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', zIndex: 2 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <MessageSquare size={17} color="var(--accent-blue)" />
            <strong>Portal Dispute Thread</strong>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 0, color: 'var(--text-muted)', cursor: 'pointer' }}><X size={18} /></button>
        </div>

        {isLoading ? <div style={{ padding: 24 }}>Loading...</div> : !dispute ? <div style={{ padding: 24 }}>Dispute not found.</div> : (
          <div style={{ padding: 18 }}>
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 16, marginBottom: 14, boxShadow: 'var(--shadow-2)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <span style={{ fontFamily: 'monospace', color: 'var(--danger)', fontSize: 12 }}>{dispute.dispute_id}</span>
                    <span className={badgeClass(dispute.status)}>{dispute.status.replace(/_/g, ' ')}</span>
                  </div>
                  <h2 style={{ margin: '0 0 6px', color: 'var(--text-primary)', fontSize: 20 }}>{dispute.subject}</h2>
                  <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                    {dispute.company_name} · {dispute.customer_email} · Invoice {dispute.invoice_id || '—'} · Order {dispute.order_id || '—'}
                  </div>
                </div>
                <div style={{ textAlign: 'right', fontSize: 12, color: 'var(--text-secondary)' }}>
                  <div>Type: <strong style={{ color: 'var(--text-primary)', textTransform: 'capitalize' }}>{(dispute.dispute_type || '').replace(/_/g, ' ')}</strong></div>
                  <div>Next: <strong style={{ color: 'var(--text-primary)' }}>{nextActorLabel(dispute)}</strong></div>
                  <div>Proofs: <strong style={{ color: 'var(--text-primary)' }}>{dispute.proof_count || 0}</strong></div>
                </div>
              </div>
            </div>

            <div style={{ background: 'var(--brand-light)', border: '1px solid var(--brand-mid)', borderRadius: 12, padding: 14, marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, color: 'var(--brand)', fontWeight: 700 }}>
                <ShieldCheck size={15} /> AI-generated Admin Summary
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{dispute.ai_summary || 'Summary pending...'}</div>
              <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>Status: {dispute.ai_summary_status || 'pending'} · Model: {dispute.ai_summary_model || '—'}</div>
            </div>

            {attachments.length > 0 && (
              <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 14, marginBottom: 14, boxShadow: 'var(--shadow-2)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontWeight: 700, marginBottom: 10 }}><Paperclip size={15} /> Proof Attachments</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {attachments.map((a) => (
                    <a key={a.attachment_id} href={`http://localhost:8000/api/portal-disputes/${disputeId}/attachments/${a.attachment_id}`} target="_blank" rel="noreferrer"
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--accent-blue)', border: '1px solid var(--border)', borderRadius: 8, padding: '7px 10px', textDecoration: 'none', fontSize: 12 }}>
                      <FileText size={13} /> {a.filename}
                    </a>
                  ))}
                </div>
              </div>
            )}

            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 14, marginBottom: 14, boxShadow: 'var(--shadow-2)' }}>
              <div style={{ color: 'var(--text-primary)', fontWeight: 700, marginBottom: 12 }}>Conversation</div>
              {messages.map((m) => {
                const isAdmin = m.sender_type === 'admin'
                const isSystem = m.sender_type === 'system'
                return (
                  <div key={m.message_id} style={{ display: 'flex', justifyContent: isAdmin ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
                    <div style={{ maxWidth: '74%', background: isSystem ? 'var(--bg-muted)' : isAdmin ? 'var(--accent-blue)' : 'var(--bg-subtle)', color: isAdmin ? '#fff' : 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 12, padding: '10px 12px' }}>
                      <div style={{ fontSize: 11, opacity: 0.75, marginBottom: 4, textTransform: 'capitalize' }}>{m.sender_type} · {formatDate(m.created_at)}</div>
                      <div style={{ fontSize: 13, whiteSpace: 'pre-wrap', lineHeight: 1.45 }}>{m.body}</div>
                    </div>
                  </div>
                )
              })}
            </div>

            {!FINAL_STATUSES.includes(dispute.status) && dispute.next_actor !== 'admin' && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', background: 'var(--warning-bg)', color: 'var(--warning)', border: '1px solid var(--warning-border)', borderRadius: 10, padding: 11, marginBottom: 14, fontSize: 13 }}>
                <AlertCircle size={15} /> Waiting for customer response. Admin reply is locked until the customer responds.
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(300px, 420px)', gap: 14 }}>
              <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 14, boxShadow: 'var(--shadow-2)' }}>
                <div style={{ color: 'var(--text-primary)', fontWeight: 700, marginBottom: 8 }}>Manual Admin Reply</div>
                <textarea rows={6} disabled={!canReply} value={reply} onChange={(e) => setReply(e.target.value)}
                  placeholder={canReply ? 'Write a manual reply to the customer...' : 'Reply locked'}
                  style={{ width: '100%', background: 'var(--surface)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: 10, resize: 'vertical', opacity: canReply ? 1 : 0.55 }} />
                <button onClick={() => replyMut.mutate()} disabled={!canReply || !reply.trim() || replyMut.isPending} className="btn btn-primary btn-sm" style={{ marginTop: 10 }}>
                  <Send size={12} /> {replyMut.isPending ? 'Sending...' : 'Send Reply'}
                </button>
                {replyMut.isError && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 8 }}>{replyMut.error?.response?.data?.detail || 'Reply failed'}</div>}
              </div>

              <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 12, padding: 14, boxShadow: 'var(--shadow-2)' }}>
                <div style={{ color: 'var(--text-primary)', fontWeight: 700, marginBottom: 8 }}>Admin Final Decision</div>
                <select disabled={!canDecide} value={decisionStatus} onChange={(e) => setDecisionStatus(e.target.value)}
                  style={{ width: '100%', background: 'var(--surface)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: 9, marginBottom: 8 }}>
                  <option value="resolved">Resolve</option>
                  <option value="rejected">Reject</option>
                  <option value="closed">Close</option>
                </select>
                <textarea rows={3} disabled={!canDecide} value={decisionNote} onChange={(e) => setDecisionNote(e.target.value)}
                  placeholder="Internal decision note for audit"
                  style={{ width: '100%', background: 'var(--surface)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: 9, resize: 'vertical', marginBottom: 8 }} />
                <textarea rows={4} disabled={!canDecide} value={customerMessage} onChange={(e) => setCustomerMessage(e.target.value)}
                  placeholder="Customer-visible closing message"
                  style={{ width: '100%', background: 'var(--surface)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 8, padding: 9, resize: 'vertical' }} />
                <button onClick={() => decideMut.mutate()} disabled={!canDecide || !decisionNote.trim() || !customerMessage.trim() || decideMut.isPending} className="btn btn-success btn-sm" style={{ marginTop: 10 }}>
                  <CheckCircle size={12} /> {decideMut.isPending ? 'Saving...' : 'Save Decision'}
                </button>
                {decideMut.isError && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 8 }}>{decideMut.error?.response?.data?.detail || 'Decision failed'}</div>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main Admin Panel ───────────────────────────────────────────────────────────
export default function PortalDisputesAdminPanel() {
  const qc = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [requestInfoDispute, setRequestInfoDispute] = useState(null)
  const [resolveDispute, setResolveDispute] = useState(null)

  // Form states
  const [showForm, setShowForm] = useState(false)
  const [emailText, setEmailText] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const submitMut = useMutation({
    mutationFn: (text) => api.post('/disputes/submit-email', { email_text: text }, { timeout: 90000 }),
    onSuccess: (res) => {
      setResult(res.data); setEmailText('')
      qc.invalidateQueries({ queryKey: ['admin-portal-disputes'] })
      qc.invalidateQueries({ queryKey: ['admin-portal-dispute-stats'] })
    },
    onError: (err) => setError(err?.response?.data?.detail || 'Submission failed'),
  })

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['admin-portal-disputes'],
    queryFn: () => adminPortalDisputesApi.list({ limit: 100 }).then(r => r.data),
    refetchInterval: 10000,
  })
  const { data: stats } = useQuery({
    queryKey: ['admin-portal-dispute-stats'],
    queryFn: () => adminPortalDisputesApi.stats().then(r => r.data),
  })

  const disputes = data?.disputes || []
  const s = stats || {}

  return (
    <div>
      <div className="page-header" style={{ marginTop: 18 }}>
        <div className="page-header-left">
          <h2 className="page-title" style={{ fontSize: 22 }}>Customer Portal Disputes</h2>
          <p className="page-subtitle">Human escalation queue · AI triage summary · Admin-only decisions</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={refetch}><RefreshCcw size={13} /> Refresh</button>
      </div>

      <div className="kpi-grid" style={{ marginBottom: 20 }}>
        <div className="kpi-card"><div className="kpi-label">Portal Disputes</div><div className="kpi-value">{s.total ?? disputes.length}</div></div>
        <div className="kpi-card"><div className="kpi-label">Pending Admin</div><div className="kpi-value" style={{ color: 'var(--accent-amber)' }}>{s.pending_admin ?? 0}</div></div>
        <div className="kpi-card"><div className="kpi-label">Awaiting Customer</div><div className="kpi-value" style={{ color: 'var(--accent-blue)' }}>{s.awaiting_customer ?? 0}</div></div>
        <div className="kpi-card"><div className="kpi-label">Final</div><div className="kpi-value" style={{ color: 'var(--accent-green)' }}>{s.final ?? 0}</div></div>
      </div>

      <div style={{ display:'flex',gap:8,alignItems:'center', marginBottom: 16 }}>
        <button className="btn btn-primary btn-sm" onClick={() => { setShowForm(!showForm); setResult(null); setError(null) }}>
          <Mail size={13}/> {showForm ? 'Cancel' : 'Submit Dispute Email (Test Agent)'}
        </button>
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom:20 }}>
          <div className="card-header">
            <div className="card-title" style={{ display:'flex',alignItems:'center',gap:8 }}>
              <Mail size={15}/> Submit Dispute Email
            </div>
            <span className="badge badge-blue">GLiNER NER</span>
          </div>
          <div style={{ marginBottom:10,display:'flex',gap:8,flexWrap:'wrap' }}>
            <span style={{ fontSize:11,color:'var(--text-muted)',alignSelf:'center' }}>Quick load sample:</span>
            {SAMPLE_EMAILS.map(s => (
              <button key={s.label} className="btn btn-secondary btn-sm" onClick={() => { setEmailText(s.text); setResult(null); setError(null) }}>{s.label}</button>
            ))}
          </div>
          <textarea className="form-input" rows={8} style={{ width:'100%',fontFamily:'monospace',fontSize:12,resize:'vertical' }}
            placeholder="Paste the dispute email here..." value={emailText}
            onChange={e => { setEmailText(e.target.value); setResult(null); setError(null) }} />
          <div style={{ display:'flex',gap:8,marginTop:10 }}>
            <button className="btn btn-primary" onClick={() => submitMut.mutate(emailText)} disabled={!emailText.trim()||submitMut.isPending}>
              {submitMut.isPending ? 'AI Parsing...' : '⚡ Parse & Submit Dispute'}
            </button>
          </div>
          {result && (
            <div style={{ marginTop:14,padding:'14px 16px',background:'rgba(16,185,129,0.08)',border:'1px solid rgba(16,185,129,0.3)',borderRadius:8 }}>
              <div style={{ display:'flex',alignItems:'center',gap:8,marginBottom:10,color:'var(--accent-green)',fontWeight:700 }}>
                <CheckCircle size={15}/> Email Dispute Ingested into Portal Queue: {result.alert_id}
              </div>
              <div style={{ fontSize:12,color:'var(--text-secondary)' }}>AI Classification: {result.dispute_type?.replace(/_/g,' ')}</div>
            </div>
          )}
          {error && <div style={{ marginTop:10,color:'var(--accent-red)',fontSize:13 }}><AlertCircle size={13} style={{ display:'inline',marginRight:6 }}/>{error}</div>}
        </div>
      )}

      <div className="card">
        <div className="card-header">
          <div className="card-title">Portal Dispute Review Queue</div>
          <span className="badge badge-blue">{disputes.length}</span>
        </div>
        {isLoading ? <div className="loading-wrap"><div className="spinner" /></div> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Dispute ID</th>
                  <th>Customer</th>
                  <th>Invoice / Order</th>
                  <th>Source</th>
                  <th>Type</th>
                  <th>AI Summary</th>
                  <th>Proof</th>
                  <th>Status</th>
                  <th>Next</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {disputes.length === 0 ? (
                  <tr><td colSpan={10}><div className="empty-state"><MessageSquare size={28} style={{ opacity: 0.3 }} /><div className="empty-title">No portal disputes yet</div><div className="empty-text">Customer-submitted disputes will appear here.</div></div></td></tr>
                ) : disputes.map((d) => {
                  const isPendingAdmin = d.next_actor === 'admin' && !FINAL_STATUSES.includes(d.status)
                  const isFinal = FINAL_STATUSES.includes(d.status)
                  return (
                    <tr key={d.dispute_id}>
                      <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--accent-red)' }}>{d.dispute_id}</td>
                      <td style={{ fontSize: 12 }}><strong>{d.company_name || 'Unknown'}</strong><br /><span style={{ color: 'var(--text-muted)' }}>{d.customer_email || '—'}</span></td>
                      <td style={{ fontSize: 12 }}>{d.invoice_id || '—'}<br /><span style={{ color: 'var(--text-muted)' }}>{d.order_id || '—'}</span></td>
                      <td>
                        {d.source === 'email' ? <span className="badge badge-gray"><Mail size={10} style={{marginRight: 4}}/> Email</span> : <span className="badge badge-violet">Portal</span>}
                      </td>
                      <td><span className="badge badge-violet">{(d.dispute_type || '').replace(/_/g, ' ')}</span></td>
                      <td style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.ai_summary || 'Summary pending...'}</td>
                      <td style={{ fontSize: 12 }}>{d.proof_count || 0}</td>
                      <td><span className={badgeClass(d.status)}>{d.status.replace(/_/g, ' ')}</span></td>
                      <td style={{ fontSize: 12, color: isPendingAdmin ? 'var(--accent-amber)' : 'var(--text-muted)', fontWeight: isPendingAdmin ? 700 : 500 }}>{nextActorLabel(d)}</td>
                      <td>
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                          {/* Request Info — only when it's admin's turn */}
                          {isPendingAdmin && (
                            <button
                              className="btn btn-secondary btn-sm"
                              title="Ask customer for more evidence"
                              onClick={() => setRequestInfoDispute(d)}
                              style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                            >
                              <MessageSquare size={11} /> Request Info
                            </button>
                          )}
                          {/* Resolve & Credit — available as long as not final */}
                          {!isFinal && (
                            <button
                              className="btn btn-success btn-sm"
                              title="AI-assisted credit resolution"
                              onClick={() => setResolveDispute(d)}
                              style={{ display: 'flex', alignItems: 'center', gap: 4 }}
                            >
                              <Sparkles size={11} /> Resolve & Credit
                            </button>
                          )}
                          {/* Open full thread */}
                          <button className="btn btn-primary btn-sm" onClick={() => setSelectedId(d.dispute_id)}>Open Thread</button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedId && <PortalDisputeDrawer disputeId={selectedId} onClose={() => setSelectedId(null)} />}
      {requestInfoDispute && (
        <RequestInfoModal
          dispute={requestInfoDispute}
          onClose={() => setRequestInfoDispute(null)}
          onSent={() => setRequestInfoDispute(null)}
        />
      )}
      {resolveDispute && (
        <ResolveCreditModal
          dispute={resolveDispute}
          onClose={() => setResolveDispute(null)}
          onResolved={() => setResolveDispute(null)}
        />
      )}
    </div>
  )
}
