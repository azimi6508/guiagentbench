// Read-only API client. All evidence comes from the local viewer server.

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const cache = new Map();

export async function get(path, params = {}, opts = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null)).toString();
  const url = query ? `${path}?${query}` : path;
  if (opts.cache && cache.has(url)) return cache.get(url);
  const response = await fetch(url, { headers: { Accept: 'application/json' } });
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) throw new ApiError(response.status, data.error || `Request failed (${response.status})`);
  if (opts.cache) cache.set(url, data);
  return data;
}

export async function text(evaluation, path) {
  const response = await fetch(artifactUrl(evaluation, path));
  if (!response.ok) throw new ApiError(response.status, 'Evidence not available');
  return response.text();
}

export function artifactUrl(evaluation, path) {
  return `/api/artifact?${new URLSearchParams({ id: evaluation, path })}`;
}

export function imageUrl(evaluation, image) {
  if (!image) return null;
  if (image.artifact) return artifactUrl(evaluation, image.artifact);
  if (image.embedded) {
    return `/api/image?${new URLSearchParams({ id: evaluation, path: image.embedded.path, line: image.embedded.line, sha: image.sha256 })}`;
  }
  return null;
}

export const api = {
  hierarchy: () => get('/api/hierarchy'),
  overview: (run) => get('/api/overview', { run }),
  evaluation: (id) => get('/api/evaluation', { id }),
  trajectory: (id, trial) => get('/api/trajectory', { id, trial }),
  record: (id, path, line) => get('/api/record', { id, path, line }),
  events: (id, path, offset, limit = 60) => get('/api/events', { id, path, offset, limit }),
};
