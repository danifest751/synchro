export async function installView(video, setVolume) {
  const stage = document.querySelector('#stage'), scale = document.querySelector('#scale');
  const captions = document.querySelector('#captions'), wide = document.querySelector('#wide'), volume = document.querySelector('#volume');
  const stored = (await chrome.storage.local.get('view')).view || {};
  let zoom = Math.max(.5, Math.min(4, Number(stored.zoom) || 1));
  let x = Number(stored.x) || 0, y = Number(stored.y) || 0, drag;
  video.style.objectFit = stored.fit === 'cover' ? 'cover' : 'contain';
  captions.checked = stored.captions === true; wide.checked = stored.wide === true;
  volume.value = String(Math.max(0, Math.min(100, Number(stored.volume ?? 80))));
  function apply() {
    scale.value = String(zoom * 100); document.querySelector('#scaleValue').textContent = `${Math.round(zoom * 100)}%`;
    stage.style.setProperty('--zoom', zoom); stage.style.setProperty('--pan-x', `${x}px`); stage.style.setProperty('--pan-y', `${y}px`);
    stage.classList.toggle('zoomed', zoom > 1);
    document.querySelector('.player').classList.toggle('wide', wide.checked);
    document.querySelector('.subtitle').hidden = !captions.checked; document.querySelector('#source').hidden = !captions.checked;
    setVolume(Number(volume.value) / 100);
  }
  function save() { void chrome.storage.local.set({view: {zoom, x, y, fit: video.style.objectFit, captions: captions.checked, wide: wide.checked, volume: Number(volume.value)}}); }
  scale.oninput = () => { zoom = Number(scale.value) / 100; apply(); };
  scale.onchange = save;
  function reset(fit) { zoom = 1; x = 0; y = 0; video.style.objectFit = fit; apply(); save(); }
  document.querySelector('#fit').onclick = () => reset('contain');
  document.querySelector('#fill').onclick = () => reset('cover');
  stage.ondblclick = () => reset('contain');
  for (const control of [captions, wide, volume]) control.oninput = () => { apply(); save(); };
  stage.onpointerdown = event => {
    if (zoom <= 1 || event.button !== 0) return;
    drag = {left: event.clientX - x, top: event.clientY - y}; stage.setPointerCapture(event.pointerId); stage.classList.add('dragging');
  };
  stage.onpointermove = event => {
    if (!drag) return;
    const boundX = stage.clientWidth * zoom / 2, boundY = stage.clientHeight * zoom / 2;
    x = Math.max(-boundX, Math.min(boundX, event.clientX - drag.left));
    y = Math.max(-boundY, Math.min(boundY, event.clientY - drag.top)); apply();
  };
  const endDrag = () => { if (!drag) return; drag = null; stage.classList.remove('dragging'); save(); };
  stage.onpointerup = endDrag; stage.onpointercancel = endDrag;
  document.addEventListener('keydown', event => {
    if (event.target.matches('input,button,summary,select,textarea') || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.code === 'Space') { event.preventDefault(); if (!document.querySelector('#play').disabled) document.querySelector('#play').click(); }
    if (event.code === 'KeyF') document.querySelector('#fullscreen').click();
    if (event.code === 'KeyC') { captions.checked = !captions.checked; apply(); save(); }
  });
  apply();
}
