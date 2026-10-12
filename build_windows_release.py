"""Build a single self-contained Windows x64 setup .exe and verify its frozen entry points."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def run(*arguments, env=None):
    subprocess.run(arguments, check=True, cwd=ROOT, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=(ROOT / "VERSION").read_text().strip())
    options = parser.parse_args()
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("Build this release with 64-bit Python on Windows x64.")
    if options.version != (ROOT / "VERSION").read_text().strip():
        parser.error("The release version must match VERSION.")
    from importlib.metadata import version
    if version("pyinstaller") != "6.22.3":
        parser.error("Install the pinned build dependencies from requirements-build.txt.")

    build = ROOT / "build"
    (build / "tmp").mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(TEMP=str(build / "tmp"), TMP=str(build / "tmp"),
                       PYINSTALLER_CONFIG_DIR=str(build / "pyinstaller-cache"))
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--noupx",
              "--specpath", str(build / "spec")]
    run(*common, "--onefile", "--name", "campus-login", "--distpath", str(build / "worker"),
        "--workpath", str(build / "worker-build"), str(ROOT / "campus-login.py"), env=environment)
    worker = build / "worker" / "campus-login.exe"

    notices = ["Python and Tcl/Tk are bundled with this release.\n",
               "PyInstaller's bootloader is distributed under its GPL exception allowing bundled applications.\n",
               "https://pyinstaller.org/en/stable/license.html\n\n"]
    for source in (Path(sys.base_prefix) / "LICENSE.txt",
                   Path(sys.base_prefix) / "tcl" / "tcl8.6" / "license.terms",
                   Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"):
        if source.is_file():
            notices.append(source.name + "\n" + source.read_text(encoding="utf-8", errors="replace") + "\n\n")
    notice = build / "THIRD-PARTY-NOTICES.txt"
    notice.write_text("".join(notices), encoding="utf-8")

    # One file to download and double-click: students should not have to
    # unzip anything or keep a folder of runtime files next to the program.
    setup = [*common, "--onefile", "--windowed", "--name", "CampusLoginSetup",
             "--distpath", str(build / "setup"), "--workpath", str(build / "setup-build")]
    for source in (worker, ROOT / "install-campus-login.ps1", ROOT / "run-campus-login.ps1",
                   ROOT / "VERSION", notice):
        setup.extend(("--add-data", "%s:." % source))
    run(*setup, str(ROOT / "windows_setup.py"), env=environment)
    built = build / "setup" / "CampusLoginSetup.exe"

    # Launch from a folder with spaces and non-ASCII characters, outside the
    # project cwd; verify bundled Tk and assets without UAC or installation.
    smoke = build / "release smoke 测试"
    smoke.mkdir(exist_ok=True)
    report = smoke / "setup-report.json"
    report.unlink(missing_ok=True)
    result = subprocess.run([str(built), "--smoke-test", str(report)],
                            cwd=smoke, env=environment, timeout=120)
    if result.returncode or not report.is_file():
        raise RuntimeError("Frozen GUI smoke test failed")
    metadata = json.loads(report.read_text(encoding="utf-8"))
    if not all(metadata["assets"].values()) or metadata["version"] != options.version:
        raise RuntimeError("Incomplete frozen installer")
    if set(metadata.get("languages", {})) != {"zh-CN", "en"}:
        raise RuntimeError("Frozen installer is missing a GUI language")
    subprocess.run([str(worker), "--help"],
                   cwd=smoke, check=True, capture_output=True, env=environment, timeout=60)
    subprocess.run([str(worker), "--list-interfaces"],
                   cwd=smoke, check=True, capture_output=True, env=environment, timeout=60)

    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    release = dist / ("CampusLoginSetup-v%s-windows-x64.exe" % options.version)
    shutil.copyfile(built, release)
    shutil.copyfile(notice, dist / notice.name)
    with release.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    release.with_name(release.name + ".sha256").write_text(digest + "  " + release.name + "\n", encoding="ascii")
    # Windows build logs may use cp1252; bilingual report text must be escaped.
    print("Release: %s\nSHA256: %s\nGUI smoke test: %s" % (
        release, digest, json.dumps(metadata, ensure_ascii=True)))


if __name__ == "__main__":
    main()
