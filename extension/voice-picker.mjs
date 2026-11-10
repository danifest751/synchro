export function fillVoiceSelect(select, voices, preferred) {
  const available = voices.filter(voice => typeof voice.id === 'string' && /^[a-z0-9-]{1,40}$/.test(voice.id) && typeof voice.name === 'string').slice(0, 24);
  if (!available.length) throw new Error('No voices are available for this mode');
  select.replaceChildren(...available.map(voice => {
    const option = document.createElement('option');
    option.value = voice.id; option.textContent = voice.name.slice(0, 120);
    return option;
  }));
  const fallback = preferred?.startsWith('studio-male-') ? 'male' : 'female';
  select.value = available.some(voice => voice.id === preferred) ? preferred : available.some(voice => voice.id === fallback) ? fallback : available[0].id;
}
