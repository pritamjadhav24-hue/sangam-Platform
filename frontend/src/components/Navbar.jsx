export default function Navbar({ page, setPage, citizen }) {
  const role = citizen?.role;
  const links = role === 'CITIZEN' ? [['dashboard', 'Citizen Services']] : role === 'OFFICER' ? [['officer', 'Officer Desk']] : role === 'ADMIN' ? [['health', 'Integration Health'], ['audit', 'Audit Lineage']] : [];
  return <><header className="tricolor"/><nav><div className="brand"><span className="emblem">⚖</span><div>GovOrchestrator <small>महाराष्ट्र शासन · Federated Services</small></div></div><div className="navlinks">{citizen && links.map(([key, label]) => <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>{label}</button>)}</div>{citizen && <div className="signed">Signed in: {citizen.name}<br/><small>{role} · {citizen.userId || citizen.citizenId}</small></div>}</nav></>
}
