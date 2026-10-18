# Extra CA certificates

Optional. Put PEM certificates named `*.crt` here (for example the root CA of a
TLS-inspecting corporate proxy) and the dev container images trust them at build
time and at runtime. Files in this directory other than this README are ignored
by git; never commit a certificate. See `docs/docker.md`.
