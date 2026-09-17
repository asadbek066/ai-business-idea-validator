import { activeProviderConfig, activeProviderName } from './providerConfig';

const API_BASE = (import.meta.env.VITE_API_URL || '/api').replace(/\/+$/, '');

export function responseError(data, response) {
  if (Array.isArray(data?.detail)) {
    return data.detail.map((item) => {
      if (typeof item === 'string') return item;
      const message = item?.msg || item?.message || 'Invalid request';
      const location = Array.isArray(item?.loc) ? item.loc.filter(Boolean).join('.') : '';
      return location ? `${location}: ${message}` : message;
    }).join(', ');
  }
  if (typeof data?.detail === 'string' && data.detail) return data.detail;
  return response.statusText || `Request failed (${response.status})`;
}

function cancelledError(cause) {
  const error = new Error('Request cancelled.', { cause });
  error.name = 'AbortError';
  return error;
}

async function postJson(path, body, { timeoutMs, signal }) {
  const controller = new AbortController();
  let externalAbortHandler;
  let timedOut = false;

  const timeoutHandler = () => {
    timedOut = true;
    controller.abort();
  };
  const timerId = setTimeout(timeoutHandler, timeoutMs);

  if (signal) {
    if (signal.aborted) controller.abort();
    externalAbortHandler = () => controller.abort();
    signal.addEventListener('abort', externalAbortHandler, { once: true });
  }

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
    if (timedOut) {
      throw new Error('The request timed out. Check the backend and try again.', {
        cause: error,
      });
    }
    if (signal?.aborted) {
      throw cancelledError(error);
    }
    if (error?.name === 'AbortError') {
      throw cancelledError(error);
    }
    throw error;
  } finally {
    clearTimeout(timerId);
    if (signal && externalAbortHandler) {
      signal.removeEventListener('abort', externalAbortHandler);
    }
  }
}

export async function analyzeIdea(idea, providersConfig, options = {}) {
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
    { timeoutMs: 90_000, signal: options.signal },
  );
}

export async function validateProvider(providersConfig, options = {}) {
  if (!activeProviderName(providersConfig)) {
    throw new Error('Choose one AI provider in Settings first.');
  }
  return postJson(
    '/validate-provider',
    { ai_providers: activeProviderConfig(providersConfig) },
    { timeoutMs: 15_000, signal: options.signal },
  );
}
