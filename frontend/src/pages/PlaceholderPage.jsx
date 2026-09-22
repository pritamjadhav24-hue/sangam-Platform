export default function PlaceholderPage({ title, eyebrow, message }) {
  return (
    <main className="container narrow">
      <div className="page-title"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1></div></div>
      <div className="empty-state card">
        <span>○</span>
        <p>{message}</p>
      </div>
    </main>
  );
}
