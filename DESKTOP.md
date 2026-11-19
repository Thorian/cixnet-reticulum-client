# ciXnet desktop preview

Run ciXnet.exe on Windows, or ciXnet on Linux. Keep the entire portable folder together. Python is included in a packaged build. Windows requires the Microsoft Edge WebView2 runtime; Linux uses GTK and WebKitGTK 4.1. No installer, automatic updates, or code signing is included yet.

If another Reticulum instance already occupies the Windows LAN discovery port, the launcher retries once with LAN discovery disabled for that session. Saved discovery preferences remain unchanged; TCP connections remain available. The client shows LAN unavailable and explains how to restore it after closing the conflicting instance and restarting. Other startup failures are not silently retried.

The receiver runs in a separate supervised process. Minimize the window to continue receiving. Quitting closes the receiver cleanly; reception resumes next time you open ciXnet. There is no tray mode or Android service in this desktop preview.

Data lives in %LOCALAPPDATA%/ciXnet on Windows, or $XDG_DATA_HOME/cixnet (normally ~/.local/share/cixnet) on Linux. The app does not import or overwrite development-preview identities automatically. Use identity export/import to transfer a key; this does not transfer chat history. --data PATH selects a separate profile folder. Only one desktop instance can use a folder at a time.

Keys and message history are still unencrypted at rest. The app uses a token-protected loopback API and separate origins for NomadPL pages. It exposes no custom Python bridge to page scripts. Logs rotate at 2 MiB with two backups; receiver.log is in the data folder. Desktop browser state stays in its webview subdirectory.

The receiver normally reuses its last local port to preserve browser preferences; if another process occupies it, a new loopback port is allocated. Conversation history, DNS configuration and bookmarks remain in their databases independently of this port.

## Build from source

Use Python 3.12 in an isolated environment. Install desktop-requirements.txt; it includes the pinned companion dependencies. On Linux also install python3-gi, python3-gi-cairo, gir1.2-gtk-3.0 and gir1.2-webkit2-4.1, and make the system GI bindings available to the environment. Build on each target operating system:

    python build_desktop.py --dist /path/to/output --work /path/to/build-cache

Run python desktop.py for source development. --smoke-test starts and checks the receiver without opening a window, then shuts it down. Use --data PATH --no-local for an isolated test.

Packaging keeps the existing application UI and Python services; it is not a rewrite of either. Windows and Linux build instructions share the same entry point and spec. Linux needs an actual Linux build and GUI verification before release. Android uses a separate foreground receiver; see ANDROID.md.

licenses/ retains discovered dependency license files, and dependency-versions.json records the build environment. SHA256SUMS.json lists built-file hashes. The ciXnet MIT license covers original code only; dependency licenses remain separate. See THIRD_PARTY_NOTICES.md and the application's About page.


## Identity protection and camera review

Windows desktop identity locks use Yubico python-fido2 2.2.1 (BSD, with included Apache 2.0 and MPL 2.0 notices) and Windows Hello. Fingerprint, face or PIN depends on the device. Enable protection in Settings; use Lock identity or switch identities to lock. Protected identities start locked after restarting. Reception and relay synchronization continue while locked. Saved identity keys and message files remain unencrypted on disk. Back up identity keys before enabling protection: loss of the Windows Hello credential prevents this interface from unlocking. Android biometric support is unfinished.

Camera capture now offers review, Retake and Use photo. Use photo attaches to the draft; existing size reduction and Send remain separate. Closing capture releases the camera.
