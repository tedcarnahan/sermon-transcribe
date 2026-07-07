#!/usr/bin/env bash
#
# build.sh - Build the standalone Sermon Transcriber macOS .app bundle
#
# Usage:
#   ./build.sh
#
# Requires: uv (https://astral.sh/uv)
# The built app will be at dist/Sermon Transcriber.app
#

set -euo pipefail

APP_NAME="Sermon Transcriber"
DIST_DIR="dist"
BUILD_DIR="build"

echo "==> Building ${APP_NAME} standalone app"

# Ensure uv is available
if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required but not found in PATH."
    echo "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Install/sync dev dependencies (PyInstaller is in [project.optional-dependencies].dev)
echo "==> Syncing dependencies (dev extras for PyInstaller)"
uv sync --extra dev

# Clean previous build artifacts
echo "==> Cleaning ${BUILD_DIR}/ and ${DIST_DIR}/"
rm -rf "${BUILD_DIR}" "${DIST_DIR}"

# Build using the project spec
echo "==> Running PyInstaller (this may take a minute)"
uv run --extra dev pyinstaller pyinstaller.spec --clean --noconfirm

# Verify output
if [[ -d "${DIST_DIR}/${APP_NAME}.app" ]]; then
    echo ""
    echo "✅ Build complete!"
    echo "   Output: ${DIST_DIR}/${APP_NAME}.app"
    echo "   To install: open ${DIST_DIR}/ && drag 'Sermon Transcriber.app' to /Applications"
    echo ""
else
    echo "⚠️  Expected app bundle not found. Check the output above and ${DIST_DIR}/"
    exit 1
fi
