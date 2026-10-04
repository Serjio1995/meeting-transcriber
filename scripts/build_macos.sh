#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python scripts/make_icons.py
pip install -r requirements.txt -r requirements-dev.txt

pyinstaller packaging/transcriber.spec --noconfirm --clean

APP="dist/Meeting Transcriber.app"
codesign --force --deep --sign - "$APP"

rm -rf dist/dmg && mkdir -p dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "Meeting Transcriber" \
    -srcfolder dist/dmg -ov -format UDZO \
    dist/MeetingTranscriber-macOS.dmg

echo ""
echo "Готово: dist/MeetingTranscriber-macOS.dmg"