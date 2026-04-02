import { useState, useEffect, useRef, useCallback } from 'react';

const DRAFT_KEY = 'ai_providers_draft';
const PROVIDER_ORDER = [
  { name: 'openai', label: 'OpenAI' },
  { name: 'azure_openai', label: 'Azure OpenAI' },
  { name: 'gemini', label: 'Google Gemini' },
  { name: 'claude', label: 'Anthropic Claude' },
];

function stripApiKeys(config) {
  const copy = JSON.parse(JSON.stringify(config || {}));
  Object.keys(copy).forEach((name) => {
    if (copy[name] && typeof copy[name] === 'object') {
      copy[name].api_key = '';
    }
  });
  return copy;
}

function ProviderOption({
  name,
  label,
  isSelected,
  config,
  onSelect,
  onUpdateField,
  onTestApiKey,
  testingKey,
  keyStatus,
}) {
  return (
    <div className="space-y-3" key={name}>
      <div
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onSelect();
          }
        }}
        className="w-full flex items-center gap-3 cursor-pointer p-3 rounded-lg border-2 transition-colors hover:bg-stone-50 text-left"
        style={{ borderColor: isSelected ? '#f59e0b' : '#e5e7eb' }}
      >
        <input
          type="radio"
          name="ai_provider"
          value={name}
          checked={isSelected}
          onChange={onSelect}
          onClick={(e) => e.stopPropagation()}
          className="w-4 h-4 text-amber-500 focus:ring-amber-500"
          aria-label={`${label} provider`}
        />
        <span className="font-medium text-stone-800 flex-1">{label}</span>
        <span className="text-xs text-stone-500">{isSelected ? 'Selected' : 'Select'}</span>
      </div>

      {isSelected && (
        <div className="ml-7 space-y-3 p-4 bg-stone-50 rounded-lg border border-stone-200">
          <div>
            <label className="block text-sm font-medium text-stone-700 mb-1">
              Model Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={config?.model ?? ''}
              onChange={(e) => onUpdateField(name, 'model', e.target.value)}
              placeholder={
                name === 'openai' ? 'gpt-4o-mini' :
                name === 'claude' ? 'claude-3-haiku-20240307' :
                name === 'gemini' ? 'gemini-pro' :
                'your-model-name'
              }
              className="w-full px-3 py-2 text-sm rounded-lg border border-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-stone-700 mb-1">
              API Key <span className="text-red-500">*</span>
            </label>
            <input
              type="password"
              value={config?.api_key ?? ''}
              onChange={(e) => onUpdateField(name, 'api_key', e.target.value)}
              placeholder="Enter your API key"
              className="w-full px-3 py-2 text-sm rounded-lg border border-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
              required
            />
            <button
              type="button"
              onClick={onTestApiKey}
              className="mt-2 px-3 py-1.5 text-xs rounded-lg border border-stone-300 hover:bg-stone-100 text-stone-700"
            >
              {testingKey ? 'Testing...' : 'Test API Key'}
            </button>
          </div>

          {name === 'azure_openai' && (
            <div>
              <label className="block text-sm font-medium text-stone-700 mb-1">
                Endpoint URL <span className="text-red-500">*</span>
              </label>
              <input
                type="text"
                value={config?.endpoint ?? ''}
                onChange={(e) => onUpdateField(name, 'endpoint', e.target.value)}
                placeholder="https://your-resource.openai.azure.com"
                className="w-full px-3 py-2 text-sm rounded-lg border border-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                required
              />
            </div>
          )}

          {keyStatus && (
            <div className={`p-3 rounded-lg text-sm ${
              keyStatus.type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' :
              keyStatus.type === 'error' ? 'bg-red-50 text-red-800 border border-red-200' :
              'bg-yellow-50 text-yellow-800 border border-yellow-200'
            }`}>
              {keyStatus.message}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ProviderSettings({ providers, onChange, onClose }) {
  const modalRef = useRef(null);
  const [activeProvider, setActiveProvider] = useState(() => {
    for (const [name, config] of Object.entries(providers)) {
      if (config.enabled) return name;
    }
    return 'openai';
  });

  const [localProviders, setLocalProviders] = useState(() => {
    try {
      const draft = localStorage.getItem(DRAFT_KEY);
      const parsed = draft ? { ...providers, ...JSON.parse(draft) } : providers;
      const normalized = { ...parsed };
      for (const { name } of PROVIDER_ORDER) {
        normalized[name] = {
          enabled: Boolean(normalized[name]?.enabled),
          model: String(normalized[name]?.model ?? ''),
          api_key: normalized[name]?.api_key ?? '',
          endpoint: String(normalized[name]?.endpoint ?? ''),
        };
      }
      const enabled = PROVIDER_ORDER.filter((p) => normalized[p.name]?.enabled).map((p) => p.name);
      if (enabled.length !== 1) {
        for (const { name } of PROVIDER_ORDER) normalized[name].enabled = false;
        normalized.openai.enabled = true;
      }
      return normalized;
    } catch {
      return providers;
    }
  });

  const [testingKey, setTestingKey] = useState(false);
  const [keyStatus, setKeyStatus] = useState(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (modalRef.current && !modalRef.current.contains(event.target)) {
        onClose();
      }
    };
    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  const handleProviderChange = useCallback((providerName) => {
    const updated = { ...localProviders };
    for (const { name } of PROVIDER_ORDER) {
      updated[name] = {
        ...localProviders[name],
        enabled: name === providerName,
      };
    }
    setLocalProviders(updated);
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(stripApiKeys(updated)));
    } catch {
      // ignore
    }
    setActiveProvider(providerName);
    setKeyStatus(null);
  }, [localProviders]);

  const updateProviderField = useCallback((providerName, field, value) => {
    setLocalProviders((prev) => {
      const updated = {
        ...prev,
        [providerName]: {
          ...prev[providerName],
          [field]: value,
        },
      };
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(stripApiKeys(updated)));
      } catch {
        // ignore
      }
      return updated;
    });
    setKeyStatus(null);
  }, []);

  const handleSave = useCallback(() => {
    onChange(localProviders);
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // ignore
    }
    onClose();
  }, [localProviders, onChange, onClose]);

  const handleCancel = useCallback(() => {
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // ignore
    }
    onClose();
  }, [onClose]);

  const testApiKey = async () => {
    if (testingKey) return;

    const config = localProviders[activeProvider];
    const missing = [];
    if (!String(config.model || '').trim()) missing.push('model name');
    if (!String(config.api_key || '').trim()) missing.push('API key');
    if (activeProvider === 'azure_openai' && !String(config.endpoint || '').trim()) {
      missing.push('endpoint URL');
    }
    if (missing.length > 0) {
      setKeyStatus({ type: 'error', message: `Please fill: ${missing.join(', ')}.` });
      return;
    }

    setTestingKey(true);
    setKeyStatus(null);

    try {
      const API_BASE = import.meta.env.VITE_API_URL || '/api';
      const res = await fetch(`${API_BASE}/analyze-idea`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idea: 'Test business idea',
          ai_providers: {
            ...Object.fromEntries(
              Object.entries(localProviders).map(([name, cfg]) => [
                name,
                name === activeProvider ? cfg : { ...cfg, enabled: false },
              ])
            ),
          },
        }),
      });

      const data = await res.json();

      if (res.ok && data.provider_used === activeProvider) {
        setKeyStatus({ type: 'success', message: 'API key is valid.' });
      } else {
        const detail = data.detail || `HTTP ${res.status}`;
        setKeyStatus({ type: 'error', message: `Provider test failed: ${detail}` });
      }
    } catch (error) {
      setKeyStatus({ type: 'error', message: `Failed to test API key: ${error.message}` });
    } finally {
      setTestingKey(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div
        ref={modalRef}
        className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-white border-b border-stone-200 px-6 py-4 flex items-center justify-between z-10">
          <h2 className="text-xl font-bold text-stone-800">Provider Settings</h2>
          <button
            onClick={handleCancel}
            className="text-stone-400 hover:text-stone-600 text-2xl leading-none transition-colors"
            aria-label="Close"
          >
            x
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-sm text-stone-600">
            Choose one provider for this session.
          </p>
          <p className="text-xs text-stone-500">
            Save applies changes. Cancel closes without saving.
          </p>

          <div className="space-y-3">
            {PROVIDER_ORDER.map((p) => (
              <ProviderOption
                key={p.name}
                name={p.name}
                label={p.label}
                isSelected={activeProvider === p.name}
                config={localProviders[p.name]}
                onSelect={() => handleProviderChange(p.name)}
                onUpdateField={updateProviderField}
                onTestApiKey={testApiKey}
                testingKey={testingKey}
                keyStatus={activeProvider === p.name ? keyStatus : null}
              />
            ))}
          </div>

          <div className="pt-4 border-t border-stone-200 flex gap-3">
            <button
              onClick={handleSave}
              className="flex-1 py-2.5 px-4 rounded-lg bg-amber-500 hover:bg-amber-600 text-white font-medium transition-colors"
            >
              Save Settings
            </button>
            <button
              onClick={handleCancel}
              className="px-4 py-2.5 rounded-lg border border-stone-300 hover:bg-stone-50 text-stone-700 font-medium transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
