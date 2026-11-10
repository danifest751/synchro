export function playableUntil(videoEnd, readyUntil) {
  return Math.min(videoEnd, readyUntil);
}

export function scheduleCue(cue, position) {
  const span = cue.source_duration ?? cue.duration;
  if (cue.start + span <= position) return null;
  const rate = Math.min(1, span / cue.duration);
  return {delay: Math.max(0, cue.start - position), offset: Math.max(0, position - cue.start) / rate};
}

export function cueRate(cue) {
  return cue ? Math.min(1, (cue.source_duration ?? cue.duration) / cue.duration) : 1;
}

export function cueAt(cues, position) {
  return cues.find(cue => cue.start <= position && position < cue.start + (cue.source_duration ?? cue.duration));
}

export function canStart(videoEnd, readyUntil, position, delay, finished) {
  const remaining = playableUntil(videoEnd, readyUntil) - position;
  return remaining > 0.1 && (finished || (videoEnd - position >= delay && remaining >= 3));
}
