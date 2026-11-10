# GitHub extension updates

Chrome does not let an unpacked extension overwrite its own installed files. Synchro therefore separates downloading files from reloading the extension: an optional standard-library Python helper installs GitHub Releases, and the extension's existing alarm reloads when playback is closed.

On Windows, run once from your own checkout with Python installed:

```powershell
./tools/install-updater.ps1 -ExtensionDir 'C:/path/to/Synchro/extension'
```

This creates the current user's **Synchro GitHub extension updates** scheduled task. It checks every 15 minutes while that user is signed in. The task runs with `pythonw.exe`, so it opens no console. Keep that checkout and Python installation in place. Task Scheduler exposes its last result; run the Python command below in a terminal for detailed errors.

For a manual check or update on any OS:

```sh
python tools/update_extension.py --target /path/to/Synchro/extension --check
python tools/update_extension.py --target /path/to/Synchro/extension
```

The helper accepts only the stable latest release of `danifest751/synchro`, the exact `Synchro-extension.zip` asset, a matching numeric manifest version and GitHub's SHA-256 asset digest. Drafts, prereleases, downgrades, unsafe archive paths, oversized archives and new extension permissions are rejected. An update that needs new permissions must be reviewed and installed manually.

Existing server endpoints, host permissions, CSP and the manifest public key are preserved. Chrome storage remains with that extension identity, including provider profiles and connection keys. Private guest connection files outside the extension folder are not overwritten. Public release archives contain no personal access keys.

Before replacement the helper copies the existing extension to `.synchro-update-backups/<version>-<timestamp>` beside its folder. Scripts are replaced first and the version manifest last. If copying fails, the helper restores the backup. Old backup folders are retained for manual rollback. Close translation before applying a manual rollback, restore the desired backup into the same extension folder, then reload it in Chrome.

To remove the Windows schedule:

```powershell
Unregister-ScheduledTask -TaskName 'Synchro GitHub extension updates' -Confirm:$false
```

GitHub updates cover the browser extension only. The operator must deploy a compatible gateway separately; downloading browser files does not update inference services.
