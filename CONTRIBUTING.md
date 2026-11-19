# Contributing

Describe the problem or intended behaviour before proposing a large change. For bugs, include your platform, build, steps to reproduce and what happened. Remove keys, pairing invitations and private messages from reports.

Use Python 3.12 and the pinned requirements. Run the Python tests, npm test and npm run build before submitting a change. Format Python with Ruff and frontend sources with Prettier. Edit the source modules, then rebuild ui/dist; do not hand-edit the bundle.

Keep Reticulum/LXMF compatibility, offline operation and background reception in mind. Tests should use disposable identities and local connections. Do not make tests depend on public gateways or real user messages.

Comments should explain constraints or decisions that are hard to see from the code. Keep UI labels and documentation plain and specific.

Original contributions use this repository's MIT license. Preserve notices for third-party code and assets.
