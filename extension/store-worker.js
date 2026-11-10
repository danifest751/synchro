let handle, directory;
self.onmessage = async ({data}) => {
  try {
    if (data.type === 'open') {
      handle?.close();
      const root = await navigator.storage.getDirectory();
      await root.removeEntry('synchro-current', {recursive: true}).catch(error => { if (error.name !== 'NotFoundError') throw error; });
      directory = await root.getDirectoryHandle('synchro-current', {create: true});
      const file = await directory.getFileHandle('video.webm', {create: true});
      handle = await file.createSyncAccessHandle(); handle.truncate(0); handle.flush();
    } else if (data.type === 'append') {
      const bytes = new Uint8Array(data.bytes);
      const written = handle.write(bytes, {at: data.offset});
      if (written !== bytes.length) throw new Error('Not enough storage for recording');
      handle.flush();
    } else if (data.type === 'cue') {
      if (!/^cue-\d+\.wav$/.test(data.fileName)) throw new Error('Invalid speech file name');
      const file = await directory.getFileHandle(data.fileName, {create: true});
      const audio = await file.createSyncAccessHandle();
      try {
        const bytes = new Uint8Array(data.bytes);
        if (audio.write(bytes, {at: 0}) !== bytes.length) throw new Error('Not enough storage for speech');
        audio.truncate(bytes.length); audio.flush();
      } finally { audio.close(); }
    } else if (data.type === 'close') { handle?.flush(); handle?.close(); handle = null; }
    self.postMessage({id: data.id});
  } catch (error) { self.postMessage({id: data.id, error: error.message}); }
};
