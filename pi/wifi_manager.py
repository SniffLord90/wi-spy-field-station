import re
import shutil
import subprocess
import time
from typing import Any

from config.settings import (
    WIFI_COMMAND_TIMEOUT_SECONDS,
    WIFI_INTERFACE,
    WIFI_SCAN_WAIT_SECONDS,
    WIFI_USE_SUDO,
)


class WifiManager:
    def __init__(self) -> None:
        self.interface = WIFI_INTERFACE
        self.use_sudo = WIFI_USE_SUDO
        self.timeout = WIFI_COMMAND_TIMEOUT_SECONDS
        self.scan_wait_seconds = WIFI_SCAN_WAIT_SECONDS

        self.wpa_cli_path = shutil.which("wpa_cli") or "/usr/sbin/wpa_cli"
        self.ip_path = shutil.which("ip") or "/usr/sbin/ip"
        self.sudo_path = shutil.which("sudo") or "/usr/bin/sudo"

    def _base_prefix(self) -> list[str]:
        if self.use_sudo:
            return [self.sudo_path, "-n"]
        return []

    def _run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = self._base_prefix() + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or self.timeout,
            check=check,
        )

    def _safe_run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int | None = None,
    ) -> tuple[bool, str, str]:
        try:
            proc = self._run(args, check=check, timeout=timeout)
            return True, (proc.stdout or "").strip(), (proc.stderr or "").strip()
        except FileNotFoundError as exc:
            return False, "", f"Commando niet gevonden: {exc}"
        except subprocess.CalledProcessError as exc:
            return (
                False,
                (exc.stdout or "").strip(),
                (exc.stderr or "").strip() or "Commando faalde",
            )
        except subprocess.TimeoutExpired:
            return False, "", "Timeout tijdens uitvoeren van wifi-commando"
        except Exception as exc:
            return False, "", f"Onverwachte fout: {exc}"

    def _wpa(self, *args: str, check: bool = True) -> tuple[bool, str, str]:
        return self._safe_run(
            [self.wpa_cli_path, "-i", self.interface, *args],
            check=check,
        )

    @staticmethod
    def _quote(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _parse_kv_block(text: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
        return result

    @staticmethod
    def _extract_first_ipv4(ip_output: str) -> str | None:
        match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)", ip_output)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _parse_security(flags: str) -> str:
        flags_upper = flags.upper()
        if "SAE" in flags_upper or "WPA3" in flags_upper:
            return "WPA3"
        if "WPA2" in flags_upper or "RSN" in flags_upper:
            return "WPA2"
        if "WPA-" in flags_upper or "WPA]" in flags_upper:
            return "WPA"
        if "WEP" in flags_upper:
            return "WEP"
        return "Open"

    @staticmethod
    def _signal_label(level: int) -> str:
        if level >= -55:
            return "Uitstekend"
        if level >= -67:
            return "Goed"
        if level >= -75:
            return "Redelijk"
        if level >= -85:
            return "Zwak"
        return "Erg zwak"

    def get_status(self) -> dict[str, Any]:
        try:
            ok, stdout, stderr = self._wpa("status")
            if not ok:
                return {
                    "ok": False,
                    "message": f"Kon wifi-status niet uitlezen: {stderr or stdout}",
                    "status": {
                        "interface": self.interface,
                        "connected": False,
                        "ssid": None,
                        "bssid": None,
                        "ip_address": None,
                        "wpa_state": None,
                        "key_mgmt": None,
                        "pairwise_cipher": None,
                        "group_cipher": None,
                    },
                }

            status = self._parse_kv_block(stdout)

            ok_ip, ip_stdout, ip_stderr = self._safe_run(
                [self.ip_path, "-4", "addr", "show", "dev", self.interface],
                check=False,
            )

            ipv4 = None
            if ok_ip and ip_stdout:
                ipv4 = self._extract_first_ipv4(ip_stdout)

            connected = status.get("wpa_state") == "COMPLETED" and bool(status.get("ssid"))

            return {
                "ok": True,
                "message": "WiFi-status opgehaald",
                "status": {
                    "interface": self.interface,
                    "connected": connected,
                    "ssid": status.get("ssid"),
                    "bssid": status.get("bssid"),
                    "ip_address": ipv4,
                    "wpa_state": status.get("wpa_state"),
                    "key_mgmt": status.get("key_mgmt"),
                    "pairwise_cipher": status.get("pairwise_cipher"),
                    "group_cipher": status.get("group_cipher"),
                    "ip_command_error": None if ok_ip else (ip_stderr or ip_stdout or None),
                },
            }
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Onverwachte fout in wifi-status: {exc}",
                "status": {
                    "interface": self.interface,
                    "connected": False,
                    "ssid": None,
                    "bssid": None,
                    "ip_address": None,
                    "wpa_state": None,
                    "key_mgmt": None,
                    "pairwise_cipher": None,
                    "group_cipher": None,
                },
            }

    def scan_networks(self) -> dict[str, Any]:
        try:
            ok, stdout, stderr = self._wpa("scan")
            if not ok:
                return {
                    "ok": False,
                    "message": f"Kon wifi-scan niet starten: {stderr or stdout}",
                    "networks": [],
                }

            time.sleep(self.scan_wait_seconds)

            ok, stdout, stderr = self._wpa("scan_results")
            if not ok:
                return {
                    "ok": False,
                    "message": f"Kon scanresultaten niet ophalen: {stderr or stdout}",
                    "networks": [],
                }

            lines = [line for line in stdout.splitlines() if line.strip()]
            if len(lines) <= 1:
                return {
                    "ok": True,
                    "message": "Geen zichtbare netwerken gevonden",
                    "networks": [],
                }

            dedup: dict[str, dict[str, Any]] = {}

            for line in lines[1:]:
                parts = line.split("\t")
                if len(parts) < 5:
                    continue

                bssid, freq, signal, flags, ssid = parts[0], parts[1], parts[2], parts[3], parts[4]
                ssid = ssid.strip()

                if not ssid:
                    continue

                try:
                    signal_dbm = int(float(signal))
                except ValueError:
                    signal_dbm = -999

                network = {
                    "ssid": ssid,
                    "bssid": bssid,
                    "frequency_mhz": int(freq) if freq.isdigit() else None,
                    "signal_dbm": signal_dbm,
                    "signal_label": self._signal_label(signal_dbm),
                    "flags": flags,
                    "security": self._parse_security(flags),
                    "open": self._parse_security(flags) == "Open",
                }

                existing = dedup.get(ssid)
                if existing is None or network["signal_dbm"] > existing["signal_dbm"]:
                    dedup[ssid] = network

            networks = sorted(
                dedup.values(),
                key=lambda item: (item["signal_dbm"], item["ssid"].lower()),
                reverse=True,
            )

            return {
                "ok": True,
                "message": f"{len(networks)} netwerk(en) gevonden",
                "networks": networks,
            }
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Onverwachte fout tijdens wifi-scan: {exc}",
                "networks": [],
            }

    def connect(self, ssid: str, password: str = "") -> dict[str, Any]:
        try:
            ssid = (ssid or "").strip()
            if not ssid:
                return {
                    "ok": False,
                    "message": "SSID ontbreekt",
                }

            ok, stdout, stderr = self._wpa("add_network")
            if not ok:
                return {
                    "ok": False,
                    "message": f"Kon netwerkprofiel niet aanmaken: {stderr or stdout}",
                }

            network_id = stdout.strip().splitlines()[-1].strip()
            if not network_id.isdigit():
                return {
                    "ok": False,
                    "message": f"Ongeldig netwerk-id ontvangen: {network_id}",
                }

            ssid_set = self._wpa("set_network", network_id, "ssid", self._quote(ssid))
            if not ssid_set[0]:
                return {
                    "ok": False,
                    "message": f"Kon SSID niet instellen: {ssid_set[2] or ssid_set[1]}",
                }

            if password:
                psk_set = self._wpa("set_network", network_id, "psk", self._quote(password))
                if not psk_set[0]:
                    return {
                        "ok": False,
                        "message": f"Kon wachtwoord niet instellen: {psk_set[2] or psk_set[1]}",
                    }
            else:
                open_set = self._wpa("set_network", network_id, "key_mgmt", "NONE")
                if not open_set[0]:
                    return {
                        "ok": False,
                        "message": f"Kon open netwerk niet instellen: {open_set[2] or open_set[1]}",
                    }

            optional_commands = [
                ("set_network", network_id, "scan_ssid", "1"),
                ("enable_network", network_id),
                ("select_network", network_id),
                ("save_config",),
                ("reconfigure",),
            ]

            for command in optional_commands:
                ok, cmd_stdout, cmd_stderr = self._wpa(*command, check=False)
                if not ok and command[0] in {"enable_network", "select_network"}:
                    return {
                        "ok": False,
                        "message": f"Kon netwerk niet activeren: {cmd_stderr or cmd_stdout}",
                    }

            deadline = time.time() + 20
            while time.time() < deadline:
                status = self.get_status()
                if status.get("ok") and status.get("status", {}).get("ssid") == ssid:
                    if status["status"].get("connected"):
                        return {
                            "ok": True,
                            "message": f"Verbonden met {ssid}",
                            "status": status["status"],
                        }
                time.sleep(1)

            final_status = self.get_status()
            return {
                "ok": False,
                "message": f"Verbinding met {ssid} niet bevestigd binnen timeout",
                "status": final_status.get("status", {}),
            }
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Onverwachte fout tijdens verbinden: {exc}",
                "status": {},
            }

    def disconnect(self) -> dict[str, Any]:
        try:
            ok, stdout, stderr = self._wpa("disconnect", check=False)
            if not ok:
                return {
                    "ok": False,
                    "message": f"Kon wifi niet verbreken: {stderr or stdout}",
                }

            status = self.get_status()
            return {
                "ok": True,
                "message": "WiFi-verbinding verbroken",
                "status": status.get("status", {}),
            }
        except Exception as exc:
            return {
                "ok": False,
                "message": f"Onverwachte fout tijdens verbreken: {exc}",
                "status": {},
            }