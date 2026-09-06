# Russian Trusted CA certificates

HappyFox needs the Russian Trusted PKI to establish verified HTTPS connections to services such as the MAX Bot API at `https://platform-api2.max.ru`.

The canonical public installation guidance is maintained by Gosuslugi / the Russian Ministry of Digital Development at:

- https://www.gosuslugi.ru/crt

This directory contains the two certificates used by the HappyFox runtime:

- `Russian_Trusted_Root_CA.crt` — Russian Trusted Root CA.
- `Russian_Trusted_Sub_CA.crt` — Russian Trusted Sub CA (issuing CA).

## Production installation

The Docker image copies these certificates into `/usr/local/share/ca-certificates/rus/` and runs `update-ca-certificates` during the immutable image build.

The dedicated-host deploy also runs `scripts/install_russian_trusted_ca.sh`, which validates the certificate subjects and chain before installing the same files into the host system trust store and regenerating `/etc/ssl/certs/ca-certificates.crt`.

Never solve a MAX TLS failure with `ssl=False`, `CERT_NONE`, `curl -k`, `--insecure`, or a comparable verification bypass. Update the trusted CA material and verify the chain instead.

After each production deploy, `scripts/check_max_connectivity.py` performs an authenticated `GET /subscriptions` through the normal `MaxClient`. A failed TLS handshake, invalid MAX credentials, or malformed API response fails the release gate.
