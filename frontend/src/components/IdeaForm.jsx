import { useState } from 'react';

export default function IdeaForm({ onSubmit, disabled, placeholder = 'e.g. A subscription box for indoor plant enthusiasts with care tips and rare seeds' }) {
  const [idea, setIdea] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!idea.trim() || disabled) return;
    onSubmit(idea.trim());
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <label htmlFor="idea" className="block text-sm font-medium text-stone-700 sr-only">
        Business idea
      </label>
      <textarea
        id="idea"
        value={idea}
        onChange={(e) => setIdea(e.target.value)}
        placeholder={placeholder}
        rows={4}
        maxLength={2000}
        disabled={disabled}
        className="w-full px-4 py-3 rounded-xl border border-stone-300 bg-white text-stone-800 placeholder-stone-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent resize-y disabled:opacity-60 disabled:cursor-not-allowed"
        aria-describedby="idea-hint"
      />
      <p id="idea-hint" className="text-xs text-stone-500">
        {idea.length}/2000 characters
      </p>
      <button
        type="submit"
        disabled={!idea.trim() || disabled}
        className="w-full py-3 px-4 rounded-xl bg-amber-500 hover:bg-amber-600 disabled:bg-stone-300 disabled:cursor-not-allowed text-white font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2"
      >
        {disabled ? 'Analyzing…' : 'Analyze idea'}
      </button>
    </form>
  );
}
