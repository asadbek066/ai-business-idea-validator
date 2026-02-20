/**
 * Backend API client.
 * In dev with Vite proxy: use relative /api so requests go to localhost:8000.
 * In production: set VITE_API_URL to your Render backend URL.
 */
const API_BASE = import.meta.env.VITE_API_URL || '/api';

export async function analyzeIdea(idea, providersConfig = null) {
  const body = { idea: idea.trim() };
  if (providersConfig) {
    body.ai_providers = providersConfig;
  }
  
  const res = await fetch(`${API_BASE}/analyze-idea`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message = data.detail || (Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : res.statusText);
    throw new Error(message || `Request failed (${res.status})`);
  }
  return data;
}
