/* Cookies carry authentication. CSRF tokens are held only in page memory. */
(() => {
  const rawFetch = window.fetch.bind(window);
  let identity;
  const ready = rawFetch('/auth/me', {cache: 'no-store'}).then(async response => {
    if (response.status === 401) {
      location.replace('/console/login.html');
      throw new Error('Login required');
    }
    identity = await response.json();
    if (identity.protected) {
      const bar = document.createElement('div');
      bar.setAttribute('role', 'status');
      bar.textContent = `${identity.username} · ${identity.role} `;
      const button = document.createElement('button');
      button.textContent = '로그아웃';
      button.type = 'button';
      button.onclick = async () => {
        const response = await window.fetch('/auth/logout', {method: 'POST'});
        if (response.ok) {
          sessionStorage.removeItem('harbinger:review:synthetic-example');
          location.replace('/console/login.html');
        }
      };
      bar.append(button);
      document.body.prepend(bar);
    }
  });
  // Every caller, including direct downloads and session cleanup, shares this guard.
  window.fetch = async (input, options = {}) => {
    await ready;
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    const headers = new Headers(options.headers || (input instanceof Request ? input.headers : {}));
    const method = (options.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.origin === location.origin && identity.protected && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      headers.set('X-CSRF-Token', identity.csrf_token);
    }
    const response = await rawFetch(input, {...options, headers});
    if (url.origin === location.origin && response.status === 401) location.replace('/console/login.html');
    return response;
  };
})();
