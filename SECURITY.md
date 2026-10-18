# Security policy

Visto drives real devices and sends screenshots to an AI provider, so
security reports are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Report a vulnerability" in the Security tab of this repository). Include steps
to reproduce and the potential impact. You can expect an initial reply within a
few days.

## Scope notes

- Visto is designed to run locally: the API and console bind to loopback by
  default. Exposing them on a network is not a supported configuration: the
  backend rejects any request whose Host is not loopback, which also blocks DNS
  rebinding from web pages open in the operator's browser.
- Run screenshots and history may contain private data and are stored unencrypted
  under the local data directory. See [docs/artifact-storage.md](docs/artifact-storage.md).
- Screenshots, goals and clarifications are transmitted to the configured AI
  provider. See [docs/provider-setup.md](docs/provider-setup.md).
