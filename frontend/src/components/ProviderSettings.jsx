import { useState, useEffect, useRef, useCallback } from 'react';
import { validateProvider } from '../api';

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
      <label
        htmlFor={`provider-${name}`}
        className="w-full flex items-center gap-3 cursor-pointer p-3 rounded-lg border-2 transition-colors hover:bg-stone-50 text-left"
        style={{ borderColor: isSelected ? '#f59e0b' : '#e5e7eb' }}
      >
        <input
          id={`provider-${name}`}
          type="radio"
          name="ai_provider"
          value={name}
          checked={isSelected}
          onChange={onSelect}
          className="w-4 h-4 text-amber-500 focus:ring-amber-500"
          aria-label={`${label} provider`}
        />
        <span className="font-medium text-stone-800 flex-1">{label}</span>
        <span className="text-xs text-stone-500">{isSelected ? 'Selected' : 'Select'}</span>
      </label>

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
              maxLength={128}
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
              autoComplete="new-password"
              maxLength={512}
              className="w-full px-3 py-2 text-sm rounded-lg border border-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500 bg-white"
              required
            />
            <button
              type="button"
              onClick={onTestApiKey}
              disabled={testingKey}
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
                maxLength={512}
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
            }`} role="status" aria-live="polite">
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
  const closeButtonRef = useRef(null);
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
    const previousActiveElement = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      if (previousActiveElement instanceof HTMLElement) {
        previousActiveElement.focus();
      }
    };
  }, []);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (modalRef.current && !modalRef.current.contains(event.target)) {
        onClose();
      }
    };
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab') {
        return;
      }
      const focusable = modalRef.current?.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable?.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
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
      const data = await validateProvider(localProviders);

      if (data.ok && data.provider_used === activeProvider) {
        setKeyStatus({ type: 'success', message: 'API key is valid.' });
      } else {
        setKeyStatus({ type: 'error', message: 'Provider test failed.' });
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
        role="dialog"
        aria-modal="true"
        aria-labelledby="provider-settings-title"
        aria-describedby="provider-settings-description"
        className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-white border-b border-stone-200 px-6 py-4 flex items-center justify-between z-10">
          <h2 id="provider-settings-title" className="text-xl font-bold text-stone-800">Provider Settings</h2>
          <button
            ref={closeButtonRef}
            onClick={handleCancel}
            className="text-stone-400 hover:text-stone-600 text-2xl leading-none transition-colors"
            aria-label="Close"
          >
            x
          </button>
        </div>

        <div className="p-6 space-y-4">
          <p id="provider-settings-description" className="text-sm text-stone-600">
            Choose one provider for this session.
          </p>
          <p className="text-xs text-stone-500">
            Save applies changes. Cancel closes without saving.
          </p>

          <fieldset className="space-y-3">
            <legend className="sr-only">AI provider</legend>
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
          </fieldset>

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
