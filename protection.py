"""Optional identity-interface locks. Receiving does not depend on UI unlocks.

Windows Hello holds the private authentication credential. We retain only its
public key and require a verified, fresh FIDO2 assertion to open an identity.
This protects the running interface, not files against an OS administrator.
"""

import base64
import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path


class IdentityProtection:
    def __init__(self, directory):
        self.path = Path(directory) / "identity-protection.json"
        self.records = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else {}
        )
        self.unlocked = set()
        self.jobs = {}
        self.lock = threading.RLock()
        self.epochs = {}

    @staticmethod
    def available():
        if sys.platform != "win32":
            return False
        try:
            from fido2.client.windows import WindowsClient

            return WindowsClient.is_available()
        except (ImportError, OSError):
            return False

    def status(self, owner):
        with self.lock:
            protected = owner in self.records
            return dict(
                protected=protected,
                locked=protected and owner not in self.unlocked,
                available=self.available(),
            )

    def require_unlocked(self, owner):
        with self.lock:
            if owner in self.records and owner not in self.unlocked:
                raise ValueError("Unlock this identity with Windows Hello first")

    def close(self, owner):
        with self.lock:
            self.unlocked.discard(owner)
            self.epochs[owner] = self.epochs.get(owner, 0) + 1
            for job in self.jobs.values():
                if job["owner"] == owner and job["state"] == "pending":
                    job["cancel"].set()

    def begin(self, profile, action):
        owner = profile["id"]
        if action not in ("enable", "unlock", "disable"):
            raise ValueError("Unknown identity protection action")
        if not self.available():
            raise ValueError("Windows Hello is unavailable in this client")
        with self.lock:
            if any(job["state"] == "pending" for job in self.jobs.values()):
                raise ValueError("Finish the current Windows Hello prompt first")
            if action == "enable" and owner in self.records:
                raise ValueError("Identity protection is already enabled")
            if action != "enable" and owner not in self.records:
                raise ValueError("Identity protection is not enabled")
            if action == "disable":
                self.require_unlocked(owner)
            self.jobs = {
                key: job
                for key, job in self.jobs.items()
                if time.monotonic() - job["created"] < 180
            }
            ident = secrets.token_urlsafe(24)
            job = dict(
                owner=owner,
                state="pending",
                error="",
                created=time.monotonic(),
                cancel=threading.Event(),
            )
            self.jobs[ident] = job
            epoch = self.epochs.get(owner, 0)
            threading.Thread(
                target=self._verify, args=(profile, action, job, epoch), daemon=True
            ).start()
            return {"job": ident}

    def result(self, owner, ident):
        with self.lock:
            job = self.jobs.get(ident)
            if not job or job["owner"] != owner:
                raise ValueError("Authentication request not found")
            return {"state": job["state"], "error": job["error"], **self.status(owner)}

    def _save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.records, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def _verify(self, profile, action, job, epoch):
        try:
            from fido2.client import DefaultClientDataCollector
            from fido2.client.windows import WindowsClient
            from fido2.server import Fido2Server
            from fido2.webauthn import AttestedCredentialData

            owner = profile["id"]
            server = Fido2Server(
                {"id": "localhost", "name": "ciXnet identity protection"}
            )
            client = WindowsClient(DefaultClientDataCollector("http://localhost"))
            if action == "enable":
                options, state = server.register_begin(
                    {
                        "id": bytes.fromhex(owner),
                        "name": profile["nickname"],
                        "displayName": profile["nickname"],
                    },
                    user_verification="required",
                    authenticator_attachment="platform",
                    resident_key_requirement="discouraged",
                )
                response = client.make_credential(
                    options.public_key, event=job["cancel"]
                )
                credential = server.register_complete(state, response).credential_data
                if credential is None:
                    raise ValueError("Windows Hello did not return a credential")
            else:
                with self.lock:
                    credential = AttestedCredentialData(
                        base64.b64decode(self.records[owner], validate=True)
                    )
                options, state = server.authenticate_begin(
                    [credential], user_verification="required"
                )
                response = client.get_assertion(
                    options.public_key, event=job["cancel"]
                ).get_response(0)
                server.authenticate_complete(state, [credential], response)
            with self.lock:
                if job["cancel"].is_set() or self.epochs.get(owner, 0) != epoch:
                    raise ValueError(
                        "Identity was locked while verification was pending"
                    )
                previous = dict(self.records)
                if action == "enable":
                    self.records[owner] = base64.b64encode(bytes(credential)).decode()
                elif action == "disable":
                    self.records.pop(owner, None)
                try:
                    self._save()
                except Exception:
                    self.records = previous
                    raise
                self.unlocked.add(owner)
                job["state"] = "complete"
        except Exception:
            with self.lock:
                job["state"] = "failed"
                job["error"] = (
                    "Windows Hello verification was cancelled or failed. No protection settings were changed."
                )
