# BOT-2B operator enablement notes

BOT-2B remains fail-closed unless the existing provider write gate is explicitly enabled and the Sanaei panel has a current CONTRACT_VERIFIED certification for the exact v3.5.0 contract digest.

Before enabling activation in a real environment:

- provide a production-generated `VPN_SALE_DELIVERY_ENCRYPTION_KEY` outside source control;
- set an explicit `VPN_SALE_DELIVERY_ENCRYPTION_KEY_VERSION`;
- retain old keys only in `VPN_SALE_DELIVERY_DECRYPT_KEYS_JSON` for controlled decrypt-only rotation windows;
- ensure provider credentials are already migrated to the version-aware AEAD provider vault;
- run database migration `0038_service_activation_delivery`;
- confirm the existing immutable fulfillment target bindings point at the intended Sanaei panel/inbound;
- verify the panel version and contract digest through the existing certification flow;
- keep `VPN_SALE_PROVIDER_WRITES_ENABLED=false` until the above checks pass.

Enabling provider writes allows both BOT-2A.1 CREATE and BOT-2B activation UPDATE. There is intentionally no separate unsafe shortcut that marks a service active locally without provider read-after-write verification.

Customer delivery endpoints and Telegram configuration reveal remain unavailable until the service is ACTIVE, its required attachment is VERIFIED and an ACTIVE encrypted delivery revision exists.
