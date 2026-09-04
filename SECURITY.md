# Security and credentials

- Do not commit `.env`, neuPrint tokens, Google credentials, or credentials embedded in command lines.
- `NEUPRINT_APPLICATION_CREDENTIALS` is the supported neuPrint credential variable.
- Run manifests record whether authenticated access was used, never the secret value.
- Dataset downloads are written to a temporary `.part` file, hashed, and atomically renamed.
- A changed checksum for an already locked dataset is a hard validation failure.

