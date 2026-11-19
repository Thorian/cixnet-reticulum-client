"""Validated LAN/TCP definitions for our private Reticulum configuration."""

import re

from RNS.vendor.configobj import ConfigObj


def validate_interfaces(interfaces):
    """Validate interface drafts before any network configuration is changed."""
    if not isinstance(interfaces, list) or len(interfaces) > 30:
        raise ValueError("Choose at most 30 interfaces")
    names = set()
    for item in interfaces:
        if not isinstance(item, dict) or item.get("type") not in (
            "AutoInterface",
            "TCPClientInterface",
            "RNodeInterface",
            "UDPInterface",
        ):
            raise ValueError("Unsupported interface type")
        name = item.get("name")
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 60
            or not re.fullmatch(r"[\w .-]+", name)
        ):
            raise ValueError(
                "Interface names may use letters, numbers, spaces, dots, hyphens, and underscores"
            )
        if name.casefold() in names:
            raise ValueError("Interface names must be unique")
        names.add(name.casefold())
        if "enabled" in item and type(item["enabled"]) is not bool:
            raise ValueError("Interface enabled must be true or false")
        if item["type"] == "TCPClientInterface" and item.get(
            "enabled", bool(item.get("host"))
        ):
            if not isinstance(item.get("host"), str) or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,253}", item["host"]
            ):
                raise ValueError("Enter a hostname or IP address without a URL scheme")
            if type(item.get("port")) is not int or not 1 <= item["port"] <= 65535:
                raise ValueError("TCP port must be 1–65535")


def definitions(local, interfaces):
    """Translate validated interface settings into Reticulum configuration entries."""
    validate_interfaces(interfaces)
    result = {}
    if local:
        result["Local network"] = {"type": "AutoInterface", "enabled": "Yes"}
    for item in interfaces:
        if item["type"] == "TCPClientInterface" and item.get(
            "enabled", bool(item.get("host"))
        ):
            result["ciXnet " + item["name"]] = {
                "type": "TCPClientInterface",
                "enabled": "Yes",
                "target_host": item["host"],
                "target_port": item["port"],
            }
    return result


def write_config(path, managed, test_listen=None, test_connect=None):
    """ConfigObj quotes values; never concatenate user input into config text."""
    config = ConfigObj(encoding="utf-8")
    config.filename = str(path.with_suffix(".tmp"))
    config["reticulum"] = {
        "enable_transport": "No",
        "share_instance": "No",
        "enable_interface_management": "Yes",
    }
    config["logging"] = {"loglevel": 3}
    config["interfaces"] = dict(managed)
    if test_listen:
        config["interfaces"]["Local test listener"] = {
            "type": "TCPServerInterface",
            "enabled": "Yes",
            "listen_ip": "127.0.0.1",
            "listen_port": test_listen,
        }
    if test_connect:
        config["interfaces"]["Local test connection"] = {
            "type": "TCPClientInterface",
            "enabled": "Yes",
            "target_host": "127.0.0.1",
            "target_port": test_connect,
        }
    config.write()
    path.with_suffix(".tmp").replace(path)
