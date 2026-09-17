import { useEffect, useRef, useState } from 'react';
import { analyzeIdea } from './api';
import {
  loadPersistedProviders,
  stripApiKeys,
} from './providerConfig';
import IdeaForm from './components/IdeaForm';
import ResultCard from './components/ResultCard';
import LoadingSpinner from './components/LoadingSpinner';
import ProviderSettings from './components/ProviderSettings';

export default function App() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [providers, setProviders] = useState(loadPersistedProviders);
  const requestControllerRef = useRef(null);

  useEffect(() => () => {
    requestControllerRef.current?.abort();
  }, []);

  const handleProviderChange = (newProviders) => {
    setProviders(newProviders);
    try {
      localStorage.setItem('ai_providers', JSON.stringify(stripApiKeys(newProviders)));
    } catch {
      // Settings still apply for this tab if storage is unavailable.
    }
  };

  const handleSubmit = async (idea) => {
    if (requestControllerRef.current) return;

    const controller = new AbortController();
    requestControllerRef.current = controller;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await analyzeIdea(idea, providers, { signal: controller.signal });
      setResult(data);
    } catch (requestError) {
      if (requestError?.name !== 'AbortError') {
        setError(requestError?.message || 'Something went wrong. Please try again.');
      }
    } finally {
      if (requestControllerRef.current === controller) {
        requestControllerRef.current = null;
        setLoading(false);
      }
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-stone-200 bg-white/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-2xl mx-auto px-4 py-5 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold text-stone-800">Business Idea Validator</h1>
            <p className="text-stone-500 text-sm mt-0.5">
              Market potential, risks, first steps, and a practical verdict.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSettings(true)}
            className="shrink-0 px-3 py-1.5 text-sm rounded-lg border border-stone-300 hover:bg-stone-50 text-stone-700 transition-colors"
            title="Provider settings"
            aria-haspopup="dialog"
          >
            Settings
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
          <div className="mt-8 space-y-4" aria-label="Business idea analysis">
            {result.provider_used && (
              <div className="text-xs text-stone-500 mb-2">
                Provider: <span className="font-medium">{result.provider_used}</span>
              </div>
            )}
            <ResultCard title="Market potential">{result.market_potential}</ResultCard>
            <ResultCard title="Risks and challenges">{result.risks}</ResultCard>
            <ResultCard title="First steps">{result.first_steps}</ResultCard>
            <ResultCard title="Verdict">{result.verdict}</ResultCard>
          </div>
        )}
      </main>

      <footer className="border-t border-stone-200 py-4 text-center text-stone-400 text-xs">
        For planning only. Not financial or legal advice.
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
