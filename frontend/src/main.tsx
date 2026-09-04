import { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type CaseRow = {
  id: string;
  customer_id: string;
  case_class: string;
  failure_category: string;
  state: string;
  amount_at_risk_paise: number;
  recovered_amount_paise: number | null;
  opened_at: string | null;
  latest_decision: { action: string; source: string; reason_codes: string[] } | null;
  latest_action: { action: string; state: string } | null;
};
type Detail = { case: CaseRow; timeline: { at: string | null; kind: string; title: string; actor: string; payload: Record<string, unknown> }[] };
type Approval = { id: string; requested_at: string; case: CaseRow; decision: string | null };
type Evaluation = { available: boolean; report?: { metrics: Record<string, any>[]; metadata: Record<string, any> }; message?: string };

const API = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const tabs = ['Overview', 'Cases', 'Approvals', 'Policy', 'Evaluation'];
const money = (paise: number | null | undefined) => `₹${((paise ?? 0) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`;
const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—';

async function get<T>(path: string): Promise<T> { const response = await fetch(`${API}${path}`); if (!response.ok) throw new Error(`${response.status} ${response.statusText}`); return response.json() as Promise<T>; }
function Badge({ value }: { value: string }) { return <span className={`badge badge-${value.toLowerCase().split('_').join('-')}`}>{value.split('_').join(' ')}</span>; }
function Metric({ label, value, note }: { label: string; value: string; note: string }) { return <article className="metric"><small>{label}</small><strong>{value}</strong><em>{note}</em></article>; }
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div>; }

function App() {
  const [tab, setTab] = useState('Overview');
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [policy, setPolicy] = useState<Record<string, any> | null>(null);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [stateFilter, setStateFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = async () => {
    setLoading(true); setError('');
    try {
      const query = stateFilter ? `?state=${encodeURIComponent(stateFilter)}` : '';
      const [caseRows, approvalRows, policyData, evaluationData] = await Promise.all([get<CaseRow[]>(`/api/cases${query}`), get<Approval[]>('/api/approvals'), get<Record<string, any>>('/api/policy'), get<Evaluation>('/api/evaluation')]);
      setCases(caseRows); setApprovals(approvalRows); setPolicy(policyData); setEvaluation(evaluationData);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'API unavailable'); } finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); }, [stateFilter]);
  const totalRisk = useMemo(() => cases.reduce((sum, item) => sum + item.amount_at_risk_paise, 0), [cases]);
  const recovered = useMemo(() => cases.reduce((sum, item) => sum + (item.recovered_amount_paise ?? 0), 0), [cases]);
  const violations = evaluation?.report?.metrics?.find((item) => item.arm === 'rules')?.safety?.policy_violations ?? 0;
  const openCase = async (id: string) => { try { setDetail(await get<Detail>(`/api/cases/${id}`)); } catch { setError('Could not load case timeline'); } };
  return <main>
    <header className="topbar"><div><p className="eyebrow">REVENUE RECOVERY / TEST MODE</p><h1>Recover revenue without unsafe retries.</h1><p className="lede">A policy-constrained operations console. Every treatment is explainable, revalidated, and auditable.</p></div><div className="status-stack"><span className="badge badge-live">Policy engine active</span><span className="mode-label">Real gateway calls are Test Mode only</span></div></header>
    <nav className="tabs" aria-label="Dashboard sections">{tabs.map((item) => <button className={tab === item ? 'active' : ''} key={item} onClick={() => setTab(item)}>{item}</button>)}</nav>
    {error && <div className="alert">API status: {error}. Start the backend at {API} to load live data.</div>}{loading && <div className="loading">Loading persisted operational data…</div>}
    {tab === 'Overview' && <Overview cases={cases} totalRisk={totalRisk} recovered={recovered} violations={violations} evaluation={evaluation} onCases={() => setTab('Cases')} onOpen={openCase} />}
    {tab === 'Cases' && <Cases cases={cases} stateFilter={stateFilter} setStateFilter={setStateFilter} onOpen={openCase} />}
    {tab === 'Approvals' && <Approvals approvals={approvals} onRefresh={refresh} />}{tab === 'Policy' && <Policy policy={policy} />}{tab === 'Evaluation' && <EvaluationPanel evaluation={evaluation} />}
    {detail && <CaseDrawer detail={detail} onClose={() => setDetail(null)} />}
  </main>;
}

function Overview({ cases, totalRisk, recovered, violations, evaluation, onCases, onOpen }: { cases: CaseRow[]; totalRisk: number; recovered: number; violations: number; evaluation: Evaluation | null; onCases: () => void; onOpen: (id: string) => void }) {
  const rules = evaluation?.report?.metrics?.find((item) => item.arm === 'rules');
  return <><section className="metrics"><Metric label="At-risk revenue" value={money(totalRisk)} note={`${cases.length} persisted case(s)`}/><Metric label="Recovered in cases" value={money(recovered)} note="Confirmed by payment evidence"/><Metric label="Policy violations" value={String(violations)} note="Must remain zero"/></section><section className="grid-two"><article className="panel"><div className="section-head"><div><p className="eyebrow">OPERATIONS</p><h2>Recovery queue</h2></div><button onClick={onCases}>Open cases</button></div>{cases.length ? <CaseTable cases={cases.slice(0, 8)} onOpen={onOpen}/> : <Empty text="No cases have been processed yet."/>}</article><article className="panel"><p className="eyebrow">LATEST EVALUATION</p><h2>Deterministic evidence</h2><div className="stat-line"><span>Rules recovery rate</span><strong>{rules ? `${(rules.recovery_rate * 100).toFixed(1)}%` : '—'}</strong></div><div className="stat-line"><span>Incremental recovery</span><strong>{rules ? `${(rules.incremental_recovery_rate * 100).toFixed(1)} pp` : '—'}</strong></div><div className="stat-line"><span>Report state</span><strong>{evaluation?.available ? 'Persisted' : 'Not generated'}</strong></div><p className="muted">The dashboard reads stored metrics JSON. It never recomputes evaluation results in the UI.</p></article></section><section className="timeline-banner"><p className="eyebrow">AUDIT TRAIL</p><h2>Every action must survive a second look.</h2><p>Open a case to inspect ingest, classification, decision, policy, scheduling, execution, gateway evidence, and rendered-message records in chronological order.</p></section></>;
}

function Cases({ cases, stateFilter, setStateFilter, onOpen }: { cases: CaseRow[]; stateFilter: string; setStateFilter: (value: string) => void; onOpen: (id: string) => void }) { return <section className="panel"><div className="section-head"><div><p className="eyebrow">CASE MANAGEMENT</p><h2>Cases</h2></div><select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}><option value="">All states</option>{['OPEN', 'CLASSIFIED', 'DECIDED', 'AWAITING_APPROVAL', 'SCHEDULED', 'RECOVERED', 'EXHAUSTED', 'STOPPED', 'EXPIRED'].map((value) => <option key={value}>{value}</option>)}</select></div>{cases.length ? <CaseTable cases={cases} onOpen={onOpen}/> : <Empty text="No cases match this filter."/>}</section>; }
function CaseTable({ cases, onOpen }: { cases: CaseRow[]; onOpen: (id: string) => void }) { return <div className="table-wrap"><table><thead><tr><th>Case</th><th>Class / failure</th><th>At risk</th><th>Action</th><th>State</th><th>Opened</th></tr></thead><tbody>{cases.map((item) => <tr key={item.id} onClick={() => onOpen(item.id)} className="clickable"><td><strong>{item.id}</strong><small>{item.customer_id}</small></td><td><Badge value={item.case_class}/><small>{item.failure_category}</small></td><td>{money(item.amount_at_risk_paise)}</td><td>{item.latest_action?.action ?? item.latest_decision?.action ?? 'WAIT'}</td><td><Badge value={item.state}/></td><td>{date(item.opened_at)}</td></tr>)}</tbody></table></div>; }
function Approvals({ approvals, onRefresh }: { approvals: Approval[]; onRefresh: () => void }) { const [token, setToken] = useState(''); const decide = async (approval: Approval, decision: 'APPROVED' | 'REJECTED') => { const note = window.prompt(`Reason for ${decision.toLowerCase()}:`, '') ?? ''; try { const response = await fetch(`${API}/api/approvals/${approval.id}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Approval-Token': token }, body: JSON.stringify({ decision, note }) }); if (!response.ok) throw new Error(await response.text()); onRefresh(); } catch (caught) { window.alert(caught instanceof Error ? caught.message : 'Approval failed'); } }; return <section className="panel"><div className="section-head"><div><p className="eyebrow">HUMAN CONTROL</p><h2>Approval queue</h2></div><input type="password" aria-label="Approval API token" placeholder="Internal approval token" value={token} onChange={(event) => setToken(event.target.value)}/></div><p className="muted">Approval actions are restricted, human-triggered, and never execute before an explicit decision.</p>{approvals.length ? <div className="approval-list">{approvals.map((approval) => <article className="approval" key={approval.id}><div><Badge value={approval.case.state}/><h3>{approval.case.id} · {money(approval.case.amount_at_risk_paise)}</h3><p>{approval.case.case_class} · {approval.case.failure_category} · requested {date(approval.requested_at)}</p></div><div className="button-row"><button onClick={() => void decide(approval, 'APPROVED')}>Approve</button><button className="danger" onClick={() => void decide(approval, 'REJECTED')}>Reject</button></div></article>)}</div> : <Empty text="No pending approvals."/>}</section>; }
function Policy({ policy }: { policy: Record<string, any> | null }) { return <section className="panel"><p className="eyebrow">POLICY VIEW</p><h2>Active deterministic controls</h2>{policy ? <><div className="hash">Config hash <code>{policy.config_hash}</code></div><pre>{JSON.stringify(policy.values, null, 2)}</pre></> : <Empty text="Policy data unavailable."/>}</section>; }
function EvaluationPanel({ evaluation }: { evaluation: Evaluation | null }) { return <section className="panel"><p className="eyebrow">EVALUATION</p><h2>Persisted metrics</h2>{evaluation?.available && evaluation.report ? <><div className="hash">Sample {evaluation.report.metadata.sample_size ?? '—'} · seed {evaluation.report.metadata.seed ?? '42'}</div><div className="evaluation-grid">{evaluation.report.metrics.map((item) => <article className="eval-card" key={item.arm}><Badge value={item.arm}/><strong>{(item.recovery_rate * 100).toFixed(1)}%</strong><span>{money(item.gross_recovered_paise)} recovered</span><small>violations: {item.safety?.policy_violations ?? 0}</small></article>)}</div><pre>{JSON.stringify(evaluation.report, null, 2)}</pre></> : <Empty text={evaluation?.message ?? 'Evaluation data unavailable.'}/>}</section>; }
function CaseDrawer({ detail, onClose }: { detail: Detail; onClose: () => void }) { return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" onClick={(event) => event.stopPropagation()}><div className="section-head"><div><p className="eyebrow">CASE TIMELINE</p><h2>{detail.case.id}</h2></div><button className="close" onClick={onClose}>Close</button></div><div className="case-summary"><Badge value={detail.case.state}/><strong>{money(detail.case.amount_at_risk_paise)}</strong><span>{detail.case.case_class} · {detail.case.failure_category}</span></div><div className="event-list">{detail.timeline.map((event, index) => <article className="event" key={`${event.at}-${index}`}><div className="event-dot"/><div><small>{date(event.at)} · {event.actor}</small><h3>{event.title}</h3><pre>{JSON.stringify(event.payload, null, 2)}</pre></div></article>)}</div></aside></div>; }

createRoot(document.getElementById('root')!).render(<App />);
