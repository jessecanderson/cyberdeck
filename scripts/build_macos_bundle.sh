#!/bin/sh
set -eu

PYTHON_BUILD="20260510"
PYTHON_VERSION="3.13.13"
PYTHON_ARCHIVE="cpython-${PYTHON_VERSION}+${PYTHON_BUILD}-aarch64-apple-darwin-install_only.tar.gz"
PYTHON_SHA256="1ad1ed518447005d4b6dfa16d4f847d45790e17e94e30164a0a6e6c79a99730f"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_BUILD}/cpython-${PYTHON_VERSION}%2B${PYTHON_BUILD}-aarch64-apple-darwin-install_only.tar.gz"

if [ "$#" -ne 2 ]; then
  echo "usage: $0 WHEEL OUTPUT_DIRECTORY" >&2
  exit 2
fi

WHEEL=$1
OUTPUT_DIRECTORY=$2
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(basename "$WHEEL" | sed -E 's/^cyberdeck_tui-([^-]+)-.*/\1/')
WORK_DIRECTORY=$(mktemp -d "${TMPDIR:-/tmp}/cyberdeck-macos.XXXXXX")
trap 'rm -rf "$WORK_DIRECTORY"' EXIT INT TERM

curl --fail --location --silent --show-error "$PYTHON_URL" --output "$WORK_DIRECTORY/$PYTHON_ARCHIVE"
ACTUAL_SHA256=$(shasum -a 256 "$WORK_DIRECTORY/$PYTHON_ARCHIVE" | awk '{print $1}')
if [ "$ACTUAL_SHA256" != "$PYTHON_SHA256" ]; then
  echo "standalone Python checksum mismatch" >&2
  exit 1
fi

mkdir -p "$WORK_DIRECTORY/bundle"
tar -xzf "$WORK_DIRECTORY/$PYTHON_ARCHIVE" -C "$WORK_DIRECTORY/bundle"
BUNDLE_ROOT="$WORK_DIRECTORY/bundle/cyberdeck"
mv "$WORK_DIRECTORY/bundle/python" "$BUNDLE_ROOT"

"$BUNDLE_ROOT/bin/python3" -m pip install \
  --disable-pip-version-check \
  --no-compile \
  "$WHEEL"

mkdir -p "$BUNDLE_ROOT/cyberdeck-bin"
cp "$PROJECT_ROOT/LICENSE" "$BUNDLE_ROOT/LICENSE"
cp "$PROJECT_ROOT/README.md" "$BUNDLE_ROOT/README.md"
cat > "$BUNDLE_ROOT/cyberdeck-bin/cyberdeck" <<'EOF'
#!/bin/sh
set -eu
SOURCE="$0"
while [ -L "$SOURCE" ]; do
  SOURCE_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$SOURCE")" && pwd)
  LINK_TARGET=$(readlink "$SOURCE")
  case "$LINK_TARGET" in
    /*) SOURCE="$LINK_TARGET" ;;
    *) SOURCE="$SOURCE_DIRECTORY/$LINK_TARGET" ;;
  esac
done
BUNDLE_ROOT=$(CDPATH= cd -- "$(dirname -- "$SOURCE")/.." && pwd)
exec "$BUNDLE_ROOT/bin/python3" -m cyberdeck.app "$@"
EOF
chmod +x "$BUNDLE_ROOT/cyberdeck-bin/cyberdeck"

"$BUNDLE_ROOT/bin/python3" -c 'import pyexpat; print(pyexpat.EXPAT_VERSION)'
test "$("$BUNDLE_ROOT/cyberdeck-bin/cyberdeck" --version)" = "cyberdeck $VERSION"
ln -s "$BUNDLE_ROOT/cyberdeck-bin/cyberdeck" "$WORK_DIRECTORY/cyberdeck-link"
test "$("$WORK_DIRECTORY/cyberdeck-link" --version)" = "cyberdeck $VERSION"
file "$BUNDLE_ROOT/bin/python3" | grep -q 'arm64'
"$BUNDLE_ROOT/bin/python3" -m venv "$WORK_DIRECTORY/module-venv"
"$WORK_DIRECTORY/module-venv/bin/python" -c 'import pyexpat, venv'

mkdir -p "$OUTPUT_DIRECTORY"
ARTIFACT="cyberdeck-${VERSION}-macos-arm64.tar.gz"
tar -czf "$OUTPUT_DIRECTORY/$ARTIFACT" -C "$WORK_DIRECTORY/bundle" cyberdeck
echo "$OUTPUT_DIRECTORY/$ARTIFACT"
