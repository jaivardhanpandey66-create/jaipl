#!/usr/bin/env bash
# Build zing-setup-<version>.exe. Needs the official Python embeddable zip
# and Inno Setup 6. Both are free downloads.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

VERSION="$(grep -oP 'AppVersion="\K[^"]+' zing.iss)"

if [ ! -d python-embed ]; then
  echo "==> fetching the embeddable Python runtime"
  curl -fsSL -o python-embed.zip \
    "https://www.python.org/ftp/python/${VERSION%.*}/python-${VERSION%.*}-embed-amd64.zip" \
    || { echo "download the embeddable zip manually into $here/python-embed" >&2; exit 1; }
  mkdir -p python-embed
  unzip -q python-embed.zip -d python-embed
  rm python-embed.zip
fi

echo "==> compiling the installer"
iscc zing.iss
echo "==> done: $here/../../dist/zing-setup-$VERSION.exe"
