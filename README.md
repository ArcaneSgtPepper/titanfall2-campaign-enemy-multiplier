# Titanfall 2 — Campaign Enemy Multiplier

More enemies in the singleplayer campaign. Choose **2× or 3×** regular combat enemies.

**[Download v0.1.1](https://github.com/ArcaneSgtPepper/titanfall2-campaign-enemy-multiplier/releases/download/v0.1.1/CampaignEnemyMultiplier-0.1.1.zip)** · [Report a problem](https://github.com/ArcaneSgtPepper/titanfall2-campaign-enemy-multiplier/issues)

## Install

Requires **Titanfall 2 on Windows** and **Python 3.10 or newer**. If needed, install Python from [python.org](https://www.python.org/downloads/windows/) and enable **Add Python to PATH** if offered.

1. Close Titanfall 2.
2. Download the ZIP above and extract it.
3. Put the extracted **CampaignEnemyMultiplier** folder inside your **Titanfall2** game folder, next to **Titanfall2.exe**.
4. Open that folder and double-click **Install 2x.cmd** or **Install 3x.cmd**. Wait for the success message.
5. Launch the game normally and start a chapter from **Mission Select**.

In Steam, use **Titanfall 2 → Manage → Browse local files** to find the game folder.

```text
Titanfall2/
├── Titanfall2.exe
└── CampaignEnemyMultiplier/
    ├── Install 2x.cmd
    ├── Install 3x.cmd
    └── Restore Vanilla.cmd
```

No Northstar or other mod loader is required. **Do not use the `-dev` launch option.** Start a fresh chapter after installing or switching presets; older checkpoints may not initialize the mod.

## Switch or remove

- **Switch presets:** close the game, run the other installer, then restart the chapter.
- **Remove the mod:** close the game and run **Restore Vanilla.cmd**.
- **Check the installation:** run **Verify.cmd**.

Keep the **.campaign-enemy-multiplier-state** backup folder in Titanfall2 until you have restored the original game. Restore vanilla before a game update or Steam file verification.

## What changes?

- Adds extra **grunts, Spectres, Stalkers, Reapers and Prowlers** during combat.
- **2×** attempts to add one extra per eligible original enemy; **3×** attempts to add two.
- Extras use the original enemy's AI settings, weapon, maximum health and skin. Killed extras are not replaced.
- Allies, Titans, bosses and training are excluded.

Some scripted enemies and crowded areas are skipped. The multiplier is a target, so individual encounters may have fewer extras. Larger battles, especially at 3×, may reduce performance.

## Troubleshooting

**Python is missing:** install Python 3.10+ and make sure the `python` command is available, then retry.

**No extra enemies:** start a fresh chapter from Mission Select and enter a normal ground fight. Extras appear during combat. Run Verify.cmd to check installation.

**SaveRecordedAnimation error:** remove `-dev` from the launch options and restart normally.

**Unsupported script or files changed externally:** the installer found a different game version or a conflicting change. Keep the backup folder and report the exact error. Do not copy another player's generated VPK files.

For bug reports, include the chapter, 2× or 3× setting, fresh start or checkpoint, and the error message.

## Status and credits

**v0.1.1 is an early release, confirmed working in-game by the initial tester.** All 13 installer tests pass, including switching presets, restoration and interrupted-change recovery. Both presets passed archive extraction checks against the tested installation. Full campaign progression and 3× performance have not been exhaustively tested.

The download includes source code, tests and the required VPK utility. Original game scripts and assets are extracted locally and are not included.

See [DEVELOPMENT.md](DEVELOPMENT.md) for technical details. Authored code uses the [MIT license](LICENSE). The bundled reader is [pg9182/tf2vpk](https://github.com/pg9182/tf2vpk); its license and dependency notices are included in `tools/THIRD_PARTY_NOTICES`. This is an unofficial fan mod. Titanfall 2 belongs to its respective owners.
