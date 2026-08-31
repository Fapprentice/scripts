/** Transport and local-session boundary for Task Verge. */
(function (global) {
  let sessionToken = null;
  let sessionClaimPromise = null;
  const notify = (...args) => global.showModal?.(...args);

  async function claimBackendSession() {
    try {
      const desktopToken = new URLSearchParams(location.search).get('desktop_token');
      const headers = desktopToken ? {'X-TaskVerge-Desktop': desktopToken} : {};
      const response = await fetch('/api/claim', {headers});
      const payload = await response.json();
      if (payload.ok) { sessionToken = payload.token; return true; }
    } catch (_) {}
    return false;
  }

  async function ensureSession() {
    if (sessionToken) return true;
    if (!sessionClaimPromise) sessionClaimPromise = (async () => {
      for (let i = 0; i < 9; i++) {
        if (await claimBackendSession()) return true;
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      return false;
    })();
    try { return await sessionClaimPromise; }
    finally { sessionClaimPromise = null; }
  }

  async function request(path, options, retryConflict) {
    if (!sessionToken && !await ensureSession()) throw new Error('无法建立本地会话');
    const requestOptions = options || {};
    requestOptions.headers ||= {};
    if (sessionToken) requestOptions.headers['X-Session'] = sessionToken;
    let response;
    try { response = await fetch('/api/' + path, requestOptions); }
    catch (error) { notify('网络错误', '无法连接到服务器：' + error.message + '。请检查服务是否在运行。'); throw error; }
    if ((response.status === 401 || (retryConflict && response.status === 409)) && sessionToken) {
      sessionToken = null;
      if (await ensureSession()) {
        requestOptions.headers['X-Session'] = sessionToken;
        response = await fetch('/api/' + path, requestOptions);
      }
    }
    if (response.status === 409) {
      let message = '另一个窗口正在操作，请勿并发写入。';
      try { const payload = await response.json(); message = payload.message || message; } catch (_) {}
      notify('会话冲突', message, 'warn');
      throw new Error(message);
    }
    if (!response.ok) {
      let message = await response.text();
      try { const payload = JSON.parse(message); message = payload.message || message; } catch (_) {}
      if (/^\s*</.test(message)) message = '服务器返回错误 (' + response.status + ')。若是「结束休息」等新功能，请退出并重新打开应用以加载最新后端。';
      if (typeof api.onError === 'function' && api.onError(message)) throw new Error(message);
      notify('操作失败', message);
      throw new Error(message);
    }
    return response.json();
  }

  function api(path, body) {
    const options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
    return request(path, options, false);
  }
  function uploadApi(path, formData) { return request(path, {method: 'POST', headers: {}, body: formData}, true); }
  function logEvent(kind, message, extra = {}) {
    const headers = {'Content-Type': 'application/json'};
    if (sessionToken) headers['X-Session'] = sessionToken;
    fetch('/api/event', {method: 'POST', headers, body: JSON.stringify({kind, message, extra})}).catch(() => {});
  }
  async function heartbeat() {
    if (!sessionToken) return;
    try { await fetch('/api/heartbeat', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Session': sessionToken}, body: '{}'}); } catch (_) {}
  }
  api.onError = null;
  global.TaskVergeApi = {api, uploadApi, logEvent, ensureSession, heartbeat,
    sessionToken: () => sessionToken};
})(window);
