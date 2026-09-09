import { useEffect, useState } from 'react';

export default function OfficerDashboard({ onQueue, onAction }) {
  const [queue, setQueue] = useState([]);
  const [remarks, setRemarks] = useState({});
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const refresh = () => onQueue().then(x => setQueue(x.applications)).catch(e => setError(e.message));
  useEffect(refresh, []);
  async function act(id, action) {
    try { await onAction(id, action, remarks[id] || 'Decision recorded after eligibility review.'); setMessage(`${action} recorded.`); setError(''); refresh(); } catch (e) { setError(e.message); }
  }
  async function decideReview(appId, reviewId, decision) {
    try { await onAction(appId, decision, remarks[reviewId] || `Entity match ${decision.toLowerCase()} by officer.`, reviewId); setMessage(`Entity review ${decision} recorded.`); setError(''); refresh(); } catch (e) { setError(e.message); }
  }
  return <main className="container"><div className="page-title"><div><p className="eyebrow">Higher Education Department · restricted view</p><h1>Officer review queue</h1><p>Only eligibility-relevant attributes and safe match metadata are visible. Raw documents and unnecessary personal data are not exposed.</p></div></div>{message && <div className="alert success">{message}</div>}{error && <div className="alert danger">{error}</div>}<div className="card"><table><thead><tr><th>Application</th><th>Eligibility</th><th>Required attributes</th><th>Entity-resolution review</th><th>Officer remarks</th><th>Decision</th></tr></thead><tbody>{queue.map(a => <tr key={a.appId}><td><b>{a.appId}</b><small>{a.status}</small></td><td>{a.eligibility.eligible ? <span className="good">Rules passed</span> : a.eligibility.reasons.join(' ')}</td><td>{a.requirements.map(r => <small key={r.code}>{r.code}: {r.status}<br /></small>)}</td><td>{a.entityReviews?.length ? a.entityReviews.map(item => <div className="review-box" key={item.reviewId}><b>{item.requirementCode}</b><small>{item.source} · {item.sourceRecordId}</small><small>Confidence: {item.confidenceLevel} · {Math.round(item.confidenceScore * 100)}%</small><small>Matched: {item.matchedFields.join(', ') || 'None'}</small><small>Decision: {item.decision || 'REVIEW'}</small>{item.status === 'WAITING_FOR_OFFICER' && <div className="button-stack"><button className="small approve" onClick={() => decideReview(a.appId, item.reviewId, 'MATCH')}>MATCH</button><button className="small reject" onClick={() => decideReview(a.appId, item.reviewId, 'REJECT')}>REJECT</button></div>}</div>) : <span className="muted">No entity review required.</span>}</td><td><textarea value={remarks[a.appId] || ''} onChange={e => setRemarks({ ...remarks, [a.appId]: e.target.value })} placeholder="Required decision remarks" /></td><td className="button-stack"><button className="small approve" onClick={() => act(a.appId, 'APPROVE')}>Approve</button><button className="small" onClick={() => act(a.appId, 'REQUEST_INFO')}>Request info / Resubmit</button><button className="small reject" onClick={() => act(a.appId, 'REJECT')}>Reject</button></td></tr>)}</tbody></table>{!queue.length && <p className="muted">No applications currently require officer review.</p>}</div></main>
}
