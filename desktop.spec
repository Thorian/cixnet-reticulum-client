# Build on the target operating system; PyInstaller is not a cross compiler.
from pathlib import Path
import ssl
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
web_data, web_binaries, web_imports = collect_all("webview")
auth_data, auth_binaries, auth_imports = collect_all("fido2")
# Some Python distributions ship additional SSL trust-policy data beside ssl.py.
# Preserve it rather than disabling verification or relying on the build machine.
trust_policy = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
runtime_data = [(str(trust_policy), ".")] if trust_policy.exists() else []
analysis = Analysis(
    [str(root / "desktop.py")],
    pathex=[str(root)],
    binaries=web_binaries + auth_binaries,
    datas=web_data + auth_data + runtime_data + [(str(root / "ui"), "ui"), (str(root / "LICENSE"), ".")],
    hiddenimports=web_imports + auth_imports + ["server"] + collect_submodules("RNS.Interfaces")
        + collect_submodules("LXMF") + collect_submodules("retdns")
        + collect_submodules("nomadpl"),
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "cefpython3", "tkinter"],
    noarchive=False,
    # Reticulum discovers interface modules by globbing its package directory.
    # Keep those upstream source files alongside the frozen import archive.
    module_collection_mode={"RNS": "pyz+py", "LXMF": "pyz+py"},
)
pyz = PYZ(analysis.pure)
window = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="ciXnet", console=False, debug=False, upx=False,
)
receiver = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="ciXnet-service", console=True, debug=False, upx=False,
)
app = COLLECT(window, receiver, analysis.binaries, analysis.datas, name="ciXnet", upx=False)
