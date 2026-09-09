/** Backend API client for the provider-backed analysis flow. */

const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/+$/, '');
const PROVIDER_NAMES = ['openai', 'azure_openai', 'gemini', 'claude'];

function activeProviderName(providersConfig) {
  return PROVIDER_NAMES.find((name) => providersConfig?.[name]?.enabled) || null;
}

/** Send only the selected provider configuration to the backend. */
export function activeProviderConfig(providersConfig) {
  const activeName = activeProviderName(providersConfig);
  return Object.fromEntries(PROVIDER_NAMES.map((name) => {
    const config = providersConfig?.[name] || {};
    if (name !== activeName) {
      return [name, { enabled: false, model: '', api_key: '', endpoint: '' }];
    }
    return [name, {
      enabled: true,
      model: String(config.model || ''),
      api_key: String(config.api_key || ''),
      endpoint: String(config.endpoint || ''),
    }];
  }));
}

function responseError(data, response) {
  if (Array.isArray(data?.detail)) {
    return data.detail.map((item) => item?.msg || 'Invalid request').join(', ');
  }
  return data?.detail || response.statusText || `Request failed (${response.status})`;
}

async function postJson(path, body, timeoutMs) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseError(data, response));
    }
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error('The request timed out. Check the backend and try again.');
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function analyzeIdea(idea, providersConfig) {
  const normalizedIdea = String(idea || '').trim();
  if (!normalizedIdea) {
    throw new Error('Enter a business idea first.');
  }
  if (!activeProviderName(providersConfig)) {
    throw new Error('Choose one AI provider in Settings first.');
  }
  return postJson(
    '/analyze-idea',
    { idea: normalizedIdea, ai_providers: activeProviderConfig(providersConfig) },
    90_000,
  );
}

export async function validateProvider(providersConfig) {
  if (!activeProviderName(providersConfig)) {
    throw new Error('Choose one AI provider in Settings first.');
  }
  return postJson(
    '/validate-provider',
    { ai_providers: activeProviderConfig(providersConfig) },
    8_000,
  );
}
