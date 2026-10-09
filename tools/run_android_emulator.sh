#!/usr/bin/env bash
# Uses the official Android SDK directly, without a third-party GitHub Action.
set -euo pipefail
test "${GITHUB_ACTIONS:-}" = true
case "${MONITOR_API:-}" in 30|35) ;; *) echo 'Expected the Android 11/15 CI matrix'; exit 1 ;; esac
sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}}"
sdk_manager="$sdk_root/cmdline-tools/latest/bin/sdkmanager"
avd_manager="$sdk_root/cmdline-tools/latest/bin/avdmanager"
export PATH="$sdk_root/platform-tools:$PATH"
export ANDROID_SERIAL=emulator-5554
export ANDROID_AVD_HOME="$RUNNER_TEMP/watch2notif-ci-avd"
mkdir -p "$ANDROID_AVD_HOME"
image="system-images;android-$MONITOR_API;google_apis;x86_64"
"$sdk_manager" --sdk_root="$sdk_root" emulator platform-tools "$image"
printf 'no\n' | "$avd_manager" create avd --force --name watch2notif_ci --package "$image" --device pixel_2
test -f "$ANDROID_AVD_HOME/watch2notif_ci.ini"
mkdir -p android/build
log="android/build/emulator-api-$MONITOR_API.log"
"$sdk_root/emulator/emulator" -avd watch2notif_ci -port 5554 -no-window -no-snapshot \
  -noaudio -no-boot-anim -gpu swiftshader_indirect -camera-back none -memory 2048 -cores 2 > "$log" 2>&1 &
emulator_pid=$!
trap 'adb emu kill >/dev/null 2>&1 || true; kill "$emulator_pid" >/dev/null 2>&1 || true' EXIT
deadline=$((SECONDS + 240))
while ! adb get-state >/dev/null 2>&1; do
  if ! kill -0 "$emulator_pid" 2>/dev/null || ((SECONDS >= deadline)); then tail -n 60 "$log"; exit 1; fi
  sleep 2
done
deadline=$((SECONDS + 300))
while [[ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != 1 ]]; do
  if ! kill -0 "$emulator_pid" 2>/dev/null || ((SECONDS >= deadline)); then tail -n 60 "$log"; exit 1; fi
  sleep 2
done
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0
python3 tools/android_background_smoke.py
