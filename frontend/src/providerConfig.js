export const PROVIDER_NAMES = Object.freeze([
  'openai',
  'azure_openai',
  'gemini',
  'claude',
]);

const DEFAULT_PROVIDERS = Object.freeze({
  openai: { enabled: true, model: '', api_key: '', endpoint: '' },
  azure_openai: { enabled: false, model: '', api_key: '', endpoint: '' },
  gemini: { enabled: false, model: '', api_key: '', endpoint: '' },
  claude: { enabled: false, model: '', api_key: '', endpoint: '' },
});

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function emptyProvider() {
  return { enabled: false, model: '', api_key: '', endpoint: '' };
}

function stringValue(value) {
  return typeof value === 'string' ? value.trim() : '';
}

export function createDefaultProviders() {
  return Object.fromEntries(
    PROVIDER_NAMES.map((name) => [name, { ...DEFAULT_PROVIDERS[name] }]),
  );
}

export function normalizeProviders(saved, { preserveApiKeys = false } = {}) {
  const source = isRecord(saved) ? saved : {};
  const normalized = Object.fromEntries(
    PROVIDER_NAMES.map((name) => {
      const config = isRecord(source[name]) ? source[name] : {};
      return [name, {
        enabled: config.enabled === true,
        model: stringValue(config.model),
        api_key: preserveApiKeys && typeof config.api_key === 'string'
          ? config.api_key
          : '',
        endpoint: stringValue(config.endpoint),
      }];
    }),
  );

  const enabledNames = PROVIDER_NAMES.filter((name) => normalized[name].enabled);
  if (enabledNames.length !== 1) {
    PROVIDER_NAMES.forEach((name) => {
      normalized[name].enabled = false;
    });
    normalized.openai.enabled = true;
  }
  return normalized;
}

export function loadPersistedProviders(storage) {
  try {
    const store = storage ?? globalThis.localStorage;
    const saved = store.getItem('ai_providers');
    return normalizeProviders(saved ? JSON.parse(saved) : null);
  } catch {
    return createDefaultProviders();
  }
}

export function stripApiKeys(config) {
  const normalized = normalizeProviders(config);
  return Object.fromEntries(
    PROVIDER_NAMES.map((name) => [name, {
      ...normalized[name],
      api_key: '',
    }]),
  );
}

export function mergeDraftProviders(providers, draft) {
  const normalized = normalizeProviders(providers, { preserveApiKeys: true });
  if (!isRecord(draft)) {
    return normalized;
  }

  PROVIDER_NAMES.forEach((name) => {
    const draftConfig = isRecord(draft[name]) ? draft[name] : null;
    if (!draftConfig) return;
    normalized[name].enabled = draftConfig.enabled === true;
    normalized[name].model = stringValue(draftConfig.model);
    normalized[name].endpoint = stringValue(draftConfig.endpoint);
  });
  return normalizeProviders(normalized, { preserveApiKeys: true });
}

export function activeProviderName(providers) {
  return PROVIDER_NAMES.find((name) => providers?.[name]?.enabled) || null;
}

export function activeProviderConfig(providers) {
  const activeName = activeProviderName(providers);
  return Object.fromEntries(
    PROVIDER_NAMES.map((name) => {
      if (name !== activeName) {
        return [name, emptyProvider()];
      }
      const config = isRecord(providers?.[name]) ? providers[name] : {};
      return [name, {
        enabled: true,
        model: stringValue(config.model),
        api_key: typeof config.api_key === 'string' ? config.api_key : '',
        endpoint: stringValue(config.endpoint),
      }];
    }),
  );
}
