# Preparing a release

1. Run the checks in DEVELOPMENT.md from a fresh environment.
2. Update the changelog, preview version and platform test notes.
3. Build Windows on Windows. Build Android with the documented SDK/JDK/Gradle versions. Check upgrades with the existing signing key and app identifier.
4. Test message delivery in both directions, restart persistence, phone notifications and reconnecting after a network change.
5. Review the user guide, screenshots and dependency notices against the actual packages.
6. Publish source through Git. Attach packaged binaries and checksums to a GitHub release, not the source tree. Keep the Android download filename ciXnet-debug.apk during the preview.

Signing keys, profiles, runtime databases, logs, generated Android sources, build caches and development configuration do not belong in the repository. Preserve the existing Android signing key privately; regenerating it prevents normal updates to installed previews.

The source export does not create a GitHub repository, push commits or publish binaries. Choose the repository name and visibility before that step. No release upload is automated.

Keep earlier releases unchanged.
