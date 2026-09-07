"""Build the two Windows release downloads from an explicit source allowlist."""
import argparse
import hashlib
from importlib.metadata import distribution
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = "0.1.2"
ROOT_FILES = (".gitignore", "cem.py", "README.md", "DEVELOPMENT.md", "CHANGELOG.md",
              "LICENSE", "Run.cmd", "Install 2x.cmd", "Install 3x.cmd",
              "Restore Vanilla.cmd", "Verify.cmd", "build_release.py", "requirements-build.txt")

def digest(data):
    return hashlib.sha256(data).hexdigest()

def manifest(files):
    return "".join(f"{digest(data)}  {name}\n" for name, data in sorted(files.items())).encode()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="Reuse the existing frozen executable")
    args = parser.parse_args()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    if not args.skip_build:
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                        "--onefile", "--console", "--noupx", "--name", "CampaignEnemyMultiplier",
                        "--distpath", str(dist / "frozen"), "--workpath", str(ROOT / "build/freezer"),
                        "--specpath", str(ROOT / "build/freezer"), str(ROOT / "cem.py")], check=True)
    files = {name: (ROOT / name).read_bytes() for name in ROOT_FILES}
    for folder in ("src", "tests", "tools"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    files["SHA256SUMS.txt"] = manifest(files)
    (ROOT / "SHA256SUMS.txt").write_bytes(files["SHA256SUMS.txt"])
    stage = dist / f"github-upload-v{VERSION}"
    for name, data in files.items():
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    standalone = {k: v for k, v in files.items() if k != "SHA256SUMS.txt"}
    standalone["CampaignEnemyMultiplier.exe"] = (dist / "frozen/CampaignEnemyMultiplier.exe").read_bytes()
    standalone["runtime-notices/Python-LICENSE.txt"] = (Path(sys.base_prefix) / "LICENSE.txt").read_bytes()
    for package in ("pyinstaller", "pyinstaller-hooks-contrib"):
        dep = distribution(package)
        for path in dep.files:
            if "licenses" in path.parts and dep.locate_file(path).is_file():
                standalone[f"runtime-notices/{package}-{path.name}"] = dep.locate_file(path).read_bytes()
    standalone["SHA256SUMS.txt"] = manifest(standalone)
    assets = {}
    for kind, content in (("Python", files), ("Standalone", standalone)):
        output = dist / f"CampaignEnemyMultiplier-{VERSION}-{kind}.zip"
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(content.items()):
                archive.writestr("CampaignEnemyMultiplier/" + name, data)
        assets[output.name] = output.read_bytes()
        print(f"{output.name}: {output.stat().st_size} bytes; SHA256 {digest(assets[output.name])}")
    (dist / f"CampaignEnemyMultiplier-{VERSION}-SHA256SUMS.txt").write_bytes(manifest(assets))

if __name__ == "__main__":
    main()
