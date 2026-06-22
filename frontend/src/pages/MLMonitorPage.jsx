import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { mlApi, analyticsApi } from '../lib/api'
import { Activity, Cpu, RefreshCw, TrendingUp } from 'lucide-react'

const STATUS_DOT = { active: 'live', placeholder: 'placeholder', warning: 'amber' }
const STATUS_COLOR = { active: 'var(--accent-green)', placeholder: 'var(--accent-amber)', warning: 'var(--accent-red)' }

const MODEL_META = {
  'Isolation Forest':     { agent: 'Agent 3', role: 'Anomaly detection — flags statistically unusual orders', input: '7 order/customer features', output: 'anomaly_score 0-1 + flag (>0.55 = anomaly)', trained: 'Startup (unsupervised, no dataset needed)' },
  'XGBoost Fraud':        { agent: 'Agent 3', role: 'Fraud pattern classification — knows known fraud behaviors', input: 'Amount, customer age, DSO, AR ratio, hour, channel', output: 'fraud_probability 0-1 · FRAUD or CLEAR verdict', trained: 'Kaggle 284K EU CC Fraud transactions' },
  'XGBoost Credit':       { agent: 'Agent 2', role: 'Credit risk classification — 3-class bucket', input: 'Order value, credit limit, AR balance, missed payments', output: 'credit_risk_class: LOW / MEDIUM / HIGH', trained: 'UCI Polish Companies Bankruptcy dataset' },
  'PD Logistic Reg':      { agent: 'Agent 2', role: 'Probability of Default — calibrated exact %, not buckets', input: 'Same as XGBoost Credit', output: 'pd_score 0.0 to 1.0 (e.g. 0.042 = 4.2% default chance)', trained: 'UCI Default of Credit Card Clients 30K rows' },
  'XGBoost Delay':        { agent: 'Agent 7', role: 'Payment delay prediction — how likely is this invoice late?', input: 'Invoice amount, terms days, DSO, missed payments, AR ratio', output: 'late_probability 0-1 + bucket GREEN/AMBER/RED', trained: 'Kaggle IBM B2B Late Payment dataset' },
  'Prophet Demand':       { agent: 'Agent 4', role: 'Daily SKU demand forecast — 30-day horizon', input: 'Historical order series by SKU', output: 'yhat (forecast) + yhat_lower/upper (95% confidence band)', trained: 'M5 Walmart 5-SKU trained models (.json) on disk' },
  'K-Means Clustering':   { agent: 'Agent 8', role: 'Customer segmentation — drives dunning email tone', input: 'Total paid, AR outstanding, avg DSO per customer', output: 'Segment: Premium / Standard / At-Risk / Problem', trained: 'Startup (unsupervised, from live customer data)' },
  'MiniLM Embeddings':    { agent: 'Agent 9', role: 'Semantic invoice matching — touchless cash application', input: 'Remittance text + invoice description (384-dim vectors)', output: 'cosine_similarity 0-1 → auto-post ≥0.78, HITL <0.50', trained: 'Pre-trained HuggingFace (no training needed)' },
  'GLiNER NER':           { agent: 'Agent 1', role: 'Named Entity Recognition — extracts SKU, qty, customer from email', input: 'Raw email text', output: 'Entities: customer_name, item_code, quantity, delivery_date', trained: 'Pre-trained zero-shot model' },
}

export default function MLMonitorPage() {
  const [expandedModel, setExpandedModel] = useState(null)
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['ml-models'],
    queryFn: () => mlApi.models().then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: kpis } = useQuery({ queryKey: ['analytics-kpis'], queryFn: () => analyticsApi.kpis().then(r => r.data) })

  const models = data?.models || []
  const live = models.filter(m => m.status === 'active')
  const needs = models.filter(m => m.status !== 'active')

  const agentGroups = {}
  models.forEach(m => {
    const meta = MODEL_META[m.name] || {}
    const agent = meta.agent || 'Other'
    if (!agentGroups[agent]) agentGroups[agent] = []
    agentGroups[agent].push({ ...m, meta })
  })

  const toggleExpand = (name) => setExpandedModel(p => p === name ? null : name)

  return (
    <div className="page-content animate-fade">
      <div className="page-header">
        <div className="page-header-left">
          <h1 className="page-title">ML Model Monitor</h1>
          <p className="page-subtitle">
            {live.length} / {models.length || 9} models active · Runtime status from live predictions
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => refetch()}><RefreshCw size={12} /> Refresh</button>
          {live.length === (models.length || 9)
            ? <span className="badge badge-green"><span className="ml-dot live" />All Systems Operational</span>
            : <span className="badge badge-amber"><span className="ml-dot placeholder" />{needs.length} need attention</span>}
        </div>
      </div>

      {/* KPI Cards */}
      <div className="kpi-grid" style={{ marginBottom: 20 }}>
        <div className="kpi-card">
          <div className="kpi-label">Total Models</div>
          <div className="kpi-value">{models.length || 9}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Active & Trained</div>
          <div className="kpi-value" style={{ color: 'var(--accent-green)' }}>{live.length}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Auto-Process Rate</div>
          <div className="kpi-value" style={{ color: 'var(--accent-blue)' }}>
            {(((kpis?.auto_process_rate || 0) * 100).toFixed(0))}%
          </div>
          <div className="kpi-delta">Driven by all ML models combined</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Training Cost</div>
          <div className="kpi-value" style={{ color: 'var(--accent-green)' }}>₹0</div>
          <div className="kpi-delta">100% free open datasets</div>
        </div>
      </div>

      {/* Model cards grouped by Agent */}
      {isLoading ? <div className="loading-wrap"><div className="spinner" /></div> : (
        Object.entries(agentGroups).sort(([a], [b]) => a.localeCompare(b)).map(([agent, agentModels]) => (
          <div key={agent} className="card" style={{ marginBottom: 12 }}>
            <div className="card-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Cpu size={14} style={{ color: 'var(--accent-cyan)' }} />
                <div className="card-title">{agent}</div>
              </div>
              <span className="badge badge-green">{agentModels.filter(m => m.status === 'active').length}/{agentModels.length} active</span>
            </div>
            {agentModels.map(m => {
              const isExp = expandedModel === m.name
              const dotClass = STATUS_DOT[m.status] || 'placeholder'
              const meta = m.meta || {}
              return (
                <div key={m.name}>
                  <div
                    onClick={() => toggleExpand(m.name)}
                    style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}
                  >
                    <span className={`ml-dot ${dotClass}`} />
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 2 }}>{m.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{meta.role || m.source}</div>
                    </div>
                    <span className={`badge ${m.status === 'active' ? 'badge-green' : 'badge-amber'}`}>{m.status === 'active' ? 'Live' : 'Check'}</span>
                    <span className="badge badge-gray">{m.type || 'ML'}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{isExp ? '▲' : '▼'}</span>
                  </div>
                  {isExp && (
                    <div style={{ background: 'rgba(59,130,246,.04)', borderRadius: 8, padding: '12px 16px', margin: '8px 0 4px 0', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                      {[
                        ['Input Features', meta.input],
                        ['Output', meta.output],
                        ['Trained On', meta.trained],
                        ['Role in Pipeline', meta.role],
                      ].map(([label, val]) => (
                        <div key={label}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent-cyan)', textTransform: 'uppercase', marginBottom: 4 }}>{label}</div>
                          <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{val || '—'}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        ))
      )}

      {/* Model Architecture Summary */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">Pipeline Model Architecture</div>
          <span className="badge badge-blue">How all 9 models connect</span>
        </div>
        {[
          ['Agent 1 → Order Ingestion',  'GLiNER NER (extracts entities) → Groq LLM (validates + corrects) → MiniLM (customer lookup)', 'var(--accent-blue)'],
          ['Agent 2 → Credit Check',     'XGBoost Credit (3-class risk) + PD Logistic Reg (exact % default) → Policy Engine (Rule-001 to Rule-008)', 'var(--accent-cyan)'],
          ['Agent 3 → Fraud Detection',  'Isolation Forest (anomaly score) + XGBoost Fraud (pattern match) → dual-flag = auto-block', 'var(--accent-red)'],
          ['Agent 4 → Demand Forecast',  'Prophet (trained, 1 model per SKU) → 30-day daily forecast with 95% confidence bands', 'var(--accent-violet)'],
          ['Agent 7 → Payment Monitor',  'XGBoost Delay → late_probability per open invoice → updates collection_priority every 15 min', 'var(--accent-amber)'],
          ['Agent 8 → Collections',      'K-Means (4 segments) → tone = Premium/Standard/At-Risk/Problem → Groq writes dunning email', 'var(--accent-green)'],
          ['Agent 9 → Cash Application', 'MiniLM (384-dim) → cosine similarity → ≥78% auto-post · 50-77% Groq verify · <50% HITL', 'var(--accent-cyan)'],
        ].map(([step, desc, color]) => (
          <div key={step} style={{ display: 'flex', gap: 12, padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
            <div style={{ width: 3, background: color, borderRadius: 2, flexShrink: 0 }} />
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color, marginBottom: 3 }}>{step}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>{desc}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
