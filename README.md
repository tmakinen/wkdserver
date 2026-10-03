# WKD PGP Key Microservice

A lightweight, enterprise-ready, containerized microservice that automates the synchronization and delivery of public PGP keys via the Web Key Directory (WKD) protocol.

The service is built around a split architecture designed for performance and reliability:
1. **Sync Ingestion Layer (Cron):** A scheduled Python task that safely extracts user public keys from corporate LDAP directory structures via SASL External binds, filters out non-Ed25519 entries using an ephemeral GnuPG keyring, and populates a cache storage layer.
2. **Delivery API (HTTP):** A high-performance Gunicorn + Flask API that reads processed keys from memory and serves them instantly using precise WKD-compliant headers and binary payloads.

---

## System Architecture & URI Direct Routing

To achieve reliable key lookup matching standard PGP client automation rules (like `gpg --locate-keys` or automatic Thunderbird discovery handlers), this microservice supports both the Advanced and Direct WKD Methods.

```text
    PGP Client Lookup
          │
          ├─► [ Advanced Method ] ──► https://example.com/.well-known/openpgpkey/example.com/hu/[z-base32-hash]
          │
          └─► [ Direct Method ]   ──► https://example.com/.well-known/openpgpkey/hu/[z-base32-hash]
```

### Path Mechanics
* **Advanced Routing:** The HTTP API parses the URL components directly and looks up keys from Valkey under the precise pattern: `wkd:<domain>:hu:<wkd_hash>`.
* **Direct Routing:** When the query lacks an embedded domain namespace (Direct Method), the service automatically falls back to utilizing a default domain fallback configured via environment flags (`DEFAULT_DOMAIN`).

---

## Deployment (Docker Compose)

The easiest way to execute this microservice stack is by deploying it behind your infrastructure's main load balancer using the unified architecture defined below.

### `docker-compose.yml`

```yaml
services:
  # --- BACKEND CACHE STORAGE ---
  wkd-cache:
    image: valkey/valkey:alpine
    container_name: wkd-cache
    restart: unless-stopped
    command:
      - valkey-server
      - --appendonly yes
    volumes:
      - valkey_data:/data

  # --- HTTP DELIVERY API ---
  wkd-api:
    build:
      context: ./web
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      - VALKEY_URL=redis://wkd-cache:6379/0
      - DEFAULT_DOMAIN=example.com
    ports:
      - "8000:8000"
    depends_on:
      - wkd-cache

volumes:
  valkey_data:
    driver: local
```
