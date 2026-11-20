# Third-party components

## Desktop package

The source preview loads the external libraries described below. The portable desktop package bundles Python, Reticulum, LXMF, retdns, NomadPL and the desktop runtime dependencies instead. Its licenses directory retains installed license files; Reticulum/LXMF notices are additionally present under _internal/ui/licenses. Dependency versions are recorded in dependency-versions.json. Those components retain their own licenses.

pywebview 6.2.1 supplies the desktop window under its MIT license. Windows uses the separately installed Microsoft Edge WebView2 runtime and pythonnet/CLR loader; Linux selects GTK/WebKitGTK. The package includes pywebview's upstream WebView2 DLL notices and other discovered dependency licenses. PyInstaller 6.22.3 is a build tool under GPL with its bootloader distribution exception; its complete license is retained in the package. Neither pywebview nor the original ciXnet desktop launcher introduces a license fee. Platform runtimes retain their own terms. This does not change Reticulum's license restrictions.

Source runs import Reticulum from the active Python environment or an explicitly selected checkout. Native packages bundle it and preserve its license. Reticulum 1.6.1 is distributed under the custom Reticulum License, copyright 2016–2026 Mark Qvist. It includes restrictions on purposeful harm and AI/model-training dataset uses. Its license must be preserved when distributing Reticulum with the client. The MIT license here applies only to original ciXnet code/artwork, not Reticulum or other dependencies.

LXMF 1.3.0 is imported from the active environment; --lxmf-path can select a source checkout. Its custom Reticulum License, copyright 2020–2025 Mark Qvist, has the same purposeful-harm and AI/model-training restrictions as the Reticulum license inspected above. Native packages bundle LXMF and preserve its license.

Python and the installed Reticulum dependencies retain their own licenses. Android packages use Chaquopy as described below. NomadNet protocol and Micron documentation/source were consulted for interoperability. The browser and renderer are independently implemented here; no NomadNet application code is bundled. Native build scripts collect dependency licenses and a version inventory.

## Material Design Icons

Bundled @mdi/font assets and the icon-name/codepoint catalog come from Pictogrammers/Templarian MaterialDesign-Webfont, version 7.4.47: https://github.com/Templarian/MaterialDesign-Webfont/tree/v7.4.47 . The font is Apache-2.0 licensed. Original upstream license and full Apache license text are retained in ui/vendor/mdi/LICENSE and ui/vendor/mdi/APACHE-2.0.txt. The catalog was extracted from the upstream CSS; the original CSS is retained alongside it. These third-party assets are not authored by ciXnet and do not become MIT-licensed merely by inclusion.

Sideband's public source was consulted to identify the existing LXMF appearance data layout for interoperability: icon name plus foreground and background RGB bytes. No Sideband UI, avatar-picker implementation, or font bundle was copied. ciXnet uses its own picker/validation/rendering code and obtains the font directly from its upstream distribution.

## Additional notices and tools

The About page links official projects and includes offline notices under ui/licenses for Python, cryptography, CFFI, pycparser, Reticulum, LXMF, MDI, and ciXnet. SQLite/OpenSSL references are provided. Native packaging requires checking the complete bundled dependency set again.

Prettier 3.6.2, esbuild 0.25.12, and Ruff 0.17.4 are MIT-licensed development tools. The unminified generated browser bundle and source map are included alongside original module sources.

## retdns and NomadPL

The retdns and NomadPL libraries (pinned Git revisions in requirements.txt) are integrated via their Python APIs. Both are MIT-licensed, copyright 2026 their respective contributors. Their license texts are preserved in ui/licenses/retdns-MIT.txt and ui/licenses/nomadpl-MIT.txt. Source runs import them as dependencies; native packages bundle them with these notices. Reticulum retains its separate license.


## Identity protection and camera review

Windows desktop identity locks use Yubico python-fido2 2.2.1 (BSD, with included Apache 2.0 and MPL 2.0 notices) and Windows Hello. Fingerprint, face or PIN depends on the device. Enable protection in Settings; use Lock identity or switch identities to lock. Protected identities start locked after restarting. Reception and relay synchronization continue while locked. Saved identity keys and message files remain unencrypted on disk. Back up identity keys before enabling protection: loss of the Windows Hello credential prevents this interface from unlocking. Android biometric support remains unfinished in the Android testing preview.

Camera capture now offers review, Retake and Use photo. Use photo attaches to the draft; existing size reduction and Send remain separate. Closing capture releases the camera.


Android preview: Chaquopy 17.2.0 (MIT) embeds CPython 3.12 (PSF license) and uses Android System WebView supplied by the device. Android SDK, Android Gradle Plugin 8.7.3 and Gradle 8.9 are build tools. Reticulum uses its supported internal crypto provider in this preview; no older PyCA Android wheel is bundled. Upstream signal-handler registration is guarded in Android build copies because service shutdown is owned by Android; original upstream source folders remain unchanged.

The Android preview includes pySerial 3.5 (BSD); its original notice is retained at ui/licenses/pyserial-LICENSE.txt.

## Offline phone pairing QR codes

qrcode-generator 1.4.4 by Kazuhiko Arase (MIT), vendored as ui/vendor/qrcode.cjs, original notice at ui/licenses/qrcode-generator-LICENSE.txt. Source: https://github.com/kazuhikoarase/qrcode-generator

jsQR 1.4.0 (Apache 2.0), vendored as ui/vendor/jsqr.cjs, original notice at ui/licenses/jsqr-LICENSE.txt. Source: https://github.com/cozmo/jsQR

Pairing transport reuses the bundled Reticulum Link implementation; no new cryptographic primitive or messaging identity export is introduced.
