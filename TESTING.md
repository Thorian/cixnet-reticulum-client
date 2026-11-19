# Testing

The automated suite covers message persistence, identity edits, attachments, delivery receipts, propagation mailboxes, page browsing, name resolution, pairing, API boundaries and saved stations. Frontend tests cover rendering, navigation, camera cleanup, QR codes and one-shot location cleanup.

Run these from a fresh Python 3.12 environment:

```text
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
npm ci
npm test
npm run build
```

Python integration tests start independent receivers on temporary loopback ports. Fixture pages are included under tests/fixtures. Local adapters are used by the pairing test; that test skips if none is available. Windows Hello cryptographic tests require python-fido2 and native prompts require a Windows device.

Use ANDROID.md for phone checks and DESKTOP.md for packaged receiver checks. GitHub Actions runs automated tests on Windows and Linux. It does not establish radio coverage, phone battery endurance or public gateway availability.
