export default function Navbar({ page, setPage, citizen }) {
  const links = [['dashboard', 'Citizen Services'], ['officer', 'Officer Desk'], ['audit', 'Audit Lineage']];
  return <><header className="tricolor"/><nav><div className="brand"><span className="emblem">⚖</span><div>GovOrchestrator <small>महाराष्ट्र शासन · Federated Services</small></div></div><div className="navlinks">{citizen && links.map(([key, label]) => <button key={key} className={page === key ? 'active' : ''} onClick={() => setPage(key)}>{label}</button>)}</div>{citizen && <div className="signed">Signed in: {citizen.name}<br/><small>Citizen ID · {citizen.citizenId}</small></div>}</nav></>
}
