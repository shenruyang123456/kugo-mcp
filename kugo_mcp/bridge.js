// Four explicit MCP controls and one combined snapshot. No background timers.
(() => {
  if (window.__kugoMcpBridge?.version === 3) return true;
  let pending = false;
  let nextAllowedAt = 0;
  const report = (id, value) => {
    try { window.__kugoMcpResult(JSON.stringify({id, ...value})); } catch (_) {}
  };
  window.__kugoMcpBridge = {
    version: 3,
    begin(id, action, expiresAt) {
      if (!['snapshot', 'play', 'pause', 'next', 'prev'].includes(action)) throw Error('Unsupported action');
      if (pending || Date.now() < nextAllowedAt) throw Error('Native bridge is busy');
      pending = true;
      // Return from Runtime.evaluate BEFORE entering KuGou's synchronous native bridge.
      // An expired queued command must never execute after the caller has timed out.
      setTimeout(() => {
        if (Date.now() >= expiresAt) {
          pending = false;
          report(id, {error: 'Request expired before execution'});
          return;
        }
        const name = '__kugoMcpSnapshot_' + id;
        let timer;
        const finish = (value) => {
          clearTimeout(timer);
          delete window[name];
          pending = false;
          nextAllowedAt = Date.now() + (value.error ? 30000 : action === 'snapshot' ? 0 : 500);
          report(id, value);
        };
        try {
          if (action !== 'snapshot') {
            external.SuperCall(841, JSON.stringify({status: action}));
            finish({result: {accepted: true}});
            return;
          }
          timer = setTimeout(() => finish({error: 'Native status callback timed out'}), 8000);
          window[name] = value => {
            try {
              const s = typeof value === 'string' ? JSON.parse(value) : value;
              let source = null;
              try { source = JSON.parse(s.QueueSource || '{}').WebInfo; } catch (_) {}
              finish({result: {
                available: String(s.status) === '1', title: s.filename || '', hash: s.hash || '',
                mixsongid: s.mix_song_id || '', playback: s.play_status || 'stopped',
                duration_ms: Number(s.duration || 0), progress: s.progress,
                source: source?.type || '', source_name: source?.info?.name || ''
              }});
            } catch (_) { finish({error: 'Invalid native snapshot'}); }
          };
          external.SuperCall(864, JSON.stringify({callback: name}));
        } catch (_) { finish({error: 'Native bridge call failed'}); }
      }, 0);
      return {accepted: true};
    }
  };
  return true;
})()
