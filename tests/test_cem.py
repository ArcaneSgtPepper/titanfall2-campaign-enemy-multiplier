"""Installer safety and real VPK-reader integration tests; no engine emulation."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cem

STUB = b"untyped\r\nvoid function SPMP_MapSpawn_Init()\r\n{\r\n\tSPMP_Shared_Init()\r\n}\r\n"


def fixture_directory(script=STUB, multi=False):
    """Independent fixture encoder: two entries, optional multi-chunk script."""
    archive = b"untouched asset contents\n" + script
    offset = len(archive) - len(script)
    record = struct.pack("<IHH", zlib.crc32(script), 0, 0)
    chunks = [script[:len(script)//2], script[len(script)//2:]] if multi else [script]
    for i, chunk in enumerate(chunks):
        record += struct.pack("<IHQQQH", 257, 0, offset, len(chunk), len(chunk),
                              0xFFFF if i == len(chunks)-1 else 0)
        offset += len(chunk)
    other = archive[:len(archive)-len(script)]
    tree = b"gnut\0scripts/vscripts/sp\0_sp_mapspawn\0" + record + b"\0\0"
    tree += b"txt\0resource\0sentinel\0" + struct.pack("<IHHIHQQQH", zlib.crc32(other),
                                                    0, 0, 257, 0, 0, len(other), len(other), 0xFFFF)
    tree += b"\0\0\0"
    return struct.pack("<IHHII", 0x55AA1234, 2, 3, len(tree), 0) + tree, archive


class PatchTests(unittest.TestCase):
    def test_replace_multichunk_entry_keeps_other_metadata(self):
        original, _ = fixture_directory(multi=True)
        payload = b"new script\r\n"
        result = cem.patch_directory(original, payload, 14)
        before, after = cem.read_directory(original), cem.read_directory(result)
        entry = after[cem.TARGET]
        self.assertEqual(entry.index, 14)
        self.assertEqual(entry.crc, zlib.crc32(payload))
        self.assertEqual(entry.chunks, [(257, 0, 0, len(payload), len(payload))])
        a, b = before["resource/sentinel.txt"], after["resource/sentinel.txt"]
        self.assertEqual(original[a.start:a.end], result[b.start:b.end])
        self.assertEqual(len(result), len(original)-32)

    def test_reject_malformed_archives(self):
        good, _ = fixture_directory()
        variants = [b"", good[:-1], b"XXXX" + good[4:], good + b"x"]
        preload = bytearray(good)
        struct.pack_into("<H", preload, cem.read_directory(good)[cem.TARGET].start+4, 1)
        variants.append(bytes(preload))
        for bad in variants:
            with self.subTest(length=len(bad)), self.assertRaises(cem.ModError):
                cem.read_directory(bad)

    def test_reject_unsafe_managed_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ("../Titanfall2.exe", "client_mp_test.bsp.pak000_014.vpk",
                         "englishclient_sp_training.bsp.pak000_dir.vpk", "C:/other.vpk"):
                with self.subTest(name=name), self.assertRaises(cem.ModError):
                    cem.game_path(Path(temp), name)

    def test_refuse_modified_source_and_bad_multiplier(self):
        with self.assertRaises(cem.ModError):
            cem.script_payload(STUB, 2)
        with self.assertRaises(cem.ModError):
            cem.script_payload(STUB, 4)


@unittest.skipUnless((cem.PACKAGE / "tools/tf2vpk.exe").exists(), "Requires the bundled independent VPK reader")
class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name).resolve()
        (self.game / "vpk").mkdir()
        directory, archive = fixture_directory(multi=True)
        for name in cem.MAPS:
            (self.game / "vpk" / f"englishclient_{name}.bsp.pak000_dir.vpk").write_bytes(directory)
            (self.game / "vpk" / f"client_{name}.bsp.pak000_000.vpk").write_bytes(archive)
        for name in ("englishclient_mp_test.bsp.pak000_dir.vpk",
                     "englishclient_sp_training.bsp.pak000_dir.vpk",
                     "englishclient_frontend.bsp.pak000_dir.vpk"):
            (self.game / "vpk" / name).write_bytes(b"must not be read or changed")
        self.original = self.snapshot()
        p = patch.object(cem, "STOCK_SHA", cem.sha(STUB))
        p.start()
        self.addCleanup(p.stop)

    def snapshot(self):
        return {p.name: p.read_bytes() for p in (self.game / "vpk").glob("*.vpk")}

    def verify_reader(self, multiplier):
        for name in cem.MAPS:
            path = self.game / "vpk" / f"englishclient_{name}.bsp.pak000_dir.vpk"
            self.assertEqual(cem.read_script(path), cem.script_payload(STUB, multiplier))

    def test_install_switch_idempotence_restore_with_real_reader(self):
        cem.install(self.game, 2)
        self.verify_reader(2)
        for name, original in self.original.items():
            if not cem.DIR_RE.fullmatch(name) or "sp_training" in name:
                self.assertEqual((self.game / "vpk" / name).read_bytes(), original)
        cem.install(self.game, 3)
        self.verify_reader(3)
        before = self.snapshot()
        cem.install(self.game, 3)
        self.assertEqual(before, self.snapshot())
        cem.restore(self.game)
        self.assertEqual(self.snapshot(), self.original)
        cem.restore(self.game)
        self.assertEqual(self.snapshot(), self.original)

    def test_refuse_external_index_change_without_any_write(self):
        manifest = cem.install(self.game, 2)
        path = cem.game_path(self.game, manifest["files"][0]["directory"])
        path.write_bytes(b"another mod or Steam changed this")
        before = self.snapshot()
        with self.assertRaises(cem.ModError):
            cem.restore(self.game)
        self.assertEqual(before, self.snapshot())

    def test_refuse_external_archive_change_without_any_write(self):
        manifest = cem.install(self.game, 2)
        cem.game_path(self.game, manifest["files"][0]["archive"]).write_bytes(b"foreign data")
        before = self.snapshot()
        with self.assertRaises(cem.ModError):
            cem.install(self.game, 3)
        self.assertEqual(before, self.snapshot())

    def test_corrupt_backup_blocks_switch_without_changes(self):
        manifest = cem.install(self.game, 2)
        backup = cem.state_path(self.game) / "originals" / manifest["files"][0]["directory"]
        backup.write_bytes(b"corrupted")
        before = self.snapshot()
        with self.assertRaises(cem.ModError):
            cem.install(self.game, 3)
        self.assertEqual(before, self.snapshot())

    def test_build_verification_catches_corruption_and_cleans_links(self):
        manifest = cem.prepare(self.game)
        files = cem.build_files(self.game, manifest, 2)
        name = manifest["files"][0]["archive"]
        files[name] = bytes([files[name][0] ^ 1]) + files[name][1:]
        with self.assertRaises(cem.ModError):
            cem.verify_build(self.game, manifest, files)
        self.assertEqual(self.original, self.snapshot())
        self.assertEqual(list(cem.state_path(self.game).glob("verify-*")), [])

    def test_occupied_archive_is_preserved_and_next_number_used(self):
        path = self.game / "vpk/client_sp_crashsite.bsp.pak000_014.vpk"
        path.write_bytes(b"pre-existing unrelated archive")
        manifest = cem.install(self.game, 2)
        row = next(row for row in manifest["files"] if row["map"] == "sp_crashsite")
        self.assertEqual(row["index"], 15)
        cem.restore(self.game)
        self.assertEqual(path.read_bytes(), b"pre-existing unrelated archive")

    def test_partial_switch_failure_rolls_back(self):
        cem.install(self.game, 2)
        before = self.snapshot()
        real_write = cem.atomic_write
        counter = 0

        def fail_once(path, data):
            nonlocal counter
            if path.parent == self.game / "vpk":
                counter += 1
                if counter == 4:
                    raise OSError("simulated disk failure")
            real_write(path, data)

        with patch.object(cem, "atomic_write", side_effect=fail_once), self.assertRaises(OSError):
            cem.install(self.game, 3)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(cem.load_manifest(self.game)["preset"], "2x")
        self.assertFalse((cem.state_path(self.game) / "transaction.json").exists())

    def test_process_crash_can_be_recovered(self):
        cem.install(self.game, 2)
        before = self.snapshot()
        program = '''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import cem
game = Path(sys.argv[2])
cem.STOCK_SHA = sys.argv[3]
original = cem.atomic_write
count = 0
def die(path, data):
    global count
    original(path, data)
    if path.parent == game / "vpk":
        count += 1
        if count == 4:
            os._exit(17)
cem.atomic_write = die
cem.install(game, 3)
'''
        result = subprocess.run([sys.executable, "-c", program, str(cem.PACKAGE),
                                 str(self.game), cem.sha(STUB)], capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertNotEqual(before, self.snapshot())
        self.assertTrue(cem.recover(self.game))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(cem.load_manifest(self.game)["preset"], "2x")

    def test_unrecognized_game_script_blocks_before_backup_manifest(self):
        with patch.object(cem, "STOCK_SHA", "0" * 64), self.assertRaises(cem.ModError):
            cem.prepare(self.game)
        self.assertEqual(self.original, self.snapshot())
        self.assertFalse((cem.state_path(self.game) / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
