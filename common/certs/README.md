# CA certificates

Extra CA certificates baked into the Prometheus container images, plus the
script that installs them. `INL.pem` is the INL CA bundle; it includes the
`CAINLROOT` root that the INL network's Zscaler TLS inspection chains to, which
is what lets containers make HTTPS requests from inside INL.

## What `setup.sh` does

At image build time, for each `*.pem` / `*.crt` file in this directory:

1. Fails the build unless every certificate in the file parses as PEM.
2. Splits it into one certificate per file under
   `/usr/local/share/ca-certificates/` (`INL.pem` → `INL.pem-001.crt`, …).
3. Runs `update-ca-certificates`, which adds them to the system bundle
   (`/etc/ssl/certs/ca-certificates.crt`) and the hashed `/etc/ssl/certs/`
   directory.
4. Copies the system bundle to `/etc/ssl/certs/ca-bundle.pem`, which the SDK
   image points `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` and `NODE_EXTRA_CA_CERTS`
   at.

Other files here (like this README) are ignored.

## Where it's used

- `sdk/Dockerfile` (the `prometheus_api` base image used by the Python services)
- `platform/frontend/Dockerfile`

Both mount this directory from a named build context called `certs`. That
context is passed by `sdk/Makefile`, `platform/docker-compose.yml`,
`.github/workflows/test.yml`, and `.github/workflows/publish.yml`. To build an
image by hand, pass it yourself:

```sh
cd sdk && docker build --build-context certs=../common/certs .
```

Without it, the build fails with `certs: failed to resolve source metadata`.

## Adding your own certificates

Put the file in this directory and rebuild the images. The file must:

- be named `*.pem` or `*.crt` (lowercase extension)
- be PEM-encoded (`-----BEGIN CERTIFICATE-----`). A file can hold one
  certificate or a bundle of several.

To convert a DER-encoded certificate to PEM:

```sh
openssl x509 -inform der -in my-ca.cer -out my-ca.pem
```
