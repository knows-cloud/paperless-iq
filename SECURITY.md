# Security Policy

## Supported Versions

Only the latest release on `main` is actively maintained.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately using one of the following channels:

- **GitHub private security advisory** — preferred. Use the
  [Security → Advisories → New draft advisory](../../security/advisories/new) form in this repository.
- **Email** — m@knows.cloud. Encrypt sensitive details with PGP if possible (key available on request).

We aim to acknowledge reports within 48 hours and to ship a fix or mitigation within 14 days for critical issues.

## Scope

This project is a self-hosted document intelligence layer on top of [Paperless-NGX](https://github.com/paperless-ngx/paperless-ngx).

### In scope

- Authentication bypass or privilege escalation in the Paperless IQ API
- Injection vulnerabilities (prompt injection leading to data exfiltration, SQL injection, command injection)
- Credential exposure via API responses or logs
- SSRF or path traversal in document handling
- Insecure storage or transmission of LLM provider credentials

### Out of scope

- Vulnerabilities in Paperless-NGX itself (report upstream)
- Issues that require physical access to the host
- Self-inflicted misconfiguration (e.g. exposing the port without authentication on a public network)
- Rate-limiting or denial-of-service against a single self-hosted instance

## Security Model

Paperless IQ is designed for **self-hosted, single-tenant** deployments on a trusted local network or behind a VPN. It is not hardened for direct public internet exposure.

- LLM provider API keys and the Paperless token are stored Fernet-encrypted in a SQLite database.
- Authentication is optional but strongly recommended for multi-user setups (enable `auth_required` in settings).
- All communication between the frontend and backend is over the same host by default; TLS termination is the operator's responsibility.

## Disclosure Policy

We follow [coordinated disclosure](https://en.wikipedia.org/wiki/Coordinated_vulnerability_disclosure). Once a fix is released, we will publish a summary of the vulnerability (without exploitable detail) in the GitHub security advisories tab.
