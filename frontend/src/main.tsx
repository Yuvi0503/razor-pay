import React from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const rows = [
  ['One-off payment', 'INSUFFICIENT_FUNDS', 'Payment link + rendered reminder', 'Scheduled'],
  ['Mandate renewal', 'TEMPORARY_BANK_ERROR', 'Retry deferred: rail degraded', 'Policy hold'],
  ['One-off payment', 'AUTHENTICATION_FAILED', 'Suggest alternate method', 'Open'],
];
function App() {
 return <main><header><div><p className="eyebrow">REVENUE RECOVERY / TEST MODE</p><h1>Recover revenue without unsafe retries.</h1></div><span className="badge">Policy engine active</span></header>
 <section className="metrics"><article><small>At-risk revenue</small><strong>₹ —</strong><em>From latest evaluation</em></article><article><small>Incremental recovery</small><strong>— pp</strong><em>Control-adjusted</em></article><article><small>Safety violations</small><strong>0</strong><em>Required invariant</em></article></section>
 <section className="panel"><div className="section-head"><h2>Recovery queue</h2><button>Run evaluation</button></div><table><thead><tr><th>Case</th><th>Failure</th><th>Next action</th><th>State</th></tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((x,j)=><td key={j}>{x}</td>)}</tr>)}</tbody></table></section>
 <section className="timeline"><p className="eyebrow">AUDIT TRAIL</p><h2>Every action must survive a second look.</h2><p>Scheduled work is revalidated before execution. If a customer pays meanwhile, the action is skipped and the reason becomes part of the case record.</p></section></main>
}
createRoot(document.getElementById('root')!).render(<App/>);
