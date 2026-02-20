import { useState } from 'react';
import { analyzeIdea } from './api';
import IdeaForm from './components/IdeaForm';
import ResultCard from './components/ResultCard';
import LoadingSpinner from './components/LoadingSpinner';
import ProviderSettings from './components/ProviderSettings';

const DEFAULT_PROVIDERS = {
  ollama: { enabled: true, url: 'http://localhost:11434', model: 'qwen2.5:1.5b', api_key: null },
  openai: { enabled: false, model: '', api_key: '' },
  azure_openai: { enabled: false, model: '', api_key: '', endpoint: '' },
  gemini: { enabled: false, model: '', api_key: '' },
  claude: { enabled: false, model: '', api_key: '' },
};

export default function App() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [providers, setProviders] = useState(() => {
    const saved = localStorage.getItem('ai_providers');
    return saved ? JSON.parse(saved) : DEFAULT_PROVIDERS;
  });

  const handleProviderChange = (newProviders) => {
    setProviders(newProviders);
    localStorage.setItem('ai_providers', JSON.stringify(newProviders));
  };

  const handleSubmit = async (idea) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await analyzeIdea(idea, providers);
      setResult(data);
    } catch (e) {
      setError(e.message || 'Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-stone-200 bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-2xl mx-auto px-4 py-5 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-stone-800">AI Business Idea Validator</h1>
            <p className="text-stone-500 text-sm mt-0.5">Get market potential, risks, first steps, and a verdict.</p>
          </div>
          <button
            onClick={() => setShowSettings(true)}
            className="px-3 py-1.5 text-sm rounded-lg border border-stone-300 hover:bg-stone-50 text-stone-700 transition-colors"
            title="AI Provider Settings"
          >
            ⚙️ Settings
          </button>
        </div>
      </header>

      <main className="flex-1 max-w-2xl mx-auto w-full px-4 py-8">
        <IdeaForm onSubmit={handleSubmit} disabled={loading} />

        {loading && <LoadingSpinner />}

        {error && (
          <div className="mt-6 p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm" role="alert">
            {error}
          </div>
        )}

        {result && !loading && (
          <div className="mt-8 space-y-4">
            {result.fallback_message && (
              <div className="p-4 rounded-xl bg-yellow-50 border border-yellow-200 text-yellow-800 text-sm" role="alert">
                ⚠️ {result.fallback_message}
              </div>
            )}
            {result.provider_used && (
              <div className="text-xs text-stone-500 mb-2">
                Powered by: <span className="font-medium">{result.provider_used}</span>
              </div>
            )}
            <ResultCard title="Market potential" icon="📈">{result.market_potential}</ResultCard>
            <ResultCard title="Risks & challenges" icon="⚠️">{result.risks}</ResultCard>
            <ResultCard title="First steps" icon="🎯">{result.first_steps}</ResultCard>
            <ResultCard title="Verdict" icon="✓">{result.verdict}</ResultCard>
          </div>
        )}
      </main>

      <footer className="border-t border-stone-200 py-4 text-center text-stone-400 text-xs">
        Uses AI for analysis. Not financial or legal advice.
      </footer>

      {showSettings && (
        <ProviderSettings
          providers={providers}
          onChange={handleProviderChange}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
