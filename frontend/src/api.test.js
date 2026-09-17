import { analyzeIdea, responseError, validateProvider } from './api';
import { afterEach, describe, expect, it, vi } from 'vitest';

function providers() {
  return {
    openai: { enabled: true, model: 'gpt-4o-mini', api_key: 'secret-key' },
    azure_openai: { enabled: false, model: '', api_key: '', endpoint: '' },
    gemini: { enabled: false, model: '', api_key: '' },
    claude: { enabled: false, model: '', api_key: '' },
  };
}

function response(body, options = {}) {
  return {
    ok: options.ok ?? true,
    status: options.status ?? 200,
    statusText: options.statusText ?? 'OK',
    json: vi.fn().mockResolvedValue(body),
  };
}

describe('API client', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('sends normalized ideas and only the active provider configuration', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ verdict: 'good' }));
    vi.stubGlobal('fetch', fetchMock);

    await analyzeIdea('  A useful product  ', providers());

    const [url, options] = fetchMock.mock.calls[0];
    const body = JSON.parse(options.body);
    expect(url).toBe('/api/analyze-idea');
    expect(body.idea).toBe('A useful product');
    expect(body.ai_providers.openai.api_key).toBe('secret-key');
    expect(body.ai_providers.gemini.api_key).toBe('');
    expect(options.signal).toBeInstanceOf(AbortSignal);
  });

  it('formats FastAPI validation arrays with locations', () => {
    const message = responseError({
      detail: [
        { loc: ['body', 'idea'], msg: 'String should have at least 1 character' },
        { loc: ['body', 'ai_providers'], msg: 'Invalid provider' },
      ],
    }, response({}, { ok: false, status: 422, statusText: 'Unprocessable Entity' }));

    expect(message).toBe(
      'body.idea: String should have at least 1 character, body.ai_providers: Invalid provider',
    );
  });

  it('surfaces public API errors instead of object coercion', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      detail: [{ loc: ['body', 'ai_providers'], msg: 'Invalid provider' }],
    }, { ok: false, status: 422, statusText: 'Unprocessable Entity' })));

    await expect(analyzeIdea('idea', providers())).rejects.toThrow(
      'body.ai_providers: Invalid provider',
    );
  });

  it('rejects blank submissions before making a request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(analyzeIdea('  ', providers())).rejects.toThrow(
      'Enter a business idea first.',
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('uses a bounded validation request and active provider payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      ok: true,
      provider_used: 'openai',
    }));
    vi.stubGlobal('fetch', fetchMock);

    await validateProvider(providers());

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/validate-provider');
    expect(JSON.parse(options.body).ai_providers.openai.api_key).toBe('secret-key');
  });

  it('reports timeout separately from user cancellation', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_, reject) => {
      options.signal.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      });
    })));

    const timedOut = expect(analyzeIdea('idea', providers())).rejects.toThrow(
      'request timed out',
    );
    await vi.advanceTimersByTimeAsync(90_000);
    await timedOut;

    const controller = new AbortController();
    const cancelled = analyzeIdea('idea', providers(), { signal: controller.signal });
    controller.abort();
    await expect(cancelled).rejects.toMatchObject({ name: 'AbortError' });
  });
});
