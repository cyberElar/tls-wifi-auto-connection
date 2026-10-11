"""Build a self-contained Windows x64 ZIP and verify its frozen entry points."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile


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
    setup = [*common, "--onedir", "--windowed", "--name", "CampusLoginSetup",
             "--distpath", str(ROOT / "dist"), "--workpath", str(build / "setup-build")]
    for source in (worker, ROOT / "install-campus-login.ps1", ROOT / "run-campus-login.ps1", ROOT / "VERSION"):
        setup.extend(("--add-data", "%s:." % source))
    run(*setup, str(ROOT / "windows_setup.py"), env=environment)
    package = ROOT / "dist" / "CampusLoginSetup"
    shutil.copyfile(ROOT / "README.release.md", package / "README.txt")
    (package / "Uninstall.cmd").write_bytes(
        b'@echo off\r\nstart "" "%~dp0CampusLoginSetup.exe" --uninstall\r\n'
    )
    notices = ["Python and Tcl/Tk are bundled with this release.\n",
               "PyInstaller's bootloader is distributed under its GPL exception allowing bundled applications.\n",
               "https://pyinstaller.org/en/stable/license.html\n\n"]
    for source in (Path(sys.base_prefix) / "LICENSE.txt",
                   Path(sys.base_prefix) / "tcl" / "tcl8.6" / "license.terms",
                   Path(sys.base_prefix) / "tcl" / "tk8.6" / "license.terms"):
        if source.is_file():
            notices.append(source.name + "\n" + source.read_text(encoding="utf-8", errors="replace") + "\n\n")
    (package / "THIRD-PARTY-NOTICES.txt").write_text("".join(notices), encoding="utf-8")

    # Launch from a folder with spaces and non-ASCII characters, outside the
    # project cwd; verify bundled Tk and assets without UAC or installation.
    smoke = build / "release smoke 测试"
    smoke.mkdir(exist_ok=True)
    report = smoke / "setup-report.json"
    report.unlink(missing_ok=True)
    result = subprocess.run([str(package / "CampusLoginSetup.exe"), "--smoke-test", str(report)],
                            cwd=smoke, env=environment, timeout=60)
    if result.returncode or not report.is_file():
        raise RuntimeError("Frozen GUI smoke test failed")
    metadata = json.loads(report.read_text(encoding="utf-8"))
    if not all(metadata["assets"].values()) or metadata["version"] != options.version:
        raise RuntimeError("Incomplete frozen installer")
    subprocess.run([str(package / "_internal" / "campus-login.exe"), "--help"],
                   cwd=smoke, check=True, capture_output=True, env=environment, timeout=60)
    subprocess.run([str(package / "_internal" / "campus-login.exe"), "--list-interfaces"],
                   cwd=smoke, check=True, capture_output=True, env=environment, timeout=60)

    name = "CampusLogin-v%s-windows-x64" % options.version
    archive = ROOT / "dist" / (name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for source in sorted(package.rglob("*")):
            if source.is_file():
                output.write(source, str(Path(name) / source.relative_to(package)))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    print("Release: %s\nSHA256: %s\nGUI smoke test: %s" % (archive, digest, metadata))


if __name__ == "__main__":
    main()
