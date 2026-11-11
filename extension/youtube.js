(() => {
  if (window.__synchroYoutube) return {ok: false, error: 'Translation is already open over this player'};
  const player = document.querySelector('#movie_player');
  const video = player?.querySelector('video');
  if (!video || !Number.isFinite(video.duration)) return {ok: false, error: 'Wait for a recorded YouTube video to load'};
  if (player.classList.contains('ad-showing')) return {ok: false, error: 'Wait for the ad to finish, then start translation'};
  const original = {volume: video.volume, muted: video.muted, rate: video.playbackRate};
  const nativeCaptions = player.querySelector('.ytp-subtitles-button');
  original.captions = nativeCaptions?.getAttribute('aria-pressed') === 'true';
  const initialUrl = location.href, position = video.currentTime;
  let closed = false, revision = 1, cues = [], ready = position, duration = video.duration, finished = false;
  let preparing = true, wanted = false, buffering = false, internalPause = false, wasAd = false, error = '', failed = false;
  let frame, timer, seekTimer, lastReport = 0, lastTime = 0, lastClock = 0, lastMix = performance.now(), duckUntil = 0;
  let ttsVolume = .9, originalVolume = .55, zoom = 1, fit = 'contain', captions = false, cloudUsage;
  const context = new AudioContext(), gain = context.createGain();
  gain.gain.value = ttsVolume; gain.connect(context.destination);
  const sources = new Map();
  let heldCue = null;
  let decodeQueue = Promise.resolve();
  const host = document.createElement('div');
  host.id = 'synchro-overlay';
  Object.assign(host.style, {position: 'absolute', inset: '0', zIndex: '70', pointerEvents: 'none'});
  const root = host.attachShadow({mode: 'open'});
  const svg = path => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const icons = {
    play: svg('<path d="m9 5 11 7-11 7z"/>'),
    pause: svg('<path d="M8 5v14M16 5v14"/>'),
    captions: svg('<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 10H7v4h3m7-4h-3v4h3"/>'),
    settings: svg('<path d="m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h6l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3z"/><circle cx="12" cy="12" r="3"/>'),
    close: svg('<path d="m6 6 12 12M6 18 18 6"/>'),
  };
  root.innerHTML = `<style>
    *{box-sizing:border-box} :host{font:14px/1.4 'Segoe UI',sans-serif;color:#edf3ef}
    button,input,select{font:inherit}button,select{color:inherit;background:#202824;border:1px solid #55645b;border-radius:7px;padding:8px;cursor:pointer}
    button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid #b9ebca;outline-offset:2px}button:active{transform:scale(.97)}button[aria-pressed=true]{color:#b9ebca;border-color:#b9ebca}
    svg{width:26px;height:26px;display:block} .bar{position:absolute;right:14px;top:14px;display:flex;gap:8px;pointer-events:auto;background:#15211bf5;border:2px solid #b9ebca;border-radius:12px;padding:7px;box-shadow:0 4px 16px #05080780}
    .bar button{width:46px;height:46px;display:grid;place-items:center;border-color:#8ba596;background:#344b3e;color:#fff;padding:8px}.bar button:hover,.bar button[aria-expanded=true]{background:#486852;border-color:#d8f6e2}.bar button[aria-pressed=true]{background:#b9ebca;color:#152b1c;border-color:#d8f6e2}.bar strong{align-self:center;padding:0 10px;font-size:15px;font-weight:700;color:#d3f5de;letter-spacing:.2px}
    .panel{position:absolute;right:14px;top:88px;width:290px;max-height:calc(100% - 110px);overflow:auto;background:#151c19fa;border:1px solid #8ba596;border-radius:10px;padding:16px;pointer-events:auto;box-shadow:0 8px 24px #05080766}
    label{display:grid;gap:7px;margin:0 0 16px}input[type=range]{width:100%;accent-color:#b9ebca}.row{display:flex;gap:8px;flex-wrap:wrap}.row button{flex:1}output{float:right;font-variant-numeric:tabular-nums;color:#b9ebca}
    .status{position:absolute;left:16px;bottom:64px;max-width:calc(100% - 32px);background:#101614df;padding:6px 10px;border-radius:6px;font-size:12px;white-space:pre-wrap}.status.error{color:#ffb4a9;pointer-events:auto}
    .subtitle{position:absolute;bottom:108px;left:10%;right:10%;text-align:center;font-size:clamp(18px,2vw,30px);line-height:1.4;text-shadow:0 2px 5px #050807}.subtitle span{background:#101614e8;padding:3px 7px;box-decoration-break:clone}
    .start{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);pointer-events:auto;background:#b9ebca;color:#122b1a;border:0;padding:14px 20px;font-weight:600}.start:active{transform:translate(-50%,-50%) scale(.98)}
    [hidden]{display:none!important}@media(max-width:600px){.bar strong{display:none}.bar{right:8px;top:8px}.panel{right:8px;top:82px;width:260px}}
  </style>
  <div class="bar"><strong>Synchro</strong><button id="toggle" aria-label="Play with translation" title="Play with translation">${icons.play}</button><button id="captions" aria-label="Translation captions" title="Translation captions" aria-pressed="false">${icons.captions}</button><button id="settings" aria-label="Translation settings" title="Translation settings" aria-expanded="false">${icons.settings}</button><button id="close" aria-label="Close translation" title="Close translation">${icons.close}</button></div>
  <section class="panel" id="panel" aria-label="Translation settings" hidden>
    <label>Voice<select id="voice"><option value="albina">Albina · female</option><option value="alfia">Alfia · female</option><option value="roman">Roman · male</option><option value="eduard">Eduard · male</option><option value="alexandr">Alexander · male</option></select></label>
    <label>Video language<select id="sourceLanguage"><option value="en">English</option><option value="zh">Chinese</option><option value="ko">Korean</option><option value="ja">Japanese</option></select></label>
    <label><span>Voiceover <output id="ttsValue">90%</output></span><input id="tts" aria-label="Voiceover volume" type="range" min="0" max="100" value="90"></label>
    <label><span>Original <output id="originalValue">55%</output></span><input id="original" aria-label="Original volume" type="range" min="0" max="100" value="55"></label>
    <label><span>Zoom <output id="zoomValue">100%</output></span><input id="zoom" aria-label="Video zoom" type="range" min="50" max="300" value="100"></label>
    <div class="row"><button id="fit" aria-pressed="true">Fit</button><button id="fill" aria-pressed="false">Fill</button></div>
    <p style="margin:12px 0 0;color:#a7b5ad;font-size:12px">Original audio is lowered during Russian speech. Use YouTube controls to pause and seek.</p>
  </section><button id="start" class="start" hidden>Play with translation</button><div id="subtitle" class="subtitle" hidden><span></span></div><div id="status" class="status" role="status"><span id="statusText">Fetching audio and preparing models…</span> <span id="usageText"></span> <button id="retry" hidden>Retry translation</button> <button id="dismiss" aria-label="Dismiss error" hidden>Dismiss</button></div>`;
  const find = id => root.getElementById(id);
  const pictureStyle = document.createElement('style');
  pictureStyle.textContent = 'video[data-synchro-native]{width:100%!important;height:100%!important;left:0!important;top:0!important;object-fit:var(--synchro-fit,contain)!important;transform:scale(var(--synchro-zoom,1))!important;transform-origin:center!important}.html5-video-container[data-synchro-container]{width:100%!important;height:100%!important}';
  video.setAttribute('data-synchro-native', '');
  const container = video.closest('.html5-video-container');
  container?.setAttribute('data-synchro-container', '');
  document.documentElement.append(pictureStyle); player.append(host);

  function send(type, extra = {}) {
    return chrome.runtime.sendMessage({type, position: video.currentTime, revision, ...extra}).catch(() => ({ok: false}));
  }
  function stopAudio() {
    for (const source of sources.values()) { try { source.stop(); } catch {} }
    sources.clear(); lastClock = 0; heldCue = null;
  }
  function pauseForBuffer() {
    buffering = true;
    if (!video.paused) { internalPause = true; video.pause(); }
    stopAudio();
  }
  function save() {
    void chrome.storage.local.set({youtubeView: {ttsVolume, originalVolume, zoom, fit, captions}});
  }
  function text(id, value) {
    const element = find(id);
    if (element.textContent !== value) element.textContent = value;
  }
  function applyPicture() {
    video.style.setProperty('--synchro-fit', fit); video.style.setProperty('--synchro-zoom', zoom);
    find('zoom').value = String(zoom * 100); find('zoomValue').textContent = `${Math.round(zoom * 100)}%`;
    find('fit').setAttribute('aria-pressed', String(fit === 'contain')); find('fill').setAttribute('aria-pressed', String(fit === 'cover'));
  }
  async function toggle() {
    await context.resume();
    if (failed) { wanted = true; restart(); return; }
    if (wanted) { wanted = false; video.pause(); stopAudio(); }
    else {
      wanted = true;
      if (!preparing && ready - video.currentTime > (finished ? .05 : 1.25)) { buffering = false; await video.play().catch(() => {}); }
      else buffering = true;
    }
  }
  function restart() {
    revision++; cues = []; ready = video.currentTime; finished = false; preparing = true; error = ''; failed = false;
    decodeQueue = Promise.resolve();
    cloudUsage = undefined; text('usageText', '');
    pauseForBuffer();
    text('statusText', 'Preparing translation from the selected position…');
    const stamp = revision;
    void send('youtube-seek').then(result => { if (!result?.ok && !closed && stamp === revision) showError(result?.error || 'Could not restart translation'); });
  }
  function seek() {
    if (player.classList.contains('ad-showing')) return;
    preparing = true; pauseForBuffer(); clearTimeout(seekTimer);
    seekTimer = setTimeout(restart, 250);
  }
  function paused() {
    if (heldCue && internalPause) { internalPause = false; return; }
    stopAudio();
    if (internalPause) internalPause = false;
    else if (!video.seeking) wanted = false;
  }
  function played() {
    if (closed) return;
    wanted = true;
    if (failed) { restart(); return; }
    if (preparing || ready - video.currentTime < (finished ? .05 : 1.1)) pauseForBuffer();
  }
  function cleanup() {
    if (closed) return;
    closed = true; clearInterval(timer); clearTimeout(seekTimer); cancelAnimationFrame(frame); stopAudio();
    void context.close(); void send('youtube-stop');
    video.removeEventListener('pause', paused); video.removeEventListener('play', played); video.removeEventListener('seeking', seek);
    video.removeAttribute('data-synchro-native'); container?.removeAttribute('data-synchro-container');
    video.style.removeProperty('--synchro-fit'); video.style.removeProperty('--synchro-zoom');
    video.volume = original.volume; video.muted = original.muted; video.playbackRate = original.rate;
    const nativeButton = player.querySelector('.ytp-subtitles-button');
    if (original.captions && nativeButton?.getAttribute('aria-pressed') === 'false') nativeButton.click();
    chrome.runtime.onMessage.removeListener(receive); window.removeEventListener('pagehide', cleanup);
    pictureStyle.remove(); host.remove(); delete window.__synchroYoutube;
  }
  function showError(message) {
    error = message; failed = true; preparing = false; wanted = false; pauseForBuffer();
    void send('youtube-stop');
  }
  function receive(message) {
    const event = message.event;
    if (message.type !== 'youtube-event' || !event || event.revision !== revision || closed) return;
    if (event.cloud_usage) {
      cloudUsage = event.cloud_usage;
      if (Object.keys(cloudUsage.stages || {}).length) text('usageText', `· Cloud ${cloudUsage.unpriced_requests ? '≥' : ''}$${cloudUsage.reported_cost_usd.toFixed(5)}`);
    }
    if (event.type === 'error') showError(event.message);
    if (event.type === 'opened') duration = event.duration;
    if (event.type === 'result') {
      const stamp = revision;
      decodeQueue = decodeQueue.catch(() => {}).then(async () => {
        if (closed || stamp !== revision || failed) return;
        const decoded = [];
        for (const {wav, ...cue} of event.segments) {
          if (cues.some(item => item.id === cue.id)) continue;
          const bytes = Uint8Array.from(atob(wav), char => char.charCodeAt(0));
          cue.buffer = await context.decodeAudioData(bytes.buffer);
          decoded.push(cue);
        }
        if (closed || stamp !== revision || failed) return;
        cues.push(...decoded); ready = Math.max(ready, event.ready_until); finished = event.finished;
      }).catch(() => { if (!closed && stamp === revision) showError('Could not decode translated speech'); });
    }
  }
  chrome.runtime.onMessage.addListener(receive);
  window.addEventListener('pagehide', cleanup, {once: true});
  video.addEventListener('pause', paused); video.addEventListener('play', played); video.addEventListener('seeking', seek);
  video.pause(); video.muted = false;
  if (original.captions) nativeCaptions.click();
  find('toggle').onclick = toggle; find('start').onclick = toggle; find('close').onclick = cleanup;
  find('retry').onclick = toggle;
  find('dismiss').onclick = () => { error = ''; };
  for (const type of ['click', 'dblclick', 'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'wheel']) root.addEventListener(type, event => event.stopPropagation());
  find('settings').onclick = () => { find('panel').hidden = !find('panel').hidden; find('settings').setAttribute('aria-expanded', String(!find('panel').hidden)); };
  root.addEventListener('keydown', event => { if (event.key === 'Escape') { find('panel').hidden = true; find('settings').setAttribute('aria-expanded', 'false'); find('settings').focus(); } event.stopPropagation(); });
  find('captions').onclick = () => { captions = !captions; save(); };
  find('tts').oninput = event => { ttsVolume = Number(event.target.value) / 100; gain.gain.setTargetAtTime(ttsVolume, context.currentTime, .03); find('ttsValue').textContent = `${event.target.value}%`; save(); };
  find('original').oninput = event => { originalVolume = Number(event.target.value) / 100; find('originalValue').textContent = `${event.target.value}%`; save(); };
  find('zoom').oninput = event => { zoom = Number(event.target.value) / 100; applyPicture(); save(); };
  find('fit').onclick = () => { fit = 'contain'; zoom = 1; applyPicture(); save(); };
  find('fill').onclick = () => { fit = 'cover'; zoom = 1; applyPicture(); save(); };
  find('voice').onchange = async event => { await chrome.storage.local.set({voice: event.target.value}); restart(); };
  find('sourceLanguage').onchange = async event => { await chrome.storage.local.set({sourceLanguage: event.target.value}); restart(); };
  void chrome.storage.local.get(['youtubeView', 'voice', 'sourceLanguage', 'delay', 'translation']).then(data => {
    const saved = data.youtubeView || {};
    ttsVolume = Math.max(0, Math.min(1, Number(saved.ttsVolume ?? .9)));
    originalVolume = Math.max(0, Math.min(1, Number(saved.originalVolume ?? .55)));
    zoom = Math.max(.5, Math.min(3, Number(saved.zoom) || 1)); fit = saved.fit === 'cover' ? 'cover' : 'contain'; captions = saved.captions === true;
    gain.gain.value = ttsVolume;
    for (const [name, value] of [['tts', ttsVolume], ['original', originalVolume]]) { find(name).value = String(Math.round(value * 100)); find(name + 'Value').textContent = `${Math.round(value * 100)}%`; }
    const voiceSelect = find('voice');
    const allCloud = data.translation?.mode === 'cloud_all';
    const aliases = allCloud ? {albina: 'female', alfia: 'female', roman: 'male', alexandr: 'male', eduard: 'male-eugene'} :
      {female: 'albina', male: 'roman', 'male-eugene': 'eduard'};
    if (allCloud) voiceSelect.innerHTML = '<option value="female">Nova · cloud female</option><option value="male">Onyx · cloud male</option><option value="male-eugene">Echo · cloud male</option>';
    const selectedVoice = aliases[data.voice] || data.voice;
    if ([...voiceSelect.options].some(option => option.value === selectedVoice)) voiceSelect.value = selectedVoice;
    find('sourceLanguage').value = ['en', 'zh', 'ko', 'ja'].includes(data.sourceLanguage) ? data.sourceLanguage : 'en';
    host.dataset.delay = String(Number(data.delay) || 20); applyPicture();
  });
  function tick() {
    if (closed) return;
    const ad = player.classList.contains('ad-showing');
    if (ad) { wasAd = true; stopAudio(); video.playbackRate = 1; text('statusText', 'Ad · translation paused'); frame = requestAnimationFrame(tick); return; }
    if (wasAd) { wasAd = false; restart(); }
    const time = video.currentTime;
    if (heldCue && sources.get(heldCue.id)?.done) {
      heldCue = null;
      if (wanted && !preparing && !error) void video.play().catch(() => { wanted = false; });
    }
    // Keep an exceptionally long voice's last words when Chromium reaches its minimum video speed.
    if (!heldCue && wanted && !video.paused && !video.seeking) {
      const unfinished = cues.find(item => item.source_duration / item.duration < .0625 &&
        time >= item.start + item.source_duration && sources.has(item.id) && !sources.get(item.id).done);
      if (unfinished) { heldCue = unfinished; internalPause = true; video.pause(); }
    }
    const cue = heldCue || cues.find(item => item.start <= time && time < item.start + item.source_duration);
    const rate = cue ? Math.max(.0625, Math.min(16, cue.source_duration / cue.duration)) : 1;
    if (Math.abs(video.playbackRate - rate) > .0001) { stopAudio(); video.playbackRate = rate; }
    if (!heldCue && lastClock && Math.abs((time - lastTime) / rate - (context.currentTime - lastClock)) > .18) stopAudio();
    if (preparing && (ready - time >= Math.min(10, Number(host.dataset.delay) || 20, duration - time - .1) - .025 || finished && ready - time > .1)) preparing = false;
    if (wanted && !preparing && !error && video.paused && buffering && ready - time > (finished ? .05 : 1.25)) { buffering = false; void context.resume(); void video.play().catch(() => { wanted = false; }); }
    if (wanted && !video.paused && (ready - time < 1.1 && !finished || preparing)) pauseForBuffer();
    const running = wanted && (!video.paused || heldCue) && !video.seeking && video.readyState >= 3 && !preparing && !error;
    if (!running) stopAudio();
    else {
      if (!lastClock) { lastClock = context.currentTime; lastTime = time; }
      if (cue?.buffer && !sources.has(cue.id)) {
        const offset = Math.max(0, (time - cue.start) / rate);
        if (offset < cue.buffer.duration) {
          const source = context.createBufferSource(); source.buffer = cue.buffer; source.connect(gain); source.done = false;
          source.onended = () => { source.done = true; };
          sources.set(cue.id, source); source.start(0, offset);
        }
      }
    }
    const speaking = running && ttsVolume > 0 && cue && sources.has(cue.id) && !sources.get(cue.id).done;
    if (speaking) duckUntil = context.currentTime + .3;
    const ducked = running && (speaking || context.currentTime < duckUntil);
    const level = originalVolume * (ducked ? .22 : 1);
    const now = performance.now(), dt = Math.max(0, Math.min(.05, (now - lastMix) / 1000)); lastMix = now;
    const mixed = video.volume + (level - video.volume) * (1 - Math.exp(-dt / (ducked ? .06 : .45)));
    if (Math.abs(video.volume - level) > .001) video.volume = mixed;
    find('captions').setAttribute('aria-pressed', String(captions));
    find('subtitle').hidden = !captions || !cue;
    const subtitle = find('subtitle').firstElementChild;
    if (subtitle.textContent !== (cue?.text || '')) subtitle.textContent = cue?.text || '';
    const label = failed ? 'Retry translation' : wanted ? 'Pause' : 'Play with translation';
    if (find('toggle').getAttribute('aria-label') !== label) {
      find('toggle').setAttribute('aria-label', label); find('toggle').title = label; find('toggle').innerHTML = wanted ? icons.pause : icons.play;
    }
    find('start').hidden = preparing || !video.paused || wanted || Boolean(error);
    find('start').textContent = failed ? 'Retry translation' : 'Play with translation';
    find('retry').hidden = !error || !failed;
    find('dismiss').hidden = !error;
    find('status').classList.toggle('error', Boolean(error));
    text('statusText', error || (failed ? 'Translation stopped · press Play to retry' : preparing ? 'Preparing translation…' : buffering ? 'Waiting for the next phrase…' : `Translated to ${Math.floor(ready / 60)}:${String(Math.floor(ready % 60)).padStart(2, '0')}${rate < .99 ? ' · synchronizing a long phrase' : ''}`));
    if (cloudUsage?.stages && Object.keys(cloudUsage.stages).length) {
      find('status').title = 'Provider-reported usage: ' + Object.entries(cloudUsage.stages).map(([stage, usage]) => `${stage}: $${usage.reported_cost_usd.toFixed(6)} (${usage.requests} requests)`).join(' · ') + (cloudUsage.unpriced_requests ? ' · Some requests have no reported price; total is incomplete' : ' · Provider-reported amounts may differ from final billing');
    }
    for (const item of cues) if (item.start + item.source_duration < time - 15) { item.buffer = null; sources.delete(item.id); }
    cues = cues.filter(item => item.start + item.source_duration >= time - 30);
    frame = requestAnimationFrame(tick);
  }
  timer = setInterval(() => {
    if (location.href !== initialUrl || !video.isConnected || !host.isConnected) return cleanup();
    if (Date.now() - lastReport > 750) { lastReport = Date.now(); void send('youtube-position'); }
  }, 250);
  window.__synchroYoutube = {close: cleanup};
  frame = requestAnimationFrame(tick);
  return {ok: true, position};
})();
