#!/bin/bash
set -e

APP_NAME="CodePop"
BUNDLE_ID="cn.codepop.macos"
VERSION="0.2.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/.build/release"
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
DMG_PATH="$BUILD_DIR/$APP_NAME-$VERSION-arm64.dmg"

echo "[1/5] Building Swift executable..."
cd "$PROJECT_DIR"
swift build -c release

BINARY_PATH="$BUILD_DIR/$APP_NAME"
if [ ! -f "$BINARY_PATH" ]; then
    echo "Error: binary not found at $BINARY_PATH"
    exit 1
fi

echo "[2/5] Creating .app bundle..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"
cp "$BINARY_PATH" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
chmod +x "$APP_BUNDLE/Contents/MacOS/$APP_NAME"

cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$BUNDLE_ID</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
</dict>
</plist>
EOF

echo "[3/5] Copying resources..."
ICON_SRC="$PROJECT_DIR/../macos/release/mac-arm64/CodePop.app/Contents/Resources/icon.icns"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
else
    echo "Warning: icon.icns not found, app will use default icon"
fi

echo "[4/5] Signing app bundle..."
codesign --force --deep --sign - "$APP_BUNDLE"

echo "[5/5] Creating DMG with Applications alias..."
rm -f "$DMG_PATH"
TMP_DMG_DIR=$(mktemp -d)
cp -R "$APP_BUNDLE" "$TMP_DMG_DIR/"
ln -s /Applications "$TMP_DMG_DIR/Applications"

# Create a writable DMG first, then convert to compressed
TMP_DMG="$BUILD_DIR/tmp-$APP_NAME.dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$TMP_DMG_DIR" -ov -format UDRW "$TMP_DMG"
rm -rf "$TMP_DMG_DIR"

# Mount and set Finder layout
MOUNT_DIR=$(hdiutil attach "$TMP_DMG" | grep "/Volumes/" | tail -1 | awk '{for(i=3;i<=NF;i++) printf "%s ", $i; print ""}' | sed 's/ *$//')

if [ -n "$MOUNT_DIR" ]; then
    echo "Setting DMG layout on $MOUNT_DIR ..."
    osascript <<APPLESCRIPT > /dev/null 2>&1 || true
    tell application "Finder"
        tell disk "$APP_NAME"
            open
            set current view of container window to icon view
            set toolbar visible of container window to false
            set statusbar visible of container window to false
            set the bounds of container window to {400, 100, 850, 360}
            set theViewOptions to icon view options of container window
            set arrangement of theViewOptions to not arranged
            set icon size of theViewOptions to 72
            set text size of theViewOptions to 12
            try
                set position of item "$APP_NAME.app" of container window to {120, 100}
                set position of item "Applications" of container window to {360, 100}
            end try
            update without registering applications
            delay 2
            close
        end tell
    end tell
APPLESCRIPT
    sleep 2
    hdiutil detach "$MOUNT_DIR" -force || true
    sleep 1
fi

# Convert to compressed read-only DMG
hdiutil convert "$TMP_DMG" -format UDZO -o "$DMG_PATH"
rm -f "$TMP_DMG"

echo "Done!"
echo "App: $APP_BUNDLE"
echo "DMG: $DMG_PATH"
