import {
  activeProviderConfig,
  createDefaultProviders,
  loadPersistedProviders,
  mergeDraftProviders,
  normalizeProviders,
  stripApiKeys,
} from './providerConfig';
import { describe, expect, it, vi } from 'vitest';

describe('provider configuration boundaries', () => {
  it('falls back when browser storage is corrupt or unavailable', () => {
    const storage = { getItem: vi.fn(() => '{not-json') };
    expect(loadPersistedProviders(storage)).toEqual(createDefaultProviders());

    expect(loadPersistedProviders({
      getItem: () => { throw new Error('storage unavailable'); },
    })).toEqual(createDefaultProviders());
  });

  it('never loads API keys from persisted settings', () => {
    const saved = {
      openai: { enabled: true, model: 'gpt-4o-mini', api_key: 'old-secret' },
      gemini: { enabled: true, model: 'gemini-2.5-flash', api_key: 'other-secret' },
    };

    const normalized = normalizeProviders(saved);
    expect(normalized.openai.api_key).toBe('');
    expect(normalized.gemini.api_key).toBe('');
    expect(Object.values(normalized).filter((config) => config.enabled)).toHaveLength(1);
  });

  it('strips keys and unknown provider state before persistence', () => {
    const config = {
      openai: {
        enabled: true,
        model: 'gpt-4o-mini',
        api_key: 'secret',
        endpoint: '',
        unexpected: 'discarded',
      },
      claude: { enabled: false, model: 'claude', api_key: 'other-secret' },
    };

    expect(stripApiKeys(config)).toEqual({
      openai: { enabled: true, model: 'gpt-4o-mini', api_key: '', endpoint: '' },
      azure_openai: { enabled: false, model: '', api_key: '', endpoint: '' },
      gemini: { enabled: false, model: '', api_key: '', endpoint: '' },
      claude: { enabled: false, model: 'claude', api_key: '', endpoint: '' },
    });
  });

  it('merges a draft without allowing draft storage to replace an in-memory key', () => {
    const providers = normalizeProviders({
      openai: { enabled: true, model: 'gpt-4o-mini', api_key: 'live-secret' },
    }, { preserveApiKeys: true });
    const merged = mergeDraftProviders(providers, {
      openai: { enabled: true, model: 'gpt-4.1', api_key: 'persisted-attack' },
    });

    expect(merged.openai.model).toBe('gpt-4.1');
    expect(merged.openai.api_key).toBe('live-secret');
  });

  it('posts only the selected provider secret', () => {
    const payload = activeProviderConfig({
      openai: { enabled: false, model: 'gpt', api_key: 'openai-secret' },
      azure_openai: { enabled: true, model: 'deployment', api_key: 'azure-secret', endpoint: 'https://resource.openai.azure.com' },
      gemini: { enabled: false, model: 'gemini', api_key: 'gemini-secret' },
      claude: { enabled: false, model: 'claude', api_key: 'claude-secret' },
    });

    expect(payload.azure_openai.api_key).toBe('azure-secret');
    expect(payload.openai.api_key).toBe('');
    expect(payload.gemini.api_key).toBe('');
    expect(payload.claude.api_key).toBe('');
    expect(payload.openai.model).toBe('');
  });
});
