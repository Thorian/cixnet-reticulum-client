# External browser bridge

Open a NomadPL HTML page in Browse, then use the external-browser arrow beside
the address bar. ciXnet asks the operating system to open its default browser;
choose Chrome as your default if desired. Native Micron pages remain in ciXnet.

A name such as `nomadpl://home.cix/` becomes
`http://home.cix.localhost:<port>/`. Literal destination hashes also work.
This is a loopback HTTP gateway: no VPN, public DNS, hosts-file edits, or public
listening port. The ciXnet receiver must remain running, with the identity unlocked.
Saved anonymous gateway ports are reused where available, so browser bookmarks
can work across restarts. Another program occupying the port forces a new port.

Identified sites use an additional random hostname component to isolate their
identity capability from other local applications. These names last for the
receiver session. Closing/locking the identity revokes existing gateway requests.
Relative resources and forms use the same origin; pages receive their original
HTML, without the embedded client's navigation script.

The browser bridge does not make a remote page trustworthy. Ordinary browser
site isolation applies, and an external browser's cookies/history are its own.
Android browser support for `.localhost` names must be checked on a real device.
