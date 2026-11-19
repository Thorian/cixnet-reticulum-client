"""Optional Windows UAC helper for a process-scoped, LAN-only pairing listener."""

import base64
import os
import sys


def allow_listener(host, port):
    """Ask Windows to allow this receiver until it exits; never open public IPs."""
    if sys.platform != "win32":
        return "Configure your LAN firewall for the displayed TCP port if needed."
    import ctypes

    # Host/port have already been validated by Pairing.invitation. Escape the
    # executable as a PowerShell literal, never interpolate user display names.
    program = sys.executable.replace("'", "''")
    rule = f"ciXnet-Pairing-{os.getpid()}-{port}"
    script = f"""
$ErrorActionPreference = 'Stop'
$ruleName = '{rule}'
try {{
  New-NetFirewallRule -Name $ruleName -DisplayName 'ciXnet phone pairing (temporary LAN)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {port} -LocalAddress '{host}' -RemoteAddress LocalSubnet -Program '{program}' -Profile Any | Out-Null
  try {{ [System.Diagnostics.Process]::GetProcessById({os.getpid()}).WaitForExit() }} catch {{ }}
}} finally {{
  Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        "powershell.exe",
        "-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand " + encoded,
        None,
        0,
    )
    if result <= 32:
        return "Firewall permission was declined; allow the displayed TCP port on your private LAN manually."
    return "Windows firewall permission requested. Approve the administrator prompt to allow the phone connection."
