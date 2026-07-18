let installed = false;

export const installAuthenticatedFetch = () => {
  if (installed) return;
  installed = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    let sameOrigin = true;
    try { sameOrigin = new URL(raw, window.location.origin).origin === window.location.origin; } catch { sameOrigin = true; }
    const token = localStorage.getItem('accessToken');
    if (!sameOrigin || !token) return original(input, init);
    const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
    if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
    return original(input, { ...init, headers });
  };
};
