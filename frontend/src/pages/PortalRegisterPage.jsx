import React, { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { portalApi } from '../lib/api'
import { CheckCircle, ArrowLeft, Mail } from 'lucide-react'

const STATES = [
  'Andhra Pradesh','Arunachal Pradesh','Assam','Bihar','Chhattisgarh','Goa','Gujarat',
  'Haryana','Himachal Pradesh','Jharkhand','Karnataka','Kerala','Madhya Pradesh',
  'Maharashtra','Manipur','Meghalaya','Mizoram','Nagaland','Odisha','Punjab',
  'Rajasthan','Sikkim','Tamil Nadu','Telangana','Tripura','Uttar Pradesh',
  'Uttarakhand','West Bengal','Delhi','Jammu and Kashmir','Ladakh',
]

const BUSINESS_TYPES = ['Manufacturer','Distributor','Retailer','Trader','Service Provider','Other']
const TURNOVER_OPTIONS = ['< 10L (Below ₹10 Lakh)','10L-1Cr (₹10 Lakh to ₹1 Crore)','> 1Cr (Above ₹1 Crore)']

const Field = ({ label, children, required }) => (
  <div>
    <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 5 }}>
      {label} {required && <span style={{ color: '#ef4444' }}>*</span>}
    </label>
    {children}
  </div>
)

const inputStyle = {
  width: '100%', padding: '9px 12px', borderRadius: 8,
  border: '1.5px solid #e2e8f0', fontSize: 13, outline: 'none',
  boxSizing: 'border-box', color: '#0f172a', background: 'white',
}

export default function PortalRegisterPage() {
  const [searchParams] = useSearchParams()
  const inviteToken = searchParams.get('invite') || ''
  const inviteEmail = searchParams.get('email') || ''

  const [form, setForm] = useState({
    company_name: '', contact_name: '', email: inviteEmail, phone: '',
    gstin: '', pan_number: '', business_type: '', state: '',
    city: '', address: '', annual_turnover: '',
  })
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(null)
  const [loading, setLoading] = useState(false)

  const [showOtp, setShowOtp] = useState(false)
  const [otpCode, setOtpCode] = useState('')
  const [otpLoading, setOtpLoading] = useState(false)
  const [otpHint, setOtpHint] = useState('')

  // If email came from invite link, pre-fill and lock it
  useEffect(() => {
    if (inviteEmail) setForm(f => ({ ...f, email: inviteEmail }))
  }, [inviteEmail])

  const set = (key) => (e) => setForm(f => ({ ...f, [key]: e.target.value }))

  const handleRequestOtp = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await portalApi.sendOtp({
        email: form.email,
        contact_name: form.contact_name || form.company_name
      })
      const devOtp = res.data?.dev_otp
      setOtpHint(devOtp ? `Local development OTP: ${devOtp}` : '')
      if (devOtp) setOtpCode(devOtp)
      setShowOtp(true)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to send OTP. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleVerifyAndSubmit = async (e) => {
    if (e) e.preventDefault()
    setError('')
    setOtpLoading(true)
    try {
      const res = await portalApi.register({ ...form, otp_code: otpCode })
      setSuccess(res.data)
      setShowOtp(false)
    } catch (err) {
      setError(err.response?.data?.detail || 'Invalid OTP. Please try again.')
    } finally {
      setOtpLoading(false)
    }
  }

  if (success) return (
    <div style={{
      minHeight: '100vh', background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'Inter, system-ui, sans-serif', padding: 20,
    }}>
      <div style={{ textAlign: 'center', maxWidth: 440 }}>
        <CheckCircle size={56} style={{ color: '#16a34a', margin: '0 auto 16px' }} />
        <h2 style={{ fontSize: 22, fontWeight: 700, color: '#0f172a', margin: '0 0 8px' }}>
          Application Submitted!
        </h2>
        <p style={{ color: '#374151', lineHeight: 1.6, marginBottom: 16 }}>
          Your KYC application (<strong>{success.kyc_id}</strong>) is under review.
          We'll email you at <strong>{form.email}</strong> within 1–2 business days.
        </p>
        <Link to="/portal/login" style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: '#16a34a', color: 'white', textDecoration: 'none',
          padding: '10px 20px', borderRadius: 8, fontWeight: 600, fontSize: 14,
        }}>
          <ArrowLeft size={14} /> Back to Login
        </Link>
      </div>
    </div>
  )

  return (
    <div style={{
      minHeight: '100vh', background: 'linear-gradient(135deg, #f0f9ff, #e0f2fe)',
      padding: '32px 20px', fontFamily: 'Inter, system-ui, sans-serif',
    }}>
      <div style={{ maxWidth: 680, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <Link to="/portal/login" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#3b82f6', textDecoration: 'none', fontSize: 13, marginBottom: 16 }}>
            <ArrowLeft size={13} /> Back to Login
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: 'linear-gradient(135deg, #3b82f6, #6366f1)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: 'white' }}>O2C</div>
            <div>
              <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: 0 }}>New Customer Application</h1>
              <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>Complete your KYC to access the B2B ordering portal</p>
            </div>
          </div>
        </div>

        {/* Invite banner — shown when arriving from an order invite email */}
        {inviteToken && (
          <div style={{
            background: '#eff6ff', border: '1.5px solid #bfdbfe', borderRadius: 12,
            padding: '14px 18px', marginBottom: 20,
            display: 'flex', alignItems: 'flex-start', gap: 12,
          }}>
            <Mail size={18} style={{ color: '#3b82f6', flexShrink: 0, marginTop: 1 }} />
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#1e40af' }}>Order held — complete registration to process it</div>
              <div style={{ fontSize: 12, color: '#3b82f6', marginTop: 3 }}>
                We received your order request from <strong>{inviteEmail}</strong>. Once you register and your account is approved, your order will be processed automatically.
              </div>
            </div>
          </div>
        )}

        {/* Form card */}
        <div style={{ background: 'white', borderRadius: 16, padding: 32, boxShadow: '0 4px 24px rgba(0,0,0,0.07)' }}>
          <form onSubmit={handleRequestOtp}>
            {/* Section: Business Info */}
            <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid #f1f5f9' }}>
              <h3 style={{ fontSize: 13, fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 16px' }}>
                Business Information
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <Field label="Company / Business Name" required>
                  <input style={inputStyle} value={form.company_name} onChange={set('company_name')} placeholder="Acme Industrials Pvt. Ltd." required />
                </Field>
                <Field label="Contact Person Name" required>
                  <input style={inputStyle} value={form.contact_name} onChange={set('contact_name')} placeholder="Rajesh Kumar" required />
                </Field>
                <Field label="Business Email" required>
                  <input style={{...inputStyle, background: inviteEmail ? '#f8fafc' : 'white'}}
                    type="email" value={form.email}
                    onChange={inviteEmail ? undefined : set('email')}
                    readOnly={!!inviteEmail}
                    placeholder="rajesh@acmeindustrials.com" required />
                </Field>
                <Field label="Phone Number" required>
                  <input style={inputStyle} type="tel" value={form.phone} onChange={set('phone')} placeholder="+91 98765 43210" required />
                </Field>
                <Field label="Business Type" required>
                  <select style={inputStyle} value={form.business_type} onChange={set('business_type')} required>
                    <option value="">Select type...</option>
                    {BUSINESS_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
                <Field label="Annual Turnover">
                  <select style={inputStyle} value={form.annual_turnover} onChange={set('annual_turnover')}>
                    <option value="">Select range...</option>
                    {TURNOVER_OPTIONS.map(t => <option key={t} value={t.split(' ')[0]}>{t}</option>)}
                  </select>
                </Field>
              </div>
            </div>

            {/* Section: Tax Info */}
            <div style={{ marginBottom: 24, paddingBottom: 20, borderBottom: '1px solid #f1f5f9' }}>
              <h3 style={{ fontSize: 13, fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 16px' }}>
                Tax & Compliance
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <Field label="GSTIN" required>
                  <input style={inputStyle} value={form.gstin} onChange={set('gstin')} placeholder="22AAAAA0000A1Z5" maxLength={15} required />
                </Field>
                <Field label="PAN Number" required>
                  <input style={inputStyle} value={form.pan_number} onChange={set('pan_number')} placeholder="AAAPL1234C" maxLength={10} required />
                </Field>
              </div>
            </div>

            {/* Section: Address */}
            <div style={{ marginBottom: 24 }}>
              <h3 style={{ fontSize: 13, fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 16px' }}>
                Business Address
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <Field label="State" required>
                  <select style={inputStyle} value={form.state} onChange={set('state')} required>
                    <option value="">Select state...</option>
                    {STATES.map(s => <option key={s} value={s}>{s}</option>)}
                  </select>
                </Field>
                <Field label="City" required>
                  <input style={inputStyle} value={form.city} onChange={set('city')} placeholder="Hyderabad" required />
                </Field>
                <div style={{ gridColumn: '1 / -1' }}>
                  <Field label="Complete Address" required>
                    <textarea
                      style={{ ...inputStyle, height: 72, resize: 'vertical' }}
                      value={form.address} onChange={set('address')}
                      placeholder="Plot No. 45, Industrial Area, Phase 2..."
                      required
                    />
                  </Field>
                </div>
              </div>
            </div>

            {error && !showOtp && (
              <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '10px 14px', fontSize: 13, color: '#dc2626', marginBottom: 16 }}>
                {error}
              </div>
            )}

            <button
              type="submit" disabled={loading}
              style={{
                width: '100%', padding: 12, borderRadius: 8, border: 'none',
                background: loading ? '#93c5fd' : 'linear-gradient(135deg, #3b82f6, #6366f1)',
                color: 'white', fontSize: 14, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? 'Sending OTP...' : 'Submit KYC Application'}
            </button>

            <p style={{ textAlign: 'center', marginTop: 12, fontSize: 12, color: '#94a3b8' }}>
              Your information is reviewed by our team within 1–2 business days.
            </p>
          </form>
        </div>
      </div>

      {/* OTP Modal */}
      {showOtp && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(15,23,42,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: 20 }}>
          <div style={{ background: 'white', width: '100%', maxWidth: 400, borderRadius: 16, padding: 32, boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)' }}>
            <h2 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: '0 0 8px', textAlign: 'center' }}>Verify Email</h2>
            <p style={{ fontSize: 13, color: '#64748b', textAlign: 'center', marginBottom: 24, lineHeight: 1.5 }}>
              We sent a 6-digit code to <strong>{form.email}</strong>.<br/>Please enter it below to complete registration.
            </p>
            {otpHint && (
              <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#1d4ed8', marginBottom: 16, textAlign: 'center', fontWeight: 600 }}>
                {otpHint}
              </div>
            )}
            
            <form onSubmit={handleVerifyAndSubmit}>
              <input
                type="text"
                maxLength={6}
                value={otpCode}
                onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ''))}
                placeholder="000000"
                style={{ ...inputStyle, textAlign: 'center', fontSize: 24, letterSpacing: '0.25em', padding: '16px 12px', fontWeight: 700, marginBottom: 16 }}
                required
              />

              {error && (
                <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: '8px 12px', fontSize: 12, color: '#dc2626', marginBottom: 16, textAlign: 'center' }}>
                  {error}
                </div>
              )}

              <button
                type="submit" disabled={otpLoading || otpCode.length !== 6}
                style={{
                  width: '100%', padding: 12, borderRadius: 8, border: 'none',
                  background: (otpLoading || otpCode.length !== 6) ? '#93c5fd' : '#16a34a',
                  color: 'white', fontSize: 14, fontWeight: 600, cursor: (otpLoading || otpCode.length !== 6) ? 'not-allowed' : 'pointer',
                  marginBottom: 12
                }}
              >
                {otpLoading ? 'Verifying...' : 'Verify & Complete'}
              </button>
              
              <button
                type="button" onClick={() => setShowOtp(false)}
                style={{ width: '100%', padding: 10, background: 'transparent', border: 'none', color: '#64748b', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
              >
                Cancel
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
