# Use a phone from the desktop

Pairing gives the desktop access to the phone's existing messages, attachments, contacts, browsing, bookmarks and DNS settings. The phone remains the receiver and stores the history.

## Connect

1. On the desktop, choose Pair with phone, or open Settings → Phone pairing.
2. Select the desktop's reachable LAN IPv4 address and create an invitation. Use the offered firewall allowance if required.
3. On the phone, open Phone pairing → On the phone and scan the desktop code.
4. Review the requesting computer, select unlocked identities and approve access.
5. Choose Open phone client on the desktop.

Invitations expire after five minutes and can be used once. The desktop shows a Using phone banner with Disconnect. Revoke a computer on the phone to remove its saved access. Disconnecting returns to the desktop's local identities and history.

## Access

Sessions use authenticated Reticulum Links and pinned device identities. The phone connects outward to the desktop's LAN listener; its HTTP API is not exposed on Wi-Fi. Messaging keys and the phone's API credential remain on the phone.

The paired interface can search and fetch old messages and attachments, send messages, manage contacts and use network pages. Identity creation/import/export, unlocking and protection changes stay on the phone. These restrictions are enforced by the receiver's API allowlist.

One active desktop per phone is the tested scope. The phone continues receiving if the desktop disconnects. Content already displayed on a computer can still be captured there; revoke prevents subsequent access.

## Transport and retries

Requests use bounded 48 KiB chunks with a 16 MiB envelope limit. Phone history is fetched on demand; the pairing service does not write a desktop copy of message history or attachments. Rendered content can remain in the webview's memory or browser storage.

Mutating requests have a durable per-device journal. Repeated completed request IDs return their saved response; altered or expired requests are rejected. If a crash leaves acceptance uncertain, the desktop asks you to check history instead of automatically sending again.

The preview has been tested with independent clients and Android emulators. Physical-device pairing and long battery tests remain on the test list.
