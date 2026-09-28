import { useEffect, useRef, useState } from 'react';
import { ArrowRight, LoaderCircle, UserRound, UsersRound } from 'lucide-react';
import { HERO_IMAGES } from '../schemeImages';

const ROTATE_MS = 8000;

// Background photos crossfade slowly; they are decorative only (no captions,
// place names or credits). Only the first is loaded up front.
function useRotatingHero(count) {
  const [index, setIndex] = useState(0);
  const [loaded, setLoaded] = useState(() => new Set([0]));
  useEffect(() => {
    const reduceMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduceMotion || count < 2) return undefined;
    const timer = setInterval(() => {
      if (typeof document !== 'undefined' && document.hidden) return; // don't rotate in a background tab
      setIndex(current => {
        const next = (current + 1) % count;
        setLoaded(previous => new Set([...previous, next, (next + 1) % count]));
        return next;
      });
    }, ROTATE_MS);
    const warmup = setTimeout(() => setLoaded(previous => new Set([...previous, 1])), 1500);
    return () => { clearInterval(timer); clearTimeout(warmup); };
  }, [count]);
  return { index, loaded };
}

export default function LoginPage({ onLogin, onDemoLogin, loadDemoAccounts, language = 'en', notice = '' }) {
  const [userId, setUserId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [guestAccounts, setGuestAccounts] = useState([]);
  const [guestOpen, setGuestOpen] = useState(false);
  const [guestId, setGuestId] = useState('');
  const userIdRef = useRef(null);
  const isMr = language === 'mr';
  const { index, loaded } = useRotatingHero(HERO_IMAGES.length);
  const guest = guestAccounts.find(item => item.citizenId === guestId);

  useEffect(() => {
    if (!loadDemoAccounts) return undefined;
    let active = true;
    // Offered only when the server explicitly enables guest (sample) accounts.
    loadDemoAccounts().then(result => { if (active) setGuestAccounts(result?.accounts || []); }).catch(() => {});
    return () => { active = false; };
  }, [loadDemoAccounts]);

  function useOwnAccount() {
    setGuestOpen(false);
    setGuestId('');
    setError('');
    setTimeout(() => userIdRef.current?.focus(), 0);
  }

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      if (guest) await onDemoLogin(guest.citizenId);
      else await onLogin(userId.trim(), password);
    } catch (err) {
      setError(err.status === 401
        ? (isMr ? 'वापरकर्ता आयडी किंवा पासवर्ड चुकीचा आहे.' : 'The user ID or password is incorrect.')
        : err.message);
    } finally {
      setLoading(false);
    }
  }

  const canSubmit = guest ? true : Boolean(userId.trim() && password);

  return (
    <main className="landing">
      <div className="landing-backdrop" aria-hidden="true">
        {HERO_IMAGES.map((image, position) => loaded.has(position) && (
          <img key={image.key} className={`landing-photo${position === index ? ' visible' : ''}`} alt=""
            src={image.src} srcSet={`${image.srcSmall} 960w, ${image.src} 1920w`} sizes="100vw"
            decoding="async" fetchPriority={position === 0 ? 'high' : 'low'} />
        ))}
      </div>
      <div className="landing-inner">
        <section className="landing-story">
          <div className="landing-brand">
            <span className="logo-badge"><img src="/brand/sangam-logo-240.webp" alt="" width="104" height="58" /></span>
            <div>
              <h1>SANGAM</h1>
              <p className="landing-tagline">{isMr ? 'फेडरेटेड शासकीय इंटरऑपरेबिलिटी प्लॅटफॉर्म' : 'Federated Government Interoperability Platform'}</p>
            </div>
          </div>
          <p className="landing-headline">{isMr ? 'एकाच जोडलेल्या व्यासपीठावरून शासकीय सेवा मिळवा.' : 'Access public services through one connected platform.'}</p>
          <p className="landing-lead">{isMr
            ? 'सेवांसाठी अर्ज करा, आपल्या संमतीने पडताळलेली माहिती पुन्हा वापरा आणि सर्व अर्जांचा एकाच ठिकाणी मागोवा घ्या.'
            : 'Apply for services, reuse verified information with your consent, and track applications in one place.'}</p>
        </section>

        <form className="card login-card" onSubmit={submit} aria-labelledby="login-title">
          <h2 id="login-title">{isMr ? 'साइन इन करा' : 'Sign in'}</h2>
          {notice && <p className="alert notice" role="status">{notice}</p>}

          {guest ? (
            <div className="guest-selected">
              <UsersRound size={20} aria-hidden="true" />
              <div>
                <span className="muted small-text">{isMr ? 'अतिथी खाते' : 'Guest account'}</span>
                <b>{guest.name}</b>
              </div>
              <button type="button" className="link" onClick={useOwnAccount}>{isMr ? 'बदला' : 'Change'}</button>
            </div>
          ) : (
            <>
              <label htmlFor="login-user-id">{isMr ? 'वापरकर्ता आयडी' : 'User ID'}</label>
              <div className="input-with-icon">
                <UserRound size={18} aria-hidden="true" />
                <input id="login-user-id" ref={userIdRef} name="username" autoComplete="username" required value={userId}
                  onChange={event => setUserId(event.target.value)} aria-invalid={Boolean(error)} aria-describedby={error ? 'login-error' : undefined} />
              </div>
              <label htmlFor="login-password">{isMr ? 'पासवर्ड' : 'Password'}</label>
              <input id="login-password" name="password" type="password" autoComplete="current-password" required
                value={password} onChange={event => setPassword(event.target.value)}
                aria-invalid={Boolean(error)} aria-describedby={error ? 'login-error' : undefined} />
            </>
          )}
          {error && <p className="alert danger" id="login-error" role="alert">{error}</p>}
          <button className="primary wide button-with-icon" disabled={loading || !canSubmit}>
            {loading ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <ArrowRight size={18} aria-hidden="true" />}
            {loading ? (isMr ? 'साइन इन होत आहे…' : 'Signing in…') : (isMr ? 'साइन इन करा' : 'Sign in')}
          </button>

          {guestAccounts.length > 0 && !guest && (
            <div className="guest-access">
              {!guestOpen ? (
                <button type="button" className="link" onClick={() => setGuestOpen(true)}>{isMr ? 'अतिथी खात्याने सुरू ठेवा' : 'Continue with a guest account'}</button>
              ) : (
                <>
                  <label htmlFor="guest-account">{isMr ? 'अतिथी खाते' : 'Guest account'}</label>
                  <select id="guest-account" value={guestId} onChange={event => { setGuestId(event.target.value); setError(''); }}>
                    <option value="">{isMr ? 'खाते निवडा' : 'Select an account'}</option>
                    {guestAccounts.map(item => <option key={item.citizenId} value={item.citizenId}>{item.name}</option>)}
                  </select>
                </>
              )}
            </div>
          )}
        </form>
      </div>
    </main>
  );
}
