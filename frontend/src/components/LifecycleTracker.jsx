const order = ['Submitted', 'Identity', 'Income', 'Academic', 'Domicile', 'Officer Review', 'Completed'];
export default function LifecycleTracker({ timeline = [] }) {
  const states = Object.fromEntries(timeline.map(x => [x.stage, x.state]));
  return <div className="lifecycle">{order.map((stage, i) => <div className="life" key={stage}><i className={(states[stage] || 'PENDING').toLowerCase()}>{i + 1}</i><span>{stage}</span><em>{(states[stage] || 'PENDING').replace('_', ' ')}</em></div>)}</div>
}
