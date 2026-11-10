(() => {
  window.__synchroCleanup?.();
  const video = [...document.querySelectorAll('video')].sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight)[0];
  if (!video) return;
  let initial = location.href;
  const ended = () => chrome.runtime.sendMessage({type: 'source-ended'}).catch(() => {});
  const changed = () => chrome.runtime.sendMessage({type: 'source-changed'}).catch(() => {});
  video.addEventListener('ended', ended, {once: true});
  video.addEventListener('seeking', changed);
  const timer = setInterval(() => { if (location.href !== initial) { initial = location.href; changed(); } }, 500);
  window.__synchroCleanup = () => { clearInterval(timer); video.removeEventListener('ended', ended); video.removeEventListener('seeking', changed); };
})();
