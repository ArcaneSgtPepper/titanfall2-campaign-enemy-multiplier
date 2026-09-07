"""Reversible, local-build-specific Titanfall 2 campaign VPK patcher.

Python 3.10+. Uses the bundled, source-built tf2vpk reader for LZHAM extraction.
Never modifies an existing numbered archive or a multiplayer/frontend VPK.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from dataclasses import dataclass

# Frozen installers keep their source template/tool beside the executable,
# not in PyInstaller's temporary runtime extraction directory.
PACKAGE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
TARGET = "scripts/vscripts/sp/_sp_mapspawn.gnut"
STOCK_SHA = "ef7011a1cae3352830540a4b7f20396ceeccaaee5cf1189d7993a1ccfcbc0a9d"
MAPS = frozenset(("sp_beacon", "sp_beacon_spoke0", "sp_boomtown", "sp_boomtown_end",
                 "sp_boomtown_start", "sp_crashsite", "sp_hub_timeshift", "sp_s2s",
                 "sp_sewers1", "sp_skyway_v1", "sp_tday", "sp_timeshift_spoke02"))
DIR_RE = re.compile(r"([a-z]+)client_(sp_[a-z0-9_]+)\.bsp\.pak000_dir\.vpk\Z")
ARCHIVE_RE = re.compile(r"client_(sp_[a-z0-9_]+)\.bsp\.pak000_(\d{3})\.vpk\Z")
HEADER = struct.Struct("<IHHII")
ENTRY = struct.Struct("<IHH")
CHUNK = struct.Struct("<IHQQQ")


class ModError(RuntimeError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".cem-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, indent=2) + "\n").encode())


@dataclass
class VpkEntry:
    start: int
    end: int
    crc: int
    index: int
    chunks: list[tuple[int, int, int, int, int]]


def read_directory(data: bytes) -> dict[str, VpkEntry]:
    """Parse Respawn VPK 2.3; preserve every byte outside the replaced record."""
    if len(data) < HEADER.size:
        raise ModError("Truncated VPK header")
    magic, major, minor, size, preload = HEADER.unpack_from(data)
    if (magic, major, minor) != (0x55AA1234, 2, 3) or preload != 0:
        raise ModError("Expected Titanfall 2 VPK 2.3 without preload data")
    if size != len(data) - HEADER.size:
        raise ModError("VPK directory tree length mismatch")
    pos = HEADER.size

    def string() -> str:
        nonlocal pos
        end = data.find(b"\0", pos)
        if end < 0:
            raise ModError("Unterminated VPK tree string")
        value = data[pos:end].decode("utf-8")
        pos = end + 1
        return value

    result = {}
    try:
        while ext := string():
            while folder := string():
                while name := string():
                    path = ("" if folder == " " else folder + "/") + name + "." + ext
                    start = pos
                    crc, preload_bytes, index = ENTRY.unpack_from(data, pos)
                    pos += ENTRY.size
                    if preload_bytes or index in (0x7FFF, 0xFFFF):
                        raise ModError("Unsupported embedded/preloaded VPK entry")
                    chunks = []
                    while True:
                        chunk = CHUNK.unpack_from(data, pos)
                        pos += CHUNK.size
                        if chunk[3] > 0x100000 or chunk[4] > 0x100000:
                            raise ModError("VPK chunk exceeds the engine's 1 MiB limit")
                        chunks.append(chunk)
                        terminator, = struct.unpack_from("<H", data, pos)
                        pos += 2
                        if terminator == 0xFFFF:
                            break
                        if terminator != index:
                            raise ModError("Invalid VPK continuation index")
                    if path in result:
                        raise ModError("Duplicate VPK entry: " + path)
                    result[path] = VpkEntry(start, pos, crc, index, chunks)
    except (struct.error, UnicodeDecodeError) as exc:
        raise ModError("Malformed VPK directory") from exc
    if pos != len(data):
        raise ModError("Unexpected bytes after VPK directory tree")
    return result


def patch_directory(original: bytes, payload: bytes, index: int) -> bytes:
    if not payload or len(payload) > 0x100000 or not 0 <= index < 0x7FFF:
        raise ModError("Invalid payload size or archive index")
    entries = read_directory(original)
    if TARGET not in entries:
        raise ModError("Campaign startup script is missing from VPK")
    entry = entries[TARGET]
    load_flags, texture_flags = entry.chunks[0][:2]
    record = (ENTRY.pack(zlib.crc32(payload), 0, index) +
              CHUNK.pack(load_flags, texture_flags, 0, len(payload), len(payload)) +
              struct.pack("<H", 0xFFFF))
    patched = bytearray(original[:entry.start] + record + original[entry.end:])
    struct.pack_into("<I", patched, 8, len(patched) - HEADER.size)
    after = read_directory(patched)
    if after.keys() != entries.keys():
        raise ModError("Patch changed the directory's file list")
    for name, before in entries.items():
        if name == TARGET:
            continue
        current = after[name]
        if original[before.start:before.end] != patched[current.start:current.end]:
            raise ModError("Patch unexpectedly modified another VPK entry")
    return bytes(patched)


def script_payload(original: bytes, multiplier: int) -> bytes:
    if multiplier not in (2, 3):
        raise ModError("Multiplier must be 2 or 3")
    if sha(original) != STOCK_SHA:
        raise ModError("Startup script is not the verified stock version; refusing to replace another mod")
    anchor = b"\tSPMP_Shared_Init()\r\n"
    if original.count(anchor) != 1:
        raise ModError("Expected exactly one campaign initialization hook")
    source = (PACKAGE / "src/campaign_enemy_multiplier.gnut").read_text(encoding="utf-8")
    if source.count("@MULTIPLIER@") != 1:
        raise ModError("Invalid multiplier template")
    source = source.replace("@MULTIPLIER@", str(multiplier)).replace("\r\n", "\n").replace("\n", "\r\n")
    return (original.replace(anchor, anchor + b"\tCEM_Init()\r\n") + b"\r\n" + source.encode("utf-8"))


def game_path(game: Path, name: str) -> Path:
    directory = DIR_RE.fullmatch(name)
    archive = ARCHIVE_RE.fullmatch(name)
    if not ((directory and directory[2] in MAPS) or (archive and archive[1] in MAPS)):
        raise ModError("Invalid managed file name: " + name)
    base = (game / "vpk").resolve()
    target = base / name
    if target.resolve().parent != base:
        raise ModError("Managed path escapes the VPK directory")
    return target


def state_path(game: Path) -> Path:
    path = game / ".campaign-enemy-multiplier-state"
    if path.resolve().parent != game.resolve():
        raise ModError("State directory escapes the game directory")
    return path


def checked_backup(state: Path, name: str, expected: str) -> bytes:
    path = state / "originals" / name
    if path.resolve().parent != (state / "originals").resolve():
        raise ModError("Invalid backup path")
    data = path.read_bytes()
    if sha(data) != expected:
        raise ModError("Backup checksum failed: " + name)
    return data


def read_script(directory: Path) -> bytes:
    tool = PACKAGE / "tools/tf2vpk.exe"
    if not tool.is_file():
        raise ModError("Missing tools/tf2vpk.exe; see README.md for the source build command")
    result = subprocess.run([str(tool), "get", str(directory), TARGET], capture_output=True)
    if result.returncode:
        message = result.stderr.decode(errors="replace").strip().splitlines()
        raise ModError("\n".join(message[:3]))
    return result.stdout


def assert_game_closed() -> None:
    if os.name != "nt":
        return
    result = subprocess.run(["tasklist.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ModError("Could not check running processes; close the game and retry")
    names = {row[0].lower() for row in csv.reader(io.StringIO(result.stdout)) if row}
    if names & {"titanfall2.exe", "northstarlauncher.exe", "northstar.exe"}:
        raise ModError("Close Titanfall 2 and its mod launcher before changing VPKs")


def load_manifest(game: Path) -> dict:
    path = state_path(game) / "manifest.json"
    if not path.is_file():
        raise ModError("No baseline exists; run build or install first")
    manifest = json.loads(path.read_text())
    if manifest.get("schema") != 1 or manifest.get("game") != str(game.resolve()):
        raise ModError("This backup belongs to another game directory or patcher version")
    return manifest


def validate_current(game: Path, manifest: dict) -> None:
    for row in manifest["files"]:
        path = game_path(game, row["directory"])
        expected = row.get("installed_sha", row["original_sha"])
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ModError("Game files changed outside this mod: " + path.name +
                           ". No files were overwritten; inspect the backup before proceeding.")
    for name, expected in manifest.get("archives", {}).items():
        path = game_path(game, name)
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ModError("Mod archive changed outside this installer: " + name)
    if manifest["preset"] == "original":
        for name in {row["archive"] for row in manifest["files"]}:
            if game_path(game, name).exists():
                raise ModError("Another file now occupies the reserved archive: " + name)


def prepare(game: Path) -> dict:
    state = state_path(game)
    if (state / "manifest.json").is_file():
        manifest = load_manifest(game)
        validate_current(game, manifest)
        return manifest
    if not (game / "vpk").is_dir():
        raise ModError("Game directory must contain the vpk folder")
    files = []
    backups = {}
    archive_by_map = {}
    for path in sorted((game / "vpk").glob("*client_sp_*_dir.vpk")):
        match = DIR_RE.fullmatch(path.name)
        if not match or match[2] not in MAPS:
            continue
        path = game_path(game, path.name)
        data = path.read_bytes()
        entries = read_directory(data)
        source = read_script(path)
        if sha(source) != STOCK_SHA:
            raise ModError("Unsupported or already modified startup script in " + path.name)
        map_name = match[2]
        if map_name not in archive_by_map:
            used = {entry.index for entry in entries.values()}
            index = next((i for i in range(14, 1000) if i not in used and
                          not (game / "vpk" / f"client_{map_name}.bsp.pak000_{i:03}.vpk").exists()), None)
            if index is None:
                raise ModError("No free supplementary archive number")
            archive_by_map[map_name] = index
        index = archive_by_map[map_name]
        if index in {entry.index for entry in entries.values()}:
            raise ModError("Localized VPKs disagree about free archive numbers")
        row = dict(directory=path.name, map=map_name, index=index,
                   archive=f"client_{map_name}.bsp.pak000_{index:03}.vpk",
                   original_sha=sha(data), script_sha=sha(source))
        files.append(row)
        backups[path.name] = data
        backups[path.name + ".gnut"] = source
    found = {row["map"] for row in files}
    if found != MAPS:
        raise ModError("Campaign VPKs are missing: " + ", ".join(sorted(MAPS - found)))
    manifest = dict(schema=1, game=str(game.resolve()), preset="original", files=files, archives={})
    for name, data in backups.items():
        path = state / "originals" / name
        if path.exists():
            if path.read_bytes() != data:
                raise ModError("Refusing to replace an existing backup: " + name)
        else:
            atomic_write(path, data)
    write_json(state / "manifest.json", manifest)
    return manifest


def build_files(game: Path, manifest: dict, multiplier: int) -> dict[str, bytes]:
    files = {}
    state = state_path(game)
    for row in manifest["files"]:
        original = checked_backup(state, row["directory"], row["original_sha"])
        source = checked_backup(state, row["directory"] + ".gnut", row["script_sha"])
        payload = script_payload(source, multiplier)
        files[row["archive"]] = payload
        files[row["directory"]] = patch_directory(original, payload, row["index"])
    return files


def verify_build(game: Path, manifest: dict, files: dict[str, bytes]) -> None:
    """Read full patched indexes with tf2vpk, borrowing untouched data by hardlink.

    tf2vpk opens every numbered archive when it opens an index, even for a
    single-file read. Keep these temporary links out of the deliverable.
    """
    state = state_path(game).resolve()
    work = Path(tempfile.mkdtemp(prefix="verify-", dir=state)).resolve()
    if work.parent != state:
        raise ModError("Verification directory is outside the backup directory")
    created = []
    try:
        for name, data in files.items():
            dest = work / name
            dest.write_bytes(data)
            created.append(dest)
        for row in manifest["files"]:
            for index in {entry.index for entry in read_directory(files[row["directory"]]).values()}:
                name = f"client_{row['map']}.bsp.pak000_{index:03}.vpk"
                dest = work / name
                if not dest.exists():
                    os.link(game_path(game, name), dest)
                    created.append(dest)
            if read_script(work / row["directory"]) != files[row["archive"]]:
                raise ModError("Independent VPK extraction verification failed")
    finally:
        # Only remove specifically created files/links; never traverse or remove
        # any source archive or an arbitrary directory tree.
        for path in reversed(created):
            if path.parent != work:
                raise ModError("Unsafe verification cleanup path")
            path.unlink()
        work.rmdir()


def recover(game: Path) -> bool:
    """Roll an interrupted transaction back only if all files are still ours."""
    state = state_path(game)
    path = state / "transaction.json"
    if not path.exists():
        return False
    journal = json.loads(path.read_text())
    before_data = {}
    for item in journal["writes"]:
        dest = game_path(game, item["name"])
        current = sha(dest.read_bytes()) if dest.exists() else None
        if current not in (item["before_sha"], item["after_sha"]):
            raise ModError("Recovery stopped because a file changed externally: " + dest.name)
        data = None
        if item["before_sha"] is not None:
            backup = state / "transaction" / item["name"]
            if backup.resolve().parent != (state / "transaction").resolve():
                raise ModError("Invalid recovery backup path")
            data = backup.read_bytes()
            if sha(data) != item["before_sha"]:
                raise ModError("Recovery backup checksum failed")
        before_data[item["name"]] = data
    # All conflicts and backup hashes are checked before the first write.
    for name, data in reversed(list(before_data.items())):
        dest = game_path(game, name)
        if data is None:
            dest.unlink(missing_ok=True)
        else:
            atomic_write(dest, data)
    write_json(state / "manifest.json", journal["before_manifest"])
    path.unlink()
    return True


def transaction(game: Path, before: dict, after: dict, writes: dict[str, bytes | None]) -> None:
    state = state_path(game)
    journal = dict(before_manifest=before, writes=[])
    for name, data in writes.items():
        dest = game_path(game, name)
        prior = dest.read_bytes() if dest.exists() else None
        if prior is not None:
            atomic_write(state / "transaction" / name, prior)
        journal["writes"].append(dict(name=name, before_sha=sha(prior) if prior is not None else None,
                                      after_sha=sha(data) if data is not None else None))
    write_json(state / "transaction.json", journal)
    try:
        # Numbered payloads are inserted before indexes reference them.
        for name, data in writes.items():
            dest = game_path(game, name)
            if data is None:
                dest.unlink(missing_ok=True)
            else:
                atomic_write(dest, data)
        write_json(state / "manifest.json", after)
        (state / "transaction.json").unlink()
    except BaseException:
        recover(game)
        raise


def install(game: Path, multiplier: int) -> dict:
    before = prepare(game)
    files = build_files(game, before, multiplier)
    verify_build(game, before, files)
    after = json.loads(json.dumps(before))
    after["preset"] = f"{multiplier}x"
    after["archives"] = {name: sha(data) for name, data in files.items() if ARCHIVE_RE.fullmatch(name)}
    for row in after["files"]:
        row["installed_sha"] = sha(files[row["directory"]])
    validate_current(game, before)
    transaction(game, before, after, files)
    validate_current(game, after)
    return after


def restore(game: Path) -> dict:
    before = load_manifest(game)
    validate_current(game, before)
    if before["preset"] == "original":
        return before
    after = json.loads(json.dumps(before))
    after["preset"] = "original"
    after["archives"] = {}
    writes = {}
    for row in after["files"]:
        writes[row["directory"]] = checked_backup(state_path(game), row["directory"], row["original_sha"])
        row.pop("installed_sha", None)
    # Restore indexes before removing supplementary payloads.
    for name in before["archives"]:
        writes[name] = None
    transaction(game, before, after, writes)
    validate_current(game, after)
    return after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "install", "restore", "status", "verify", "recover"))
    parser.add_argument("--multiplier", type=int, choices=(2, 3), default=2)
    parser.add_argument("--game-dir", type=Path, default=PACKAGE.parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    game = args.game_dir.resolve()
    lock = None
    try:
        # OS locks release automatically on process exit, including a crash.
        # Serialize status reads too so they never observe a half-switched preset.
        state_path(game).mkdir(parents=True, exist_ok=True)
        lock = (state_path(game) / "installer.lock").open("a+b")
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command not in ("status", "verify"):
            assert_game_closed()
            if recover(game):
                print("Recovered an interrupted change; previous preset restored.")
        if args.command == "recover":
            return 0
        if (state_path(game) / "transaction.json").exists():
            raise ModError("An interrupted transaction needs recovery; run recover with the game closed")
        if args.command == "build":
            manifest = prepare(game)
            files = build_files(game, manifest, args.multiplier)
            verify_build(game, manifest, files)
            output = (args.output or PACKAGE / "build" / f"{args.multiplier}x").resolve()
            # Never allow a build command to act as an unjournaled install.
            if output == (game / "vpk").resolve() or output.is_relative_to(state_path(game).resolve()):
                raise ModError("Build output must be separate from game VPKs and backups")
            for name, data in files.items():
                atomic_write(output / name, data)
            print(f"Built and independently verified {args.multiplier}x for {len(manifest['files'])} campaign VPKs: {output}")
            return 0
        if args.command == "install":
            manifest = install(game, args.multiplier)
        elif args.command == "restore":
            manifest = restore(game)
        else:
            manifest = load_manifest(game)
            validate_current(game, manifest)
        if args.command == "verify":
            for row in manifest["files"]:
                source = checked_backup(state_path(game), row["directory"] + ".gnut", row["script_sha"])
                expected = source if manifest["preset"] == "original" else script_payload(source, int(manifest["preset"][0]))
                if read_script(game_path(game, row["directory"])) != expected:
                    raise ModError("Independent extraction differs from expected script")
            print("All managed scripts passed independent extraction and CRC checks.")
        print(f"Preset: {manifest['preset']}; campaign VPKs: {len(manifest['files'])}; checksums OK.")
        if not (game / "Titanfall2.exe").is_file():
            print("Titanfall2.exe is missing. Restore the game installation before attempting to play.")
        if manifest["preset"] != "original":
            print("Start a fresh chapter from Mission Select without -dev. Full-campaign testing remains limited.")
        return 0
    except (ModError, OSError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
