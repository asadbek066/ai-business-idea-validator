export default function LoadingSpinner() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-12" aria-label="Loading">
      <div className="w-10 h-10 border-2 border-amber-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-stone-500 text-sm">Analyzing your idea…</p>
    </div>
  );
}
