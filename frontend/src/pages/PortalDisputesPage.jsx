import React, { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Bot, CheckCircle, FileText, MessageSquare, Paperclip, Plus, RefreshCcw, Send, Sparkles, XCircle } from 'lucide-react'
import { portalApi } from '../lib/api'

const FINAL_STATUSES = ['resolved', 'rejected', 'closed', 'withdrawn']

const disputeTypes = [
  ['pricing_error', 'Pricing Error'],
  ['damaged_goods', 'Damaged Goods'],
  ['short_ship', 'Short Shipment'],
  ['payment_not_reflected', 'Payment Not Reflected'],
  ['pod_dispute', 'Proof of Delivery Issue'],
  ['general', 'General Dispute'],
]

function badgeStyle(status) {
  const base = { borderRadius: 999, padding: '4px 9px', fontSize: 11, fontWeight: 700, textTransform: 'capitalize' }
  if (status === 'pending_admin') return { ...base, background: '#fef3c7', color: '#92400e' }
  if (status === 'awaiting_customer') return { ...base, background: '#dbeafe', color: '#1d4ed8' }
  if (status === 'resolved') return { ...base, background: '#dcfce7', color: '#166534' }
  if (status === 'rejected') return { ...base, background: '#fee2e2', color: '#991b1b' }
  if (status === 'withdrawn') return { ...base, background: '#f1f5f9', color: '#475569' }
  return { ...base, background: '#e2e8f0', color: '#334155' }
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

function nextActionText(dispute) {
  if (!dispute) return ''
  if (dispute.status === 'withdrawn') return 'Withdrawn by you'
  if (['resolved', 'rejected', 'closed'].includes(dispute.status)) return 'Closed'
  if (dispute.next_actor === 'customer') return 'Your response required'
  return 'Waiting for Admin response'
}

function CreateDisputeForm({ invoices = [], orders = [], onCreated }) {
  const qc = useQueryClient()
  const [aiText, setAiText] = useState('')
  const [aiPreview, setAiPreview] = useState(null)
  const [invoiceId, setInvoiceId] = useState('')
  const [orderId, setOrderId] = useState('')
  const [disputeType, setDisputeType] = useState('general')
  const [subject, setSubject] = useState('')
  const [message, setMessage] = useState('')
  const [files, setFiles] = useState([])

  const inputStyle = { width: '100%', border: '1px solid #cbd5e1', borderRadius: 8, padding: '10px 12px', fontSize: 13, outline: 'none', background: 'white' }
  const labelStyle = { display: 'block', marginBottom: 5, fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }

  const extractMut = useMutation({
    mutationFn: () => portalApi.previewDispute({ text: aiText }),
    onSuccess: (res) => {
      const payload = res?.data || res          // unwrap Axios { data: ... }
      const form = payload?.prefilled_form || {}
      setAiPreview(payload)
      setInvoiceId(form.invoice_id || '')
      setOrderId(form.order_id || '')
      setDisputeType(form.dispute_type || 'general')
      setSubject(form.subject || '')
      setMessage(form.message || aiText)
    },
  })

  const createMut = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      if (invoiceId) fd.append('invoice_id', invoiceId)
      if (orderId) fd.append('order_id', orderId)
      fd.append('dispute_type', disputeType)
      fd.append('subject', subject)
      fd.append('message', message)
      files.forEach((file) => fd.append('attachments', file))
      return portalApi.createDispute(fd)
    },
    onSuccess: (res) => {
      setAiText('')
      setAiPreview(null)
      setInvoiceId('')
      setOrderId('')
      setDisputeType('general')
      setSubject('')
      setMessage('')
      setFiles([])
      qc.invalidateQueries({ queryKey: ['portal-disputes'] })
      onCreated?.(res.dispute_id)
    },
  })

  const hasReview = Boolean(aiPreview)
  const missingFields = aiPreview?.missing_fields || []
  const reviewNotes = aiPreview?.review_notes || []

  return (
    <div style={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 14, padding: 18, boxShadow: '0 1px 3px rgba(15,23,42,0.06)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <Plus size={18} color="#2563eb" />
        <h2 style={{ margin: 0, fontSize: 18, color: '#0f172a' }}>Submit a Dispute</h2>
      </div>

      <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 12, padding: 14, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <Bot size={16} color="#6366f1" />
          <div style={{ fontSize: 14, fontWeight: 800, color: '#0f172a' }}>Describe the dispute in your own words</div>
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>
          AI will extract invoice/order reference, dispute type, subject, and first message. You can review and edit everything before submitting.
        </div>
        <textarea
          rows={5}
          style={{ ...inputStyle, resize: 'vertical', lineHeight: 1.45 }}
          value={aiText}
          onChange={(e) => setAiText(e.target.value)}
          placeholder={'Example: Invoice INV-003 has a pricing mismatch. We were charged ₹85,000 but the agreed price was ₹75,000. Please review and issue a credit note. I am attaching the PO as proof.'}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 10 }}>
          <button
            type="button"
            onClick={() => extractMut.mutate()}
            disabled={!aiText.trim() || extractMut.isPending}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 7, background: extractMut.isPending ? '#c4b5fd' : 'linear-gradient(135deg, #6366f1, #8b5cf6)', color: 'white', border: 0, borderRadius: 9, padding: '10px 15px', fontWeight: 700, cursor: !aiText.trim() || extractMut.isPending ? 'not-allowed' : 'pointer', opacity: !aiText.trim() ? 0.65 : 1 }}
          >
            <Sparkles size={14} /> {extractMut.isPending ? 'Extracting...' : hasReview ? 'Extract Again' : 'Extract with AI'}
          </button>
          {extractMut.isError && <span style={{ color: '#dc2626', fontSize: 13 }}>{extractMut.error?.response?.data?.detail || 'AI extraction failed'}</span>}
        </div>
      </div>

      {hasReview && (
        <div style={{ background: '#faf5ff', border: '1px solid #e9d5ff', borderRadius: 12, padding: 14, marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, color: '#6d28d9', fontSize: 13, fontWeight: 800 }}>
            <Bot size={14} /> AI extracted details · Confidence: {aiPreview.ner_confidence || 'MEDIUM'}
          </div>
          {missingFields.length > 0 && (
            <div style={{ background: '#fff7ed', border: '1px solid #fed7aa', color: '#9a3412', borderRadius: 8, padding: '8px 10px', fontSize: 12, marginBottom: 10 }}>
              Please review missing/uncertain fields: {missingFields.join(', ')}
            </div>
          )}
          {reviewNotes.length > 0 && (
            <div style={{ background: '#ede9fe', color: '#5b21b6', borderRadius: 8, padding: '8px 10px', fontSize: 12, marginBottom: 10 }}>
              {reviewNotes.join(' ')}
            </div>
          )}
          {aiPreview.groq_corrections?.length > 0 && (
            <div style={{ background: '#ede9fe', color: '#5b21b6', borderRadius: 8, padding: '8px 10px', fontSize: 12, marginBottom: 10 }}>
              Groq normalized: {aiPreview.groq_corrections.join('; ')}
            </div>
          )}
          <div style={{ fontSize: 12, color: '#16a34a', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6 }}>
            <CheckCircle size={14} /> Review the editable fields below, attach proof if needed, then submit.
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14, marginBottom: 14 }}>
        <div>
          <label style={labelStyle}>Invoice</label>
          <select style={inputStyle} value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)}>
            <option value="">Select invoice if applicable</option>
            {invoices.map((inv) => (
              <option key={inv.invoice_id} value={inv.invoice_id}>{inv.invoice_id} · ₹{Number(inv.balance_due_inr || inv.total_amount_inr || 0).toLocaleString('en-IN')}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Order</label>
          <select style={inputStyle} value={orderId} onChange={(e) => setOrderId(e.target.value)}>
            <option value="">Select order if applicable</option>
            {orders.map((order) => (
              <option key={order.order_id} value={order.order_id}>{order.order_id} · {order.status}</option>
            ))}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Type</label>
          <select style={inputStyle} value={disputeType} onChange={(e) => setDisputeType(e.target.value)}>
            {disputeTypes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      </div>

      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>Subject</label>
        <input style={inputStyle} value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="AI will fill this after extraction" />
      </div>
      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>First Message to Admin</label>
        <textarea rows={5} style={{ ...inputStyle, resize: 'vertical' }} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="AI will prepare this message, and you can edit it before sending." />
      </div>
      <div style={{ marginBottom: 14 }}>
        <label style={labelStyle}>Proof Upload</label>
        <input type="file" multiple accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setFiles(Array.from(e.target.files || []))} />
        <div style={{ marginTop: 6, fontSize: 12, color: '#64748b' }}>Allowed: PDF, PNG, JPG, JPEG. Max 5 files. AI does not submit anything until you click Submit.</div>
      </div>
      <button
        onClick={() => createMut.mutate()}
        disabled={!subject.trim() || !message.trim() || createMut.isPending}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 7, background: '#2563eb', color: 'white', border: 0, borderRadius: 9, padding: '10px 15px', fontWeight: 700, cursor: !subject.trim() || !message.trim() || createMut.isPending ? 'not-allowed' : 'pointer', opacity: !subject.trim() || !message.trim() || createMut.isPending ? 0.6 : 1 }}
      >
        <Send size={14} /> {createMut.isPending ? 'Submitting...' : 'Submit Reviewed Dispute'}
      </button>
      {createMut.isError && <div style={{ marginTop: 10, color: '#dc2626', fontSize: 13 }}>{createMut.error?.response?.data?.detail || 'Could not submit dispute'}</div>}
    </div>
  )
}

function DisputeThread({ disputeId, onBack }) {
  const qc = useQueryClient()
  const [message, setMessage] = useState('')
  const [files, setFiles] = useState([])
  const [withdrawReason, setWithdrawReason] = useState('')
  const [showWithdraw, setShowWithdraw] = useState(false)

  const { data, isLoading } = useQuery({
    queryKey: ['portal-dispute', disputeId],
    queryFn: () => portalApi.getDispute(disputeId).then(r => r.data),
    enabled: !!disputeId,
    refetchInterval: 7000,
  })

  const dispute = data?.dispute
  const messages = data?.messages || []
  const attachments = data?.attachments || []
  const canReply = dispute?.next_actor === 'customer' && !FINAL_STATUSES.includes(dispute?.status)
  const canWithdraw = dispute && !FINAL_STATUSES.includes(dispute.status)

  const replyMut = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('message', message)
      files.forEach((file) => fd.append('attachments', file))
      return portalApi.replyDispute(disputeId, fd)
    },
    onSuccess: () => {
      setMessage('')
      setFiles([])
      qc.invalidateQueries({ queryKey: ['portal-dispute', disputeId] })
      qc.invalidateQueries({ queryKey: ['portal-disputes'] })
    },
  })

  const withdrawMut = useMutation({
    mutationFn: () => portalApi.withdrawDispute(disputeId, withdrawReason),
    onSuccess: () => {
      setShowWithdraw(false)
      qc.invalidateQueries({ queryKey: ['portal-dispute', disputeId] })
      qc.invalidateQueries({ queryKey: ['portal-disputes'] })
    },
  })

  if (isLoading) return <div style={{ padding: 24 }}>Loading dispute...</div>
  if (!dispute) return <div style={{ padding: 24 }}>Dispute not found.</div>

  return (
    <div>
      <button onClick={onBack} style={{ border: 0, background: 'transparent', color: '#2563eb', fontWeight: 700, cursor: 'pointer', marginBottom: 12 }}>← Back to disputes</button>
      <div style={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 14, overflow: 'hidden' }}>
        <div style={{ padding: 18, borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <MessageSquare size={18} color="#2563eb" />
              <h2 style={{ margin: 0, fontSize: 18 }}>{dispute.subject}</h2>
              <span style={badgeStyle(dispute.status)}>{dispute.status.replace(/_/g, ' ')}</span>
            </div>
            <div style={{ fontSize: 12, color: '#64748b' }}>
              ID: <strong>{dispute.dispute_id}</strong> · Invoice: {dispute.invoice_id || '—'} · Order: {dispute.order_id || '—'} · {nextActionText(dispute)}
            </div>
          </div>
          {canWithdraw && (
            <button onClick={() => setShowWithdraw(true)} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', border: '1px solid #fecaca', color: '#b91c1c', background: '#fff1f2', borderRadius: 8, padding: '8px 11px', cursor: 'pointer', fontWeight: 700 }}>
              <XCircle size={14} /> Withdraw
            </button>
          )}
        </div>

        <div style={{ padding: 18, background: '#f8fafc', minHeight: 260 }}>
          {messages.map((m) => {
            const isCustomer = m.sender_type === 'customer'
            const isSystem = m.sender_type === 'system'
            return (
              <div key={m.message_id} style={{ display: 'flex', justifyContent: isCustomer ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
                <div style={{ maxWidth: '74%', background: isSystem ? '#f1f5f9' : isCustomer ? '#2563eb' : 'white', color: isCustomer ? 'white' : '#0f172a', border: isSystem ? '1px dashed #cbd5e1' : '1px solid #e2e8f0', borderRadius: 14, padding: '10px 12px', boxShadow: '0 1px 2px rgba(15,23,42,0.05)' }}>
                  <div style={{ fontSize: 11, opacity: 0.75, marginBottom: 4, textTransform: 'capitalize' }}>{m.sender_type} · {formatDate(m.created_at)}</div>
                  <div style={{ fontSize: 14, whiteSpace: 'pre-wrap', lineHeight: 1.45 }}>{m.body}</div>
                  {attachments.filter((a) => a.message_id === m.message_id).map((a) => (
                    <a key={a.attachment_id} href={`http://localhost:8000/api/customer-portal/disputes/${disputeId}/attachments/${a.attachment_id}`} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', gap: 5, alignItems: 'center', marginTop: 8, fontSize: 12, color: isCustomer ? 'white' : '#2563eb' }}>
                      <Paperclip size={12} /> {a.filename}
                    </a>
                  ))}
                </div>
              </div>
            )
          })}
        </div>

        <div style={{ padding: 18, borderTop: '1px solid #e2e8f0' }}>
          {!canReply && !FINAL_STATUSES.includes(dispute.status) && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#fffbeb', color: '#92400e', padding: 11, borderRadius: 9, fontSize: 13, marginBottom: 12 }}>
              <AlertCircle size={15} /> Waiting for Admin response. You can reply after Admin responds.
            </div>
          )}
          {FINAL_STATUSES.includes(dispute.status) && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#f1f5f9', color: '#475569', padding: 11, borderRadius: 9, fontSize: 13, marginBottom: 12 }}>
              <CheckCircle size={15} /> This dispute is final and cannot receive new messages.
            </div>
          )}
          <textarea rows={4} disabled={!canReply} value={message} onChange={(e) => setMessage(e.target.value)} placeholder={canReply ? 'Write your response to Admin...' : 'Reply is locked until Admin responds'} style={{ width: '100%', border: '1px solid #cbd5e1', borderRadius: 9, padding: 12, resize: 'vertical', opacity: canReply ? 1 : 0.55 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
            <input type="file" multiple accept=".pdf,.png,.jpg,.jpeg" disabled={!canReply} onChange={(e) => setFiles(Array.from(e.target.files || []))} />
            <button onClick={() => replyMut.mutate()} disabled={!canReply || !message.trim() || replyMut.isPending} style={{ display: 'inline-flex', gap: 7, alignItems: 'center', background: '#2563eb', color: 'white', border: 0, borderRadius: 9, padding: '9px 14px', cursor: 'pointer', fontWeight: 700, opacity: !canReply || replyMut.isPending ? 0.55 : 1 }}>
              <Send size={14} /> {replyMut.isPending ? 'Sending...' : 'Send Response'}
            </button>
            {replyMut.isError && <span style={{ color: '#dc2626', fontSize: 13 }}>{replyMut.error?.response?.data?.detail || 'Reply failed'}</span>}
          </div>
        </div>
      </div>

      {showWithdraw && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16, zIndex: 50 }}>
          <div style={{ width: '100%', maxWidth: 460, background: 'white', borderRadius: 14, padding: 18 }}>
            <h3 style={{ marginTop: 0 }}>Withdraw dispute?</h3>
            <p style={{ color: '#64748b', fontSize: 13 }}>This will close the dispute from your side. Admin will still see it for audit history.</p>
            <textarea rows={4} value={withdrawReason} onChange={(e) => setWithdrawReason(e.target.value)} placeholder="Optional reason" style={{ width: '100%', border: '1px solid #cbd5e1', borderRadius: 9, padding: 10 }} />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
              <button onClick={() => setShowWithdraw(false)} style={{ border: '1px solid #cbd5e1', background: 'white', borderRadius: 8, padding: '8px 12px', cursor: 'pointer' }}>Cancel</button>
              <button onClick={() => withdrawMut.mutate()} disabled={withdrawMut.isPending} style={{ border: 0, background: '#dc2626', color: 'white', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', fontWeight: 700 }}>Withdraw</button>
            </div>
            {withdrawMut.isError && <div style={{ marginTop: 10, color: '#dc2626', fontSize: 13 }}>{withdrawMut.error?.response?.data?.detail || 'Withdraw failed'}</div>}
          </div>
        </div>
      )}
    </div>
  )
}

export default function PortalDisputesPage() {
  const [selectedId, setSelectedId] = useState(null)
  const [showCreate, setShowCreate] = useState(false)

  const { data, isLoading, refetch } = useQuery({ queryKey: ['portal-disputes'], queryFn: () => portalApi.disputes().then(r => r.data), refetchInterval: 10000 })
  const { data: invoicesData } = useQuery({ queryKey: ['portal-invoices'], queryFn: () => portalApi.outstanding().then((r) => r.data) })
  const { data: ordersData } = useQuery({ queryKey: ['portal-orders'], queryFn: () => portalApi.orders().then((r) => r.data) })

  const disputes = data?.disputes || []
  const invoices = useMemo(() => invoicesData?.invoices || invoicesData || [], [invoicesData])
  const orders = useMemo(() => ordersData?.orders || ordersData || [], [ordersData])

  if (selectedId) return <DisputeThread disputeId={selectedId} onBack={() => setSelectedId(null)} />

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, gap: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 28, color: '#0f172a' }}>Disputes</h1>
          <p style={{ margin: '6px 0 0', color: '#64748b', fontSize: 14 }}>Submit disputes, upload proof, and chat with Admin in controlled turns.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => refetch()} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', border: '1px solid #cbd5e1', background: 'white', borderRadius: 8, padding: '9px 12px', cursor: 'pointer' }}><RefreshCcw size={14} /> Refresh</button>
          <button onClick={() => setShowCreate((v) => !v)} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', border: 0, background: '#2563eb', color: 'white', borderRadius: 8, padding: '9px 12px', cursor: 'pointer', fontWeight: 700 }}><Plus size={14} /> {showCreate ? 'Hide Form' : 'New Dispute'}</button>
        </div>
      </div>

      {showCreate && <div style={{ marginBottom: 20 }}><CreateDisputeForm invoices={invoices} orders={orders} onCreated={(id) => { setShowCreate(false); setSelectedId(id) }} /></div>}

      <div style={{ background: 'white', border: '1px solid #e2e8f0', borderRadius: 14, overflow: 'hidden' }}>
        <div style={{ padding: 16, borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: 8 }}>
          <FileText size={17} color="#2563eb" />
          <strong>My Dispute Cases</strong>
          <span style={{ color: '#64748b', fontSize: 13 }}>({disputes.length})</span>
        </div>
        {isLoading ? (
          <div style={{ padding: 24 }}>Loading disputes...</div>
        ) : disputes.length === 0 ? (
          <div style={{ padding: 34, textAlign: 'center', color: '#64748b' }}>
            <MessageSquare size={36} style={{ opacity: 0.35, marginBottom: 8 }} />
            <div style={{ fontWeight: 700, color: '#0f172a' }}>No disputes yet</div>
            <div style={{ fontSize: 13 }}>Create a dispute when you need Admin review for an invoice or order.</div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead style={{ background: '#f8fafc', color: '#64748b', textAlign: 'left' }}>
                <tr>
                  <th style={{ padding: 12 }}>Dispute ID</th>
                  <th style={{ padding: 12 }}>Subject</th>
                  <th style={{ padding: 12 }}>Invoice / Order</th>
                  <th style={{ padding: 12 }}>Status</th>
                  <th style={{ padding: 12 }}>Next Action</th>
                  <th style={{ padding: 12 }}>Updated</th>
                  <th style={{ padding: 12 }}></th>
                </tr>
              </thead>
              <tbody>
                {disputes.map((d) => (
                  <tr key={d.dispute_id} style={{ borderTop: '1px solid #e2e8f0' }}>
                    <td style={{ padding: 12, fontFamily: 'monospace', fontSize: 12 }}>{d.dispute_id}</td>
                    <td style={{ padding: 12 }}>
                      <div style={{ fontWeight: 700, color: '#0f172a' }}>{d.subject}</div>
                      <div style={{ fontSize: 12, color: '#64748b', textTransform: 'capitalize' }}>{(d.dispute_type || '').replace(/_/g, ' ')} · Proofs: {d.proof_count || 0}</div>
                    </td>
                    <td style={{ padding: 12 }}>{d.invoice_id || '—'} / {d.order_id || '—'}</td>
                    <td style={{ padding: 12 }}><span style={badgeStyle(d.status)}>{d.status.replace(/_/g, ' ')}</span></td>
                    <td style={{ padding: 12, color: d.next_actor === 'customer' ? '#1d4ed8' : '#64748b', fontWeight: d.next_actor === 'customer' ? 700 : 500 }}>{nextActionText(d)}</td>
                    <td style={{ padding: 12, color: '#64748b' }}>{formatDate(d.updated_at)}</td>
                    <td style={{ padding: 12 }}><button onClick={() => setSelectedId(d.dispute_id)} style={{ border: '1px solid #cbd5e1', background: 'white', borderRadius: 8, padding: '7px 10px', cursor: 'pointer', fontWeight: 700 }}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
