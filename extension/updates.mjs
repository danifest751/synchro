export function updateAction(loaded, disk, active, playerOpen) {
  if (!/^\d+(\.\d+){0,3}$/.test(disk || '') || disk === loaded) return 'none';
  return active || playerOpen ? 'defer' : 'reload';
}
