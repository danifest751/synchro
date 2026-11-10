# Security

This prototype has not received an independent security audit. Deploy model services on loopback or a private authenticated link and expose only the gateway through HTTPS when remote viewers need access.

## Credentials and boundaries

- Generate unique owner, guest, ASR, and TTS keys; do not reuse keys across roles.
- Keep `.local/`, environment files, model files, SSH keys, and personal ZIPs out of Git and public releases.
- The extension's manifest key is a public identity key. It is intentionally committed and is not a private signing key.
- Keep exact extension-Origin checks and the explicit server URL allowlist. A connection file must not be able to redirect a token to any arbitrary server.
- Treat fetched URLs, transcripts, model output, audio, and accent-service output as untrusted data.
- Restrict any SSH gateway account to required forwarding ports and disallow interactive use.
- The optional CONNECT proxy accepts only HTTPS to validated public YouTube addresses; never turn it into an unauthenticated public proxy.

The guest registry contains hashes, while connection files contain usable bearer keys. Revocation takes effect at the next authenticated request and cannot retract already delivered audio. Origin checks complement authentication; they do not replace secret keys. Anyone who has a valid key can make non-browser API requests.

## Reporting

For vulnerabilities, use GitHub's private vulnerability reporting if enabled, or contact the repository owner privately through their GitHub profile. Do not post exploit details, real keys, connection files, signed media URLs, or private video contents in a public issue. Describe the affected version, expected boundary, and a reproduction using dummy credentials.

If a key leaks, revoke it, rotate affected service keys, replace private connection files, and inspect your own server logs. Removing a credential from the latest commit does not remove it from repository history; avoid committing it in the first place.
