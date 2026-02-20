export default function ResultCard({ title, children, icon }) {
  return (
    <section className="bg-white rounded-xl border border-stone-200 p-5 shadow-sm">
      <h3 className="flex items-center gap-2 text-stone-800 font-semibold text-base mb-3">
        {icon && <span className="text-amber-500" aria-hidden>{icon}</span>}
        {title}
      </h3>
      <div className="text-stone-600 text-sm leading-relaxed whitespace-pre-wrap">
        {children || '—'}
      </div>
    </section>
  );
}
