"""Тесты модели данных и импорта (без GUI)."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from kerio_vpn_gui.core import (
    Profile,
    ProfileStore,
    format_duration,
    normalize_fingerprint,
    parse_server,
    scan_directory,
    xor_decode,
    xor_encode,
)

SAMPLE = """<config>
  <connections>
    <connection type="persistent">
      <server>vpn.example.com</server>
      <port>4090</port>
      <username>testuser</username>
      <password>XOR:213026217825342626223a2731</password>
      <fingerprint>00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff</fingerprint>
      <active>1</active>
    </connection>
  </connections>
</config>
"""


class CoreTests(unittest.TestCase):
    def test_xor_known_value(self) -> None:
        self.assertEqual(xor_encode("test-password"), "213026217825342626223a2731")
        self.assertEqual(xor_decode("XOR:213026217825342626223a2731"), "test-password")

    def test_xor_roundtrip_utf8(self) -> None:
        password = "Пароль-123"
        self.assertEqual(xor_decode(xor_encode(password)), password)

    def test_normalize_fingerprint(self) -> None:
        self.assertEqual(
            normalize_fingerprint("00112233445566778899aabbccddeeff"),
            "00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF",
        )
        self.assertEqual(
            normalize_fingerprint("00-11-22-33-44-55-66-77-88-99-aa-bb-cc-dd-ee-ff"),
            "00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF",
        )
        self.assertEqual(
            normalize_fingerprint(
                "md5 Fingerprint=00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF"
            ),
            "00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF",
        )
        with self.assertRaises(ValueError):
            normalize_fingerprint("00:11")

    def test_parse_server(self) -> None:
        self.assertEqual(parse_server("vpn.example.com"), ("vpn.example.com", 4090))
        self.assertEqual(parse_server("1.2.3.4:443"), ("1.2.3.4", 443))
        self.assertEqual(
            parse_server("https://vpn.example.com/"), ("vpn.example.com", 4090)
        )
        self.assertEqual(parse_server("[2001:db8::1]:4091"), ("2001:db8::1", 4091))
        with self.assertRaises(ValueError):
            parse_server("   ")

    def test_parse_and_serialize(self) -> None:
        profile = Profile.from_kerio_xml(SAMPLE, name="office", mac_fix=True)
        self.assertEqual(profile.server, "vpn.example.com")
        self.assertEqual(profile.port, 4090)
        self.assertEqual(profile.username, "testuser")
        self.assertEqual(profile.password, "test-password")
        self.assertEqual(
            profile.fingerprint,
            "00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF",
        )
        self.assertTrue(profile.mac_fix)
        xml = profile.to_kerio_xml()
        again = Profile.from_kerio_xml(xml, name="copy")
        self.assertEqual(again.password, profile.password)
        self.assertEqual(again.fingerprint, profile.fingerprint)
        self.assertEqual(again.server, profile.server)

    def test_format_duration(self) -> None:
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3665), "01:01:05")
        self.assertEqual(format_duration(None), "")

    def test_store_roundtrip_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config" / "profiles.json"
            store = ProfileStore(path)
            profile = Profile.from_kerio_xml(SAMPLE, name="alpha")
            store.add(profile)
            store.settings["connect_timeout_sec"] = 45
            store.save()
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            loaded = ProfileStore(path)
            self.assertEqual(len(loaded.profiles), 1)
            self.assertEqual(loaded.profiles[0].name, "alpha")
            self.assertEqual(loaded.profiles[0].password, "test-password")
            self.assertEqual(loaded.settings["connect_timeout_sec"], 45)

    def test_unique_name_and_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(Path(temporary) / "profiles.json")
            first = Profile.from_kerio_xml(SAMPLE, name="alpha")
            store.add(first)
            self.assertEqual(store.unique_name("alpha"), "alpha (2)")
            self.assertTrue(store.is_duplicate(first.clone("other")))
            self.assertIs(store.find_matching("vpn.example.com", 4090, "TESTUSER"), first)

    def test_scan_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "office.conf").write_text(SAMPLE, encoding="utf-8")
            (folder / "office.sh").write_text(
                "sudo ip link set kvnet addr 00:11:22:33:44:55\n",
                encoding="utf-8",
            )
            (folder / "broken.conf").write_text("<config>", encoding="utf-8")
            (folder / "empty.conf").write_text("", encoding="utf-8")
            (folder / "ignored.conf~").write_text(SAMPLE, encoding="utf-8")

            scanned = scan_directory(folder)
            names = {item.name for item in scanned}
            self.assertEqual(names, {"office", "broken"})
            good = next(item for item in scanned if item.name == "office")
            self.assertTrue(good.mac_fix)
            self.assertFalse(good.duplicate)
            self.assertEqual(good.profile.password, "test-password")
            broken = next(item for item in scanned if item.name == "broken")
            self.assertIsNotNone(broken.error)

            existing = [good.profile] if good.profile else []
            rescanned = scan_directory(folder, existing)
            good_again = next(item for item in rescanned if item.name == "office")
            self.assertTrue(good_again.duplicate)

    def test_corrupt_store_is_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profiles.json"
            path.write_text("{not json", encoding="utf-8")
            store = ProfileStore(path)
            self.assertIsNotNone(store.load_error)
            self.assertTrue((Path(temporary) / "profiles.json.broken").exists())


if __name__ == "__main__":
    unittest.main()
