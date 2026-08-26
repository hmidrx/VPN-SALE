# Encrypted backup boundary

`scripts/operations/backup.py` and `restore.py` use an authenticated, versioned
AES-256-GCM envelope. The 32-byte key is read from a root-readable secret file with
`--key-file`, or from `VPN_SALE_BACKUP_MASTER_KEY_B64`. A checksum is verified before
decryption and the AEAD tag detects tampering and wrong keys.

Production procedure:

1. create a logical PostgreSQL dump with `pg_dump --format=custom`;
2. create a manifest for private media/object storage and include it beside the dump;
3. encrypt the archive and upload only the encrypted object plus sanitized manifest;
4. restore into an isolated database and run migrations/read-only integrity checks;
5. require the exact `RESTORE PRODUCTION VPN-SALE` confirmation for a production target.

Never store the key, plaintext dump, panel credentials or real destination URL in Git
or CI artifacts. Rotate keys with a documented retention window for older backups.
