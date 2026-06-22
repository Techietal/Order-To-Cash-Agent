import React, { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { portalApi } from '../lib/api'
import { usePortalStore } from '../store'
import { Send, Bot, CheckCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react'

const cardStyle = {
  background: 'white', borderRadius: 14, padding: 24,
  boxShadow: '0 2px 12px rgba(0,0,0,0.06)', border: '1px solid #f1f5f9'
}

const inputStyle = {
  width: '100%', padding: '9px 12px', borderRadius: 8,
  border: '1.5px solid #e2e8f0', fontSize: 13, outline: 'none',
  boxSizing: 'border-box', color: '#0f172a', background: 'white',
}

const labelStyle = { fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 5 }

const STATUS_COLOR = {
  pending_credit: '#f59e0b', approved: '#10b981', fulfilled: '#3b82f6',
  fraud_review: '#ef4444', rejected: '#ef4444', pending: '#94a3b8',
}

export default function PortalDashboardPage() {
  const { customer } = usePortalStore()
  const [formOrder, setFormOrder] = useState({ sku_id: '', quantity: '', delivery_address: '', requested_delivery_date: '', po_reference: '' })
  const [nlpText, setNlpText] = useState('')
  const [nlpPreview, setNlpPreview] = useState(null)
  const [nlpLoading, setNlpLoading] = useState(false)
  const [orderResult, setOrderResult] = useState(null)
  const [activeTab, setActiveTab] = useState('form')  // 'form' | 'nlp'
  const [formExpanded, setFormExpanded] = useState(true)

  const { data: products } = useQuery({
    queryKey: ['portal-products'],
    queryFn: () => portalApi.products().then(r => r.data),
  })

  const { data: outstandingData } = useQuery({
    queryKey: ['portal-outstanding'],
    queryFn: () => portalApi.outstanding().then(r => r.data),
  })

  const placeMutation = useMutation({
    mutationFn: (data) => portalApi.placeOrder(data),
    onSuccess: (res) => {
      setOrderResult({ success: true, ...res.data })
      setFormOrder({ sku_id: '', quantity: '', delivery_address: '', requested_delivery_date: '', po_reference: '' })
    },
    onError: (err) => setOrderResult({ success: false, error: err.response?.data?.detail || 'Order failed' }),
  })

  const handleNlpPreview = async () => {
    if (!nlpText.trim()) return
    setNlpLoading(true)
    setNlpPreview(null)
    try {
      const res = await portalApi.nlpPreview({ text: nlpText })
      setNlpPreview(res.data)

      // Auto-populate the structured form
      if (res.data.prefilled_form) {
        const pf = res.data.prefilled_form
        let matchedSku = ''
        if (pf.sku_hint && products?.products) {
          const hint = String(pf.sku_hint).toLowerCase()
          const hintNoS = hint.replace(/s$/, '')
          
          let matched = products.products.find(p => {
            const pName = p.product_name.toLowerCase()
            return pName.includes(hint) || hint.includes(pName) || 
                   pName.includes(hintNoS) || hintNoS.includes(pName) ||
                   p.sku_id.toLowerCase().includes(hint)
          })

          if (!matched) {
            const words = hint.split(' ').filter(w => w.length > 2)
            matched = products.products.find(p => {
              const pName = p.product_name.toLowerCase()
              const matchedWords = words.filter(w => pName.includes(w) || pName.includes(w.replace(/s$/, '')))
              return matchedWords.length >= 2
            })
          }

          if (matched) matchedSku = matched.sku_id
        }

        let parsedQty = pf.quantity || ''
        if (typeof parsedQty === 'string') {
          const match = parsedQty.match(/\d+/)
          if (match) parsedQty = match[0]
        }

        setFormOrder(prev => ({
          ...prev,
          sku_id: matchedSku || prev.sku_id,
          quantity: parsedQty || prev.quantity,
          delivery_address: pf.delivery_address || prev.delivery_address,
          requested_delivery_date: pf.requested_delivery_date || prev.requested_delivery_date,
          po_reference: pf.po_reference || prev.po_reference
        }))
        setFormExpanded(true)
      }
    } catch (e) {
      setNlpPreview({ error: e.response?.data?.detail || 'Preview failed' })
    } finally {
      setNlpLoading(false)
    }
  }

  const productList = products?.products || []
  const selectedProduct = productList.find(p => p.sku_id === formOrder.sku_id)
  const qty = parseInt(formOrder.quantity) || 0
  const estimatedTotal = selectedProduct ? qty * parseFloat(selectedProduct.base_price_inr) * 1.18 : 0

  return (
    <div>
      {/* Welcome bar */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 4px' }}>
          Welcome back, {customer?.company_name || 'Customer'} 👋
        </h1>
        <p style={{ fontSize: 14, color: '#64748b', margin: 0 }}>
          Place a new order below or describe what you need in your own words.
        </p>
      </div>

      {/* Outstanding alert */}
      {outstandingData?.total > 0 && (
        <div style={{ background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: 10, padding: '12px 16px', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 10 }}>
          <AlertCircle size={16} style={{ color: '#f97316', flexShrink: 0 }} />
          <span style={{ fontSize: 13, color: '#7c2d12' }}>
            You have <strong>{outstandingData.total} unpaid invoice(s)</strong> totaling{' '}
            <strong>₹{outstandingData.total_outstanding_inr?.toLocaleString('en-IN')}</strong>.{' '}
            <a href="/portal/outstanding" style={{ color: '#ea580c', fontWeight: 600 }}>View outstanding →</a>
          </span>
        </div>
      )}

      {/* Order Result */}
      {orderResult && (
        <div style={{
          background: orderResult.success ? '#f0fdf4' : '#fef2f2',
          border: `1px solid ${orderResult.success ? '#bbf7d0' : '#fecaca'}`,
          borderRadius: 10, padding: '14px 18px', marginBottom: 20,
          display: 'flex', gap: 10, alignItems: 'flex-start',
        }}>
          {orderResult.success
            ? <CheckCircle size={18} style={{ color: '#16a34a', flexShrink: 0, marginTop: 1 }} />
            : <AlertCircle size={18} style={{ color: '#dc2626', flexShrink: 0, marginTop: 1 }} />
          }
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: orderResult.success ? '#14532d' : '#7f1d1d' }}>
              {orderResult.success ? `Order ${orderResult.order_id} placed!` : 'Order Failed'}
            </div>
            <div style={{ fontSize: 13, color: orderResult.success ? '#166534' : '#991b1b', marginTop: 2 }}>
              {orderResult.success
                ? `${orderResult.product} × ${orderResult.quantity} — ₹${Number(orderResult.total_amount_inr).toLocaleString('en-IN')}`
                : orderResult.error}
            </div>
          </div>
        </div>
      )}

      {/* Main grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        {/* LEFT: Structured form */}
        <div style={cardStyle}>
          <div
            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer', marginBottom: formExpanded ? 20 : 0 }}
            onClick={() => setFormExpanded(e => !e)}
          >
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>📋 Structured Order Form</div>
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Select product and fill details</div>
            </div>
            {formExpanded ? <ChevronUp size={16} style={{ color: '#94a3b8' }} /> : <ChevronDown size={16} style={{ color: '#94a3b8' }} />}
          </div>

          {formExpanded && (
            <form onSubmit={e => { e.preventDefault(); placeMutation.mutate({ ...formOrder, quantity: parseInt(formOrder.quantity) }) }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div>
                  <label style={labelStyle}>Product <span style={{ color: '#ef4444' }}>*</span></label>
                  <select style={inputStyle} value={formOrder.sku_id} onChange={e => setFormOrder(f => ({ ...f, sku_id: e.target.value }))} required>
                    <option value="">Select a product...</option>
                    {productList.map(p => (
                      <option key={p.sku_id} value={p.sku_id}>
                        {p.product_name} — ₹{Number(p.base_price_inr).toLocaleString('en-IN')}/{p.unit_of_measure || 'Unit'} · Avail {p.available_stock ?? '—'}
                      </option>
                    ))}
                  </select>
                  {selectedProduct && (
                    <div style={{ marginTop: 7, fontSize: 12, color: selectedProduct.available_stock > 20 ? '#047857' : selectedProduct.available_stock > 0 ? '#b45309' : '#b91c1c' }}>
                      {selectedProduct.available_stock > 20 ? 'In stock' : selectedProduct.available_stock > 0 ? 'Limited stock' : 'Backorder likely'} · Available: {selectedProduct.available_stock ?? '—'}
                    </div>
                  )}
                </div>

                <div>
                  <label style={labelStyle}>Quantity <span style={{ color: '#ef4444' }}>*</span></label>
                  <input style={inputStyle} type="number" min={1} value={formOrder.quantity} onChange={e => setFormOrder(f => ({ ...f, quantity: e.target.value }))} placeholder="e.g. 25" required />
                </div>

                <div>
                  <label style={labelStyle}>Delivery Address</label>
                  <input style={inputStyle} value={formOrder.delivery_address} onChange={e => setFormOrder(f => ({ ...f, delivery_address: e.target.value }))} placeholder="Delivery address (optional)" />
                </div>

                <div>
                  <label style={labelStyle}>Requested Delivery Date</label>
                  <input style={inputStyle} type="date" value={formOrder.requested_delivery_date} onChange={e => setFormOrder(f => ({ ...f, requested_delivery_date: e.target.value }))} />
                </div>

                <div>
                  <label style={labelStyle}>PO Reference (optional)</label>
                  <input style={inputStyle} value={formOrder.po_reference} onChange={e => setFormOrder(f => ({ ...f, po_reference: e.target.value }))} placeholder="Your PO number" />
                </div>

                {/* Estimate */}
                {estimatedTotal > 0 && (
                  <div style={{ background: '#f0f9ff', border: '1px solid #bae6fd', borderRadius: 8, padding: '10px 14px', fontSize: 13 }}>
                    <div style={{ color: '#0369a1' }}>
                      Estimated Total (incl. 18% GST):{' '}
                      <strong style={{ fontSize: 15 }}>₹{estimatedTotal.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</strong>
                    </div>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={placeMutation.isPending}
                  style={{
                    padding: '11px', borderRadius: 8, border: 'none',
                    background: placeMutation.isPending ? '#93c5fd' : 'linear-gradient(135deg, #3b82f6, #6366f1)',
                    color: 'white', fontSize: 14, fontWeight: 600,
                    cursor: placeMutation.isPending ? 'not-allowed' : 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                  }}
                >
                  <Send size={14} />
                  {placeMutation.isPending ? 'Placing order...' : 'Place Order'}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* RIGHT: NLP Text Box */}
        <div style={cardStyle}>
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <Bot size={16} style={{ color: '#6366f1' }} />
              <div style={{ fontSize: 15, fontWeight: 700, color: '#0f172a' }}>✍️ Describe Your Order</div>
            </div>
            <div style={{ fontSize: 12, color: '#64748b' }}>Type naturally — our AI will extract the details</div>
          </div>

          <textarea
            value={nlpText}
            onChange={e => setNlpText(e.target.value)}
            placeholder={`e.g. "Please send us 50 Industrial Motors to our Hyderabad warehouse by next Friday. Our PO is PO-2025-789."`}
            style={{
              ...inputStyle, height: 130, resize: 'vertical', lineHeight: 1.5,
              fontSize: 13, marginBottom: 12,
            }}
          />

          <button
            onClick={handleNlpPreview}
            disabled={nlpLoading || !nlpText.trim()}
            style={{
              width: '100%', padding: '10px', borderRadius: 8, border: 'none',
              background: nlpLoading ? '#c4b5fd' : 'linear-gradient(135deg, #6366f1, #8b5cf6)',
              color: 'white', fontSize: 14, fontWeight: 600,
              cursor: (nlpLoading || !nlpText.trim()) ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, marginBottom: 16,
            }}
          >
            <Bot size={14} />
            {nlpLoading ? 'AI is reading your email...' : 'Extract with AI'}
          </button>

          {/* NLP Preview result */}
          {nlpPreview && !nlpPreview.error && (
            <div style={{ background: '#faf5ff', border: '1px solid #e9d5ff', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#6d28d9', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 5 }}>
                <Bot size={12} /> AI Extracted (Confidence: {nlpPreview.ner_confidence})
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {Object.entries(nlpPreview.prefilled_form).map(([k, v]) => v && (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                    <span style={{ color: '#7c3aed', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</span>
                    <span style={{ color: '#1e1b4b', fontWeight: 600 }}>{v}</span>
                  </div>
                ))}
              </div>
              {nlpPreview.groq_corrections?.length > 0 && (
                <div style={{ marginTop: 10, fontSize: 11, color: '#7c3aed', background: '#ede9fe', padding: '6px 10px', borderRadius: 6 }}>
                  ✏️ Groq corrections: {nlpPreview.groq_corrections.join('; ')}
                </div>
              )}
              <div style={{ marginTop: 12, fontSize: 12, color: '#16a34a', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                <CheckCircle size={14} />
                We've auto-populated the form on the left! Review and click Place Order.
              </div>
            </div>
          )}

          {nlpPreview?.error && (
            <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#dc2626' }}>
              {nlpPreview.error}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
