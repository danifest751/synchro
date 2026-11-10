const start = document.querySelector('#start'), status = document.querySelector('#status');
document.querySelector('#settings').onclick = () => chrome.runtime.openOptionsPage();
start.onclick = async () => {
  start.disabled = true; status.textContent = 'Warming up local models… Keep this popup open.';
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    const result = await chrome.runtime.sendMessage({type: 'start', tabId: tab.id});
    if (!result?.ok) throw new Error(result?.error || 'Could not start translation');
    window.close();
  } catch (error) { status.textContent = error.message; status.className = 'error small'; start.disabled = false; }
};
