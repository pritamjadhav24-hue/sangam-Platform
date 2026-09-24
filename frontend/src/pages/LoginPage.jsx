import { useState } from 'react';
import SangamMark from '../components/SangamMark';

export default function LoginPage({ onLogin, language = 'en', demoCitizens = [], onDemoSwitch }) {
  const [citizenId, setCitizenId] = useState('CITIZEN_001'); const [password, setPassword] = useState(''); const [error, setError] = useState(''); const [loading, setLoading] = useState(false);
  // DEMO ONLY: the backend lists demo citizens only when demo switching is
  // enabled (never in production), so this panel simply doesn't render otherwise.
  async function demoSignIn(event) { const id = event.target.value; if (!id) return; setLoading(true); setError(''); try { await onDemoSwitch(id); } catch (err) { setError(err.message); setLoading(false); } }
  async function submit(event) { event.preventDefault(); setLoading(true); setError(''); try { await onLogin(citizenId, password); } catch (err) { setError(err.message); } finally { setLoading(false); } }
  const isMr = language === 'mr';
  return (
    <main className="login">
      <section className="login-story">
        <div className="brand-lockup">
          <SangamMark size={52} />
          <div>
            <strong>SANGAM</strong>
            <small>{isMr ? 'फेडरेटेड शासकीय इंटरऑपरेबिलिटी प्लॅटफॉर्म' : 'Federated Government Interoperability Platform'}</small>
          </div>
        </div>
        <p className="eyebrow">{isMr ? 'SIH २०२६ · प्रोटोटाइप' : 'SIH 2026 · Prototype'}</p>
        <h1>{isMr ? 'शासकीय सेवांचे अखंड, सुलभ एकत्रीकरण.' : 'Connecting government services, seamlessly.'}</h1>
        <p>{isMr ? 'सेवांकरिता अर्ज करा, पडताळलेली माहिती पुन्हा वापरा आणि एकाच ठिकाणाहून अर्जाचा मागोवा घ्या.' : 'Apply for services, reuse verified information and track your applications from one place.'}</p>
        <div className="network-visual" aria-hidden="true">
          <span className="network-node central">S</span>
          <span className="network-node n1">R</span>
          <span className="network-node n2">E</span>
          <span className="network-node n3">C</span>
          <i className="line l1" />
          <i className="line l2" />
          <i className="line l3" />
        </div>
        <div className="security-note">
          <b>{isMr ? 'प्रोटोटाइप वातावरण' : 'Prototype environment'}</b><br />
          {isMr ? 'उद्देश-मर्यादित प्रवेश · सुरक्षित विभागीय जोडणी' : 'Purpose-bound access · Secure department connections'}
        </div>
      </section>
      <form className="card login-card" onSubmit={submit}>
        <div className="seal">
          महाराष्ट्र शासन<br />
          <b>{isMr ? 'सुरक्षित नमुना साइन-इन' : 'Secure demo sign-in'}</b>
        </div>
        <h2>{isMr ? 'SANGAM मध्ये साइन इन करा' : 'Sign in to SANGAM'}</h2>
        <p className="muted">{isMr ? 'पुढे जाण्यासाठी आपली नमुना ओळख वापरा.' : 'Use your prototype identity to continue.'}</p>
        <label>
          {isMr ? 'वापरकर्ता आयडी' : 'User ID'}
          <input value={citizenId} onChange={event => setCitizenId(event.target.value)} />
        </label>
        <label>
          {isMr ? 'पासवर्ड' : 'Password'}
          <input type="password" value={password} onChange={event => setPassword(event.target.value)} />
        </label>
        {error && <p className="alert danger">{error}</p>}
        <button className="primary" disabled={loading}>
          {loading ? (isMr ? 'ओळख पडताळत आहे…' : 'Verifying identity…') : (isMr ? 'पडताळणी करा व पुढे जा' : 'Verify & continue')}
        </button>
        {demoCitizens.length > 0 && onDemoSwitch && (
          <label className="demo-switcher login-demo-switcher">
            <span className="demo-switcher-badge">DEMO</span>
            <select aria-label={isMr ? 'डेमो नागरिक म्हणून पुढे जा' : 'Continue as a demo citizen'} defaultValue="" disabled={loading} onChange={demoSignIn}>
              <option value="" disabled>{isMr ? 'डेमो नागरिक म्हणून पुढे जा' : 'Continue as a demo citizen'}</option>
              {demoCitizens.map(item => <option key={item.citizenId} value={item.citizenId}>{item.name}{item.persona ? ` · ${item.persona.replace(/_/g, ' ')}` : ''}</option>)}
            </select>
          </label>
        )}
        <div className="demo-credentials">
          <b>{isMr ? 'नमुना ओळख (डेमो)' : 'Demo identities'}</b>
          {/* Account IDs only: passwords are set per deployment (.env) and are never shipped in the UI. */}
          <span>{isMr ? 'नागरिक' : 'Citizen'} · <code>CITIZEN_001</code> · <code>CITIZEN_002</code></span>
          <span>{isMr ? 'अधिकारी' : 'Officer'} · <code>OFFICER_MH_01</code></span>
          <span>{isMr ? 'प्रशासक' : 'Admin'} · <code>ADMIN_MH_01</code></span>
        </div>
      </form>
    </main>
  );
}
