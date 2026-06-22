import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { complianceApi } from '../lib/api'
import { ScrollText, ShieldCheck } from 'lucide-react'

const RULES = [
  { id: 'RULE-001', name: 'ECOA Credit Audit', cat: 'ECOA', desc: 'Every credit decision logged with reason for ECOA compliance.' },
  { id: 'RULE-002', name: 'SOX Dual Approval', cat: 'SOX', desc: 'Credit memo above ₹50,000 requires Finance Controller HITL.' },
  { id: 'RULE-003', name: 'GDPR PII Masking', cat: 'GDPR', desc: 'All PII fields masked in agent tool call audit logs.' },
  { id: 'RULE-004', name: 'Credit Limit Block', cat: 'CREDIT', desc: 'Order above 90% credit limit triggers HITL Gate 2.' },
  { id: 'RULE-005', name: 'Fraud Block', cat: 'FRAUD', desc: 'XGBoost prob above 70% → auto-block + HITL Gate 3.' },
  { id: 'RULE-006', name: 'ECOA Bias Audit', cat: 'ECOA', desc: 'Monthly SHAP disparity analysis on credit decisions.' },
  { id: 'RULE-007', name: 'FDCPA Rate Limit', cat: 'FDCPA', desc: 'Max 2 dunning contacts/week. No late-night contact.' },
  { id: 'RULE-008', name: 'Audit Log Immutable', cat: 'SOX', desc: 'PostgreSQL RLS prevents UPDATE/DELETE on audit_log.' },
]

const CC = { ECOA: 'badge-blue', SOX: 'badge-violet', GDPR: 'badge-green', CREDIT: 'badge-amber', FRAUD: 'badge-red', FDCPA: 'badge-cyan' }

export default function CompliancePage() {
  const { data, isLoading } = useQuery({
    queryKey: ['audit-log'],
    queryFn: () => complianceApi.auditLog({ limit: 100 }).then(r => r.data),
  })
  const { data: ecoa } = useQuery({
    queryKey: ['ecoa'],
    queryFn: () => complianceApi.ecoaReport().then(r => r.data),
  })

  const log = data?.audit_log || []
  const ecoaDist = ecoa?.ecoa_distribution || []

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">Compliance and Audit</h1>
          <p className="page-subtitle">Policy Engine — ECOA · SOX · GDPR · FDCPA · Immutable audit trail</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <span className="badge badge-green"><ShieldCheck size={11} /> Policy Engine Active</span>
          <span className="badge badge-blue">{RULES.length} Rules</span>
        </div>
      </div>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <div className="card-header"><div className="card-title">Active Policy Rules</div></div>
          {RULES.map(r => (
            <div className="stat-row" key={r.id}>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                  <span style={{ fontFamily: 'monospace', fontSize: 10, color: 'var(--text-muted)' }}>{r.id}</span>
                  <span className={'badge ' + (CC[r.cat] || 'badge-gray')}>{r.cat}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>{r.name}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{r.desc}</div>
              </div>
              <span className="badge badge-green" style={{ flexShrink: 0 }}>Active</span>
            </div>
          ))}
        </div>

        <div className="card">
          <div className="card-header"><div className="card-title">ECOA Distribution</div></div>
          {ecoaDist.map(e => (
            <div className="stat-row" key={e.credit_risk_class}>
              <span className="stat-label">{e.credit_risk_class || '—'}</span>
              <span className="stat-val">{e.count}</span>
            </div>
          ))}
          <div className="alert alert-info" style={{ marginTop: 12, fontSize: 12 }}>
            Monthly SHAP bias audit ensures no disparity across protected categories per ECOA regulation.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <div className="card-title">Audit Log</div>
            <div className="card-subtitle">Append-only · PostgreSQL RLS · SOX compliant</div>
          </div>
          <span className="badge badge-violet">{log.length} entries</span>
        </div>
        {isLoading ? (
          <div className="loading-wrap"><div className="spinner" /></div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>#</th><th>Event</th><th>Agent</th><th>Customer</th>
                <th>Action</th><th>Policy Rule</th><th>Timestamp</th>
              </tr></thead>
              <tbody>
                {log.length === 0 ? (
                  <tr><td colSpan={7}>
                    <div className="empty-state">
                      <ScrollText size={28} style={{ opacity: 0.3 }} />
                      <div className="empty-title">No audit entries</div>
                      <div className="empty-text">Audit log fills as orders flow through the pipeline</div>
                    </div>
                  </td></tr>
                ) : log.map(e => (
                  <tr key={e.log_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{e.log_id}</td>
                    <td><span className="badge badge-blue">{e.event_type}</span></td>
                    <td style={{ fontSize: 11, color: 'var(--accent-cyan)' }}>{e.agent_name}</td>
                    <td style={{ fontSize: 11 }}>{e.customer_id || '—'}</td>
                    <td style={{ fontSize: 11, color: 'var(--text-primary)' }}>{e.action}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{e.policy_rule_id || '—'}</td>
                    <td style={{ fontSize: 10 }}>{e.created_at ? new Date(e.created_at).toLocaleString() : '—'}</td>
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
