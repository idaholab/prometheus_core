#!/bin/sh
#
# Install custom CA certificates into the image's system trust store.
#
# Shared by sdk/Dockerfile and platform/frontend/Dockerfile. Both run it during
# the image build with this directory bind-mounted (read-only) into the build
# container from a named build context called "certs":
#
#   RUN --mount=type=bind,from=certs,target=/tmp/certs sh /tmp/certs/setup.sh
#
# This directory is outside both build contexts, so every build must pass it
# in, e.g. `docker build --build-context certs=../common/certs .` from sdk/.
# sdk/Makefile, platform/docker-compose.yml, .github/workflows/test.yml and
# .github/workflows/publish.yml already do; a bare `docker build` fails with
# "certs: failed to resolve source metadata".
#
# Drop any extra CA certificates (e.g. a corporate TLS-inspection root) into
# common/certs/ next to this script. Each file must be PEM-encoded and named
# *.pem or *.crt; one file may hold several certificates (a bundle). Other
# files in this directory, including this script, are ignored.
#
# With no certificate files present, the image simply gets the stock Debian
# CA store.

# Stop on the first failed command. Without this, a failed copy or
# update-ca-certificates call would be ignored and the build would quietly
# produce an image that is missing the custom CAs.
set -e

# The certificates live next to this script, so it works no matter where the
# directory is mounted.
cert_dir="$(dirname "$0")"

# update-ca-certificates only picks up files under this directory. It may not
# exist yet in a slim base image.
install_dir=/usr/local/share/ca-certificates
mkdir -p "$install_dir"

for cert in "$cert_dir"/*.pem "$cert_dir"/*.crt; do
    # With no matches, the shell leaves the glob pattern itself in $cert;
    # skip it rather than treating the pattern as a file name.
    [ -f "$cert" ] || continue

    # Validate before installing, because update-ca-certificates does not:
    # it exits 0 even when handed garbage, leaving an image that silently
    # lacks the certificate.
    #
    # A plain `openssl x509 -noout` is not enough either: it only reads the
    # first certificate in a file (so a bad cert later in a bundle slips
    # through) and it also accepts DER, which update-ca-certificates cannot
    # use. Instead, parse every PEM certificate in the file and require that
    # the number openssl parsed equals the number of BEGIN CERTIFICATE
    # markers, and that there is at least one. That rejects empty files,
    # non-certificate text, DER files, and partially corrupt bundles.
    #
    # If any certificate in the file is malformed, openssl rejects the whole
    # file, so "parsed" reports 0 rather than the count of good certificates.
    #
    # `|| true` keeps `set -e` from aborting here: grep -c exits 1 when it
    # counts zero matches, and the zero case is reported below instead.
    parsed="$(openssl crl2pkcs7 -nocrl -certfile "$cert" 2>/dev/null \
        | openssl pkcs7 -print_certs 2>/dev/null | grep -c '^subject=' || true)"
    expected="$(grep -c 'BEGIN CERTIFICATE' "$cert" || true)"
    if [ "$parsed" -eq 0 ] || [ "$parsed" -ne "$expected" ]; then
        echo "ERROR: $cert: parsed $parsed of $expected PEM certificates" >&2
        exit 1
    fi

    # Install each certificate as its own file rather than copying the file
    # as-is. update-ca-certificates appends every installed file to the
    # combined bundle either way, but its rehash step only creates the
    # per-certificate hash links in /etc/ssl/certs (<hash>.0) for files that
    # hold exactly one certificate; it skips bundles with a warning. Tools
    # that look CAs up by directory (OpenSSL CApath, `openssl verify
    # -CApath`) would then never find the certificates in a bundle.
    #
    # The source file is left untouched; the split copies are written under
    # $install_dir as <file>-001.crt, <file>-002.crt, ... where <file> is the
    # full source file name, extension included (INL.pem -> INL.pem-001.crt).
    # Keeping the extension guarantees two sources can never install to the
    # same names: foo.pem and foo.crt would otherwise both produce
    # foo-001.crt, and the second would silently overwrite the first. The
    # trailing .crt matters too: update-ca-certificates ignores anything
    # else. Single-certificate files go through the same path and become
    # <file>-001.crt.
    #
    # Only the BEGIN/END CERTIFICATE blocks are kept, so any comment text
    # between certificates is dropped. Trailing carriage returns are stripped
    # so CRLF (Windows) line endings don't reach the trust store. Validation
    # above already guaranteed every block is well formed.
    base="$(basename "$cert")"
    awk -v prefix="$install_dir/$base" '
        { sub(/\r$/, "") }
        /-----BEGIN CERTIFICATE-----/ {
            n++
            out = sprintf("%s-%03d.crt", prefix, n)
            inside = 1
        }
        inside { print > out }
        /-----END CERTIFICATE-----/ && inside {
            close(out)
            inside = 0
        }
    ' "$cert"
done

# Rebuild /etc/ssl/certs/ca-certificates.crt from the Debian CAs plus the
# files installed above. Tools that read the system default bundle (git,
# curl, OpenSSL-based clients) pick the custom CAs up from there.
update-ca-certificates

# The Dockerfile points SSL_CERT_FILE, REQUESTS_CA_BUNDLE and
# NODE_EXTRA_CA_CERTS at ca-bundle.pem, so keep that path as a copy of the
# combined system bundle for Python and Node clients that honor those
# variables.
cp /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-bundle.pem
