# Android preview

Install `ciXnet-debug.apk` from the release files on Android 8 or later. This debug build
contains arm64-v8a and x86_64 code. Allow installation from the app used to open
the APK. It is a development preview signed with a development key, not a store
release. Back up identities before replacing an existing installation.

The native foreground receiver runs in a separate process from Android System
WebView. It receives through standard Reticulum/LXMF. Its persistent notification
includes Stop; reopening ciXnet starts it again. Android 13+ asks permission for
message alerts. Denying alerts must not disable receiving or saving messages.
Message notifications contain no message body or attachment names.

The local API requires a random app-private key on Android. There is no VPN or
cloud push dependency. The external browser bridge uses loopback `.localhost`
addresses. The app uses Chaquopy 17.2 and Python 3.12; licenses are in About.

## Phone checks

- Exchange messages in both directions; verify notifications with the screen off.
- Close the interface, reopen it, and confirm history and receiving persist.
- Disconnect/reconnect Wi-Fi; verify queued messages eventually arrive.
- Deny/grant notification permission and check reception continues either way.
- Try taking, reviewing, reducing, attaching and sending a photo.
- Open a NomadPL page in Chrome through the external-browser arrow.
- Test long idle periods with your phone's actual battery settings.

The receiver uses wake and multicast locks; this costs battery. Manufacturer
battery restrictions and Doze can delay networking. Force-stop stops reception
until the app is opened again. This version does not automatically start at boot.
Android fingerprint unlocking is not implemented yet. Identity/message storage
is not encrypted by ciXnet. File export/download behavior and the camera still
need real-phone verification; emulator transport tests do not establish these.

## Building and testing

Use Python 3.12, JDK 17, Android SDK 35 and Gradle 8.9. Install requirements.txt first, then supply your tool paths:

```text
python build_android.py --sdk /path/to/android-sdk --jdk /path/to/jdk-17 --gradle /path/to/gradle-8.9/bin/gradle
```

On Windows, use gradle.bat. Android Gradle Plugin 8.7.3 and Chaquopy 17.2.0 are pinned. The builder stages installed dependencies and their licenses, then writes ciXnet-debug.apk under cixnet-android/ beside this source folder. Use --stage-only to check inputs without compiling. Checkout overrides --reticulum, --lxmf, --retdns and --nomadpl each take a directory containing the Python package.

Keep the generated debug signing key privately when updating installed previews. Generated dependencies, build caches and keystores are excluded from the source repository.

tests/android_smoke.py uses an explicitly selected emulator and disposable data. A successful build is separate from the phone checks above.

The background receiver uses a separate, low-priority service notification with launcher badges disabled. Its status says “Receiver running · waiting for messages”. Incoming message alerts use their own channel and may show a launcher badge.

Incoming messages now request the system-default vibration with the VIBRATE permission. Android retains settings for channels already created: on an existing installation, long-press a real message notification and open Incoming messages settings to enable vibration if desired. Silent mode, Do Not Disturb and user channel settings still apply. The new receiver-status-v2 channel disables badges for service status on upgraded installations too.

Station location: Use my location requests foreground coarse/fine location only on demand through the trusted local WebView origin. Remote NomadPL origins are refused. A one-fix location watch stops on completion, dialog close or hiding the app; no background location permission is requested. Manual coordinate entry remains available.
