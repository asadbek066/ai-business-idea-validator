import { useState, useEffect, useRef, useCallback } from 'react';

// Helper functions for localStorage history
const getHistoryKey = (provider, field) => `ai_provider_history_${provider}_${field}`;
const MAX_HISTORY = 10;
const DRAFT_KEY = 'ai_providers_draft';
const PROVIDER_ORDER = [
  { name: 'ollama', label: 'Ollama (Local - Recommended)' },
  { name: 'openai', label: 'OpenAI' },
  { name: 'azure_openai', label: 'Azure OpenAI' },
  { name: 'gemini', label: 'Google Gemini' },
  { name: 'claude', label: 'Anthropic Claude' },
];

const getHistory = (provider, field) => {
  try {
    const stored = localStorage.getItem(getHistoryKey(provider, field));
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
};

const saveToHistory = (provider, field, value) => {
  if (!value || value.trim() === '') return;
  try {
    const history = getHistory(provider, field);
    const filtered = history.filter(v => v !== value);
    const updated = [value, ...filtered].slice(0, MAX_HISTORY);
    localStorage.setItem(getHistoryKey(provider, field), JSON.stringify(updated));
  } catch {
    // Ignore localStorage errors
  }
};

export default function ProviderSettings({ providers, onChange, onClose }) {
  const modalRef = useRef(null);
  const [activeProvider, setActiveProvider] = useState(() => {
    for (const [name, config] of Object.entries(providers)) {
      if (config.enabled) return name;
    }
    return 'ollama';
  });
  
  // Separate state for provider configs - don't tie to input values
  // Also keep a draft in localStorage so closing the modal doesn't feel like it "ate" edits.
  const [localProviders, setLocalProviders] = useState(() => {
    try {
      const draft = localStorage.getItem(DRAFT_KEY);
      const parsed = draft ? JSON.parse(draft) : providers;
      // Normalize shape so every field stays editable (no undefined/null surprises)
      const normalized = { ...parsed };
      for (const { name } of PROVIDER_ORDER) {
        normalized[name] = {
          enabled: Boolean(normalized[name]?.enabled),
          model: String(normalized[name]?.model ?? ''),
          api_key: normalized[name]?.api_key ?? '',
          endpoint: String(normalized[name]?.endpoint ?? ''),
          url: String(normalized[name]?.url ?? 'http://localhost:11434'),
        };
      }
      // Ensure exactly one enabled provider (default to ollama)
      const enabled = PROVIDER_ORDER.filter(p => normalized[p.name]?.enabled).map(p => p.name);
      if (enabled.length !== 1) {
        for (const { name } of PROVIDER_ORDER) normalized[name].enabled = false;
        normalized.ollama.enabled = true;
      }
      return normalized;
    } catch {
      return providers;
    }
  });
  const [testingKey, setTestingKey] = useState(false);
  const [keyStatus, setKeyStatus] = useState(null);
  
  // Autocomplete state
  const [autocompleteState, setAutocompleteState] = useState({
    field: null,
    query: '',
    suggestions: [],
    selectedIndex: -1,
  });

  // Click outside to close
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
      localStorage.setItem(DRAFT_KEY, JSON.stringify(updated));
    } catch {
      // ignore
    }
    setActiveProvider(providerName);
    setKeyStatus(null);
    setAutocompleteState({ field: null, query: '', suggestions: [], selectedIndex: -1 });
  }, [localProviders]);

  const updateProviderField = useCallback((providerName, field, value) => {
    setLocalProviders(prev => {
      const updated = {
        ...prev,
        [providerName]: {
          ...prev[providerName],
          [field]: value,
        },
      };
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify(updated));
      } catch {
        // ignore
      }
      return updated;
    });
    setKeyStatus(null);
    
    // Update autocomplete suggestions
    if (field === 'model' || field === 'endpoint' || field === 'url') {
      const history = getHistory(providerName, field);
      const filtered = history.filter(h => h.toLowerCase().includes(value.toLowerCase()));
      setAutocompleteState(prev => ({
        ...prev,
        field: `${providerName}_${field}`,
        query: value,
        suggestions: filtered.slice(0, 5),
        selectedIndex: -1,
      }));
    }
  }, []);

  const handleSave = useCallback(() => {
    // Save current values to history
    const config = localProviders[activeProvider];
    if (config.model) saveToHistory(activeProvider, 'model', config.model);
    if (config.endpoint) saveToHistory(activeProvider, 'endpoint', config.endpoint);
    if (config.url) saveToHistory(activeProvider, 'url', config.url);
    
    onChange(localProviders);
    try {
      localStorage.removeItem(DRAFT_KEY);
    } catch {
      // ignore
    }
    onClose();
  }, [localProviders, activeProvider, onChange, onClose]);

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
    if (activeProvider !== 'ollama') {
      const missing = [];
      if (!String(config.model || '').trim()) missing.push('model name');
      if (!String(config.api_key || '').trim()) missing.push('API key');
      if (activeProvider === 'azure_openai' && !String(config.endpoint || '').trim()) {
        missing.push('endpoint URL');
      }
      if (missing.length > 0) {
        setKeyStatus({
          type: 'error',
          message: `Please fill: ${missing.join(', ')}.`,
        });
        return;
      }
    }

    setTestingKey(true);
    setKeyStatus(null);

    try {
      const API_BASE = import.meta.env.VITE_API_URL || '/api';
      const testIdea = 'Test business idea';
      const res = await fetch(`${API_BASE}/analyze-idea`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          idea: testIdea,
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

      if (res.ok) {
        // Provider used and no fallback message -> key looks good
        if (data.provider_used === activeProvider && !data.fallback_message) {
          setKeyStatus({ type: 'success', message: 'API key is valid.' });
        } else if (data.fallback_message) {
          // Backend explicitly reports fallback (e.g. invalid or missing key)
          setKeyStatus({
            type: 'warning',
            message: data.fallback_message,
          });
        } else {
          setKeyStatus({
            type: 'warning',
            message: 'Provider did not respond as expected. Ollama may be used as fallback.',
          });
        }
      } else {
        const detail = data.detail || data.fallback_message || `HTTP ${res.status}`;
        setKeyStatus({
          type: 'error',
          message: `Provider test failed: ${detail}`,
        });
      }
    } catch (error) {
      setKeyStatus({
        type: 'error',
        message: `Failed to test API key: ${error.message}`,
      });
    } finally {
      setTestingKey(false);
    }
  };

  const handleInputFocus = (providerName, field) => {
    const history = getHistory(providerName, field);
    const currentValue = localProviders[providerName][field] || '';
    const filtered = history.filter(h => 
      h.toLowerCase().includes(currentValue.toLowerCase()) && h !== currentValue
    );
    setAutocompleteState({
      field: `${providerName}_${field}`,
      query: currentValue,
      suggestions: filtered.slice(0, 5),
      selectedIndex: -1,
    });
  };

  const handleInputBlur = () => {
    // Delay closing autocomplete to allow click on suggestion
    setTimeout(() => {
      setAutocompleteState({ field: null, query: '', suggestions: [], selectedIndex: -1 });
    }, 200);
  };

  const selectSuggestion = (providerName, field, value) => {
    updateProviderField(providerName, field, value);
    setAutocompleteState({ field: null, query: '', suggestions: [], selectedIndex: -1 });
  };

  const handleInputKeyDown = (e, providerName, field) => {
    const { suggestions, selectedIndex } = autocompleteState;
    if (autocompleteState.field !== `${providerName}_${field}`) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setAutocompleteState(prev => ({
        ...prev,
        selectedIndex: Math.min(prev.selectedIndex + 1, suggestions.length - 1),
      }));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setAutocompleteState(prev => ({
        ...prev,
        selectedIndex: Math.max(prev.selectedIndex - 1, -1),
      }));
    } else if (e.key === 'Enter' && selectedIndex >= 0 && suggestions[selectedIndex]) {
      e.preventDefault();
      selectSuggestion(providerName, field, suggestions[selectedIndex]);
    } else if (e.key === 'Escape') {
      setAutocompleteState({ field: null, query: '', suggestions: [], selectedIndex: -1 });
    }
  };

  const AutocompleteInput = ({ providerName, field, value, onChange, placeholder, type = 'text', required = false }) => {
    const inputRef = useRef(null);
    const dropdownRef = useRef(null);
    const isActive = autocompleteState.field === `${providerName}_${field}`;
    const suggestions = isActive ? autocompleteState.suggestions : [];

    return (
      <div className="relative">
        <input
          ref={inputRef}
          type={type}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => handleInputFocus(providerName, field)}
          onBlur={handleInputBlur}
          onKeyDown={(e) => handleInputKeyDown(e, providerName, field)}
          placeholder={placeholder}
          className="w-full px-3 py-2 text-sm rounded-lg border border-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
          required={required}
        />
        {suggestions.length > 0 && (
          <div
            ref={dropdownRef}
            className="absolute z-10 w-full mt-1 bg-white border border-stone-200 rounded-lg shadow-lg max-h-40 overflow-y-auto"
            onMouseDown={(e) => e.preventDefault()} // Prevent blur
          >
            {suggestions.map((suggestion, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => selectSuggestion(providerName, field, suggestion)}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-amber-50 transition-colors ${
                  idx === autocompleteState.selectedIndex ? 'bg-amber-50' : ''
                }`}
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  };

  const ProviderOption = ({ name, label }) => {
    const isSelected = activeProvider === name;
    const config = localProviders[name];
    const selectProvider = () => handleProviderChange(name);

    return (
      <div className="space-y-3" key={name}>
        <div
          role="button"
          tabIndex={0}
          onClick={selectProvider}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              selectProvider();
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
            onChange={selectProvider}
            onClick={(e) => e.stopPropagation()}
            className="w-4 h-4 text-amber-500 focus:ring-amber-500"
            aria-label={`${label} provider`}
          />
          <span className="font-medium text-stone-800 flex-1">{label}</span>
          <span className="text-xs text-stone-500">
            {isSelected ? 'Selected' : 'Select'}
          </span>
        </div>

        {isSelected && (
          <div className="ml-7 space-y-3 p-4 bg-stone-50 rounded-lg border border-stone-200">
            <div>
              <label className="block text-sm font-medium text-stone-700 mb-1">
                Model Name <span className="text-red-500">*</span>
              </label>
              <AutocompleteInput
                providerName={name}
                field="model"
                value={config?.model ?? ''}
                onChange={(value) => updateProviderField(name, 'model', value)}
                placeholder={
                  name === 'ollama' ? 'qwen2.5:1.5b' :
                  name === 'openai' ? 'gpt-4o-mini' :
                  name === 'claude' ? 'claude-3-haiku-20240307' :
                  name === 'gemini' ? 'gemini-pro' :
                  'your-model-name'
                }
                required
              />
            </div>

            {name !== 'ollama' && (
              <div>
                <label className="block text-sm font-medium text-stone-700 mb-1">
                  API Key <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  value={config?.api_key ?? ''}
                  onChange={(e) => updateProviderField(name, 'api_key', e.target.value)}
                  placeholder="Enter your API key"
                  className="w-full px-3 py-2 text-sm rounded-lg border border-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
                  required
                />
                <button
                  type="button"
                  onClick={testApiKey}
                  className="mt-2 px-3 py-1.5 text-xs rounded-lg border border-stone-300 hover:bg-stone-100 text-stone-700"
                >
                  {testingKey ? 'Testing...' : 'Test API Key'}
                </button>
              </div>
            )}

            {name === 'azure_openai' && (
              <div>
                <label className="block text-sm font-medium text-stone-700 mb-1">
                  Endpoint URL <span className="text-red-500">*</span>
                </label>
                <AutocompleteInput
                  providerName={name}
                  field="endpoint"
                  value={config?.endpoint ?? ''}
                  onChange={(value) => updateProviderField(name, 'endpoint', value)}
                  placeholder="https://your-resource.openai.azure.com"
                  required
                />
              </div>
            )}

            {name === 'ollama' && (
              <div>
                <label className="block text-sm font-medium text-stone-700 mb-1">
                  Ollama URL
                </label>
                <AutocompleteInput
                  providerName={name}
                  field="url"
                  value={config?.url ?? 'http://localhost:11434'}
                  onChange={(value) => updateProviderField(name, 'url', value)}
                  placeholder="http://localhost:11434"
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
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div
        ref={modalRef}
        className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-white border-b border-stone-200 px-6 py-4 flex items-center justify-between z-10">
          <h2 className="text-xl font-bold text-stone-800">AI Provider Settings</h2>
          <button
            onClick={handleCancel}
            className="text-stone-400 hover:text-stone-600 text-2xl leading-none transition-colors"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p className="text-sm text-stone-600">
            Select <strong>one AI provider</strong> for analysis. If the selected provider fails, Ollama will be used as fallback.
          </p>
          <p className="text-xs text-stone-500">
            Tip: click <strong>Save Settings</strong> to apply changes. Closing cancels.
          </p>

          <div className="space-y-3">
            {PROVIDER_ORDER.map((p) => (
              <ProviderOption key={p.name} name={p.name} label={p.label} />
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
