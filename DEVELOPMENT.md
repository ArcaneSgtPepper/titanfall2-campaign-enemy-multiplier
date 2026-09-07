# Development

`src/campaign_enemy_multiplier.gnut` is the authored gameplay code. `cem.py` builds, installs, verifies and restores the patch. Requires Python 3.10+ and the bundled Windows VPK reader.

From the CampaignEnemyMultiplier folder:

```powershell
python -m unittest discover -s tests -v
python cem.py build --multiplier 2
python cem.py build --multiplier 3
python cem.py install --multiplier 2
python cem.py verify
python cem.py restore
```

The package belongs directly inside the game folder; use `--game-dir` for another location. Close the game before building, installing, switching or restoring. Tests use temporary fixtures and do not modify the actual game.

## Implementation

The installer changes only `scripts/vscripts/sp/_sp_mapspawn.gnut` in the twelve non-training campaign map indexes. It inserts `CEM_Init()` after `SPMP_Shared_Init()` and appends the authored script. A small additional numbered VPK holds the payload. Existing numbered archives are not rewritten, and unrelated directory records are preserved byte for byte.

Supported original startup script SHA-256:

```text
ef7011a1cae3352830540a4b7f20396ceeccaaee5cf1189d7993a1ccfcbc0a9d
```

Unknown scripts are rejected. Backups live under the game's `.campaign-enemy-multiplier-state/originals`. The installer uses checksums, atomic writes, a process lock and a transaction journal. To recover an interrupted operation, close the game and run `python cem.py recover`.

Eligible NPCs must be alive, fighting the player or Militia, within 5,000 game units, grounded and free of scripted/busy actions, parenting and invulnerability. Extras inherit AI settings, weapon/mods, maximum health and skin, but not mission names, outputs or linked entities. Clone markers prevent recursive multiplication. Placement checks navigation, reachability, vertical separation and collisions. Limits are 96 living extras, 200 total living NPCs and eight additions per quarter-second pass. These are configuration choices, not measured engine limits.

The allowlist is `npc_soldier`, `npc_spectre`, `npc_stalker`, `npc_super_spectre`, and `npc_prowler`. Stock spawn callbacks still run. Timeline handling in Effect and Cause and ship handling in The Ark were inspected in installed scripts; full mission playthroughs remain to be tested.

Generated VPKs and backups belong to their source installation. Never distribute them. Distribute this installer, which extracts scripts from each player's own game.

## Validation

The 13 tests cover multi-chunk entries, unrelated data preservation, install/switch/restore, repeated installation, conflicting files, occupied archive numbers, corrupt backups, failed writes, process termination during a switch, and independent-reader rejection of corrupt payloads. They do not emulate NPC behavior or compile Squirrel scripts.

Remaining playtests include checkpoint reloads, allies, bosses, scripted deaths, mission progression, Reaper encounters, timeline changes, ship sections and large battles at 3×. Initial in-game success does not establish full-campaign compatibility.

## Tool provenance and research

`tools/tf2vpk.exe` was built from [pg9182/tf2vpk](https://github.com/pg9182/tf2vpk) at commit `b73c54d8e4245075ea207c7e51a2a86fdb94e4ff`, using Go 1.26.2 for Windows amd64. From that upstream checkout:

```powershell
$env:CGO_ENABLED = '0'
go build -trimpath -o tf2vpk.exe ./cmd/tf2vpk
```

Place the executable in this package's `tools` folder. Upstream and dependency licenses, including tf2lzham, LZHAM, Cobra, pflag, mousetrap, wazero and Go, are in `tools/THIRD_PARTY_NOTICES`.

Research used the [pinned VPK implementation](https://github.com/pg9182/tf2vpk/blob/b73c54d8e4245075ea207c7e51a2a86fdb94e4ff/vpk.go), [Icepick SDK](https://github.com/Titanfall-Mods/TTF2SDK), [client script reference](https://github.com/Syampuuh/Titanfall2), and locally installed server campaign scripts. The latter establish the initialization hook, NPC APIs, navigation and spawn callbacks. Original scripts are not redistributed.

## Building release packages

On Windows x64 with Python 3.14, create a virtual environment, install `requirements-build.txt`, then run `python build_release.py` in that environment. The script builds both Standalone and Python ZIPs under `dist`, with per-file checksums and release-asset checksums. It selects only authored source, docs, tests, tools and notices. It never packages local game VPKs, saves, backups or research files.

The standalone executable uses [PyInstaller 6.22.2](https://pyinstaller.org/en/v6.22.2/) to bundle Python. Its resources stay beside the executable; the default game directory is the parent of that folder, regardless of the working directory. Run.cmd prefers the executable when present, otherwise it runs cem.py with Python. The Python and PyInstaller license notices are included in the Standalone download.

Build-tool versions are pinned in requirements-build.txt. The public gameplay template remains identical to v0.1.1.

The v0.1.2 standalone was exercised with Python absent from PATH, from an unrelated working directory, in a fixture game path containing spaces. The actual CMD buttons installed 2x, verified, switched to 3x, verified, restored and verified original files across 12 fixture campaign archives. Restoration reproduced every original VPK byte. This checks installer packaging, not gameplay.
