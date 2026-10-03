#!/usr/bin/env python3
"""Build self-contained x86_64 AppImage and Debian packages on Ubuntu 22.04."""
from pathlib import Path
import hashlib
from importlib import metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "linux"
DIST = ROOT / "dist"
REPO = "https://github.com/tefaz/rasterly-image-editing-software"


def run(command, **kwargs):
    print("Running:", " ".join(map(str, command)), flush=True)
    result = subprocess.run(list(map(str, command)), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, **kwargs)
    print(result.stdout, flush=True)
    if result.returncode:
        # GitHub exposes annotations through its public checks API, so a failed
        # build can be diagnosed without a user's GitHub authentication token.
        error = result.stdout[-5000:].replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
        print(f"::error::{error}", flush=True)
        raise subprocess.CalledProcessError(result.returncode, command)
    return result.stdout


def download(url, target, expected=None):
    with urllib.request.urlopen(url, timeout=120) as response:
        content = response.read()
    if expected and hashlib.sha256(content).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch: {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def notices(bundle, version):
    copy(ROOT / "LICENSE", bundle / "LICENSE")
    copy(ROOT / "packaging" / "THIRD-PARTY-NOTICES.md", bundle / "THIRD-PARTY-NOTICES.md")
    components = {}
    for name in ("PyQt6", "PyQt6-Qt6", "PyQt6-sip", "Pillow", "numpy", "pyinstaller"):
        distribution = metadata.distribution(name)
        release_url = f"https://pypi.org/pypi/{name}/{distribution.version}/json"
        with urllib.request.urlopen(release_url, timeout=60) as response:
            release = json.load(response)
        sources = [{"url": asset["url"], "sha256": asset["digests"]["sha256"]}
                   for asset in release["urls"] if asset["packagetype"] == "sdist"]
        components[name] = {"version": distribution.version, "sources": sources}
        for relative in distribution.files or ():
            lowered = str(relative).lower()
            if any(word in lowered for word in ("license", "licence", "copying", "copyright", "notice")):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    # Never copy outside a component's notice directory.
                    safe_parts = [part for part in Path(relative).parts if part not in {"..", "/"}]
                    copy(source, bundle / "licenses" / name / Path(*safe_parts))

    # PyInstaller's library analysis can collect system shared libraries.
    # Include their Debian copyright files alongside the wheel license files.
    copied = set()
    for library in (bundle / "_internal").rglob("*.so*"):
        for base in (Path("/usr/lib/x86_64-linux-gnu"), Path("/lib/x86_64-linux-gnu")):
            candidate = base / library.name
            if not candidate.is_file():
                continue
            result = subprocess.run(["dpkg-query", "-S", str(candidate)], capture_output=True, text=True)
            if result.returncode:
                continue
            for line in result.stdout.splitlines():
                package = line.split(": ", 1)[0].split(":", 1)[0]
                copyright_file = Path("/usr/share/doc") / package / "copyright"
                if package not in copied and copyright_file.is_file():
                    copy(copyright_file, bundle / "licenses" / "system" / package / "copyright")
                    copied.add(package)

    python_version = platform.python_version()
    qt_version = metadata.version("PyQt6-Qt6")
    qt_series = ".".join(qt_version.split(".")[:2])
    components["Python"] = {"version": python_version,
                            "source": f"https://www.python.org/ftp/python/{python_version}/Python-{python_version}.tar.xz"}
    components["Qt"] = {"version": qt_version,
                        "source": f"https://download.qt.io/archive/qt/{qt_series}/{qt_version}/single/qt-everywhere-src-{qt_version}.tar.xz"}
    tools = json.loads((ROOT / "packaging" / "appimage-tools.json").read_text())
    components["AppImage-runtime"] = {**tools["runtime"],
                                      "source": "https://github.com/AppImage/type2-runtime"}
    download(f"https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE",
             bundle / "licenses" / "Python" / "LICENSE")
    download("https://raw.githubusercontent.com/AppImage/type2-runtime/main/LICENSE",
             bundle / "licenses" / "AppImage-runtime" / "LICENSE")
    download("https://www.gnu.org/licenses/lgpl-3.0.txt", bundle / "licenses" / "Qt" / "LGPL-3.0.txt")
    info = {"application": "Rasterly", "version": version,
            "commit": run(["git", "rev-parse", "HEAD"]).strip(),
            "platform": "Linux x86_64", "minimum_glibc": "2.35",
            "build_host": platform.platform(), "components": components}
    manifest = json.dumps(info, indent=2) + "\n"
    (bundle / "BUILD-INFO.json").write_text(manifest)
    (DIST / f"Rasterly-{version}-build-info.json").write_text(manifest)


def render_icon(output):
    from PyQt6.QtCore import Qt, QRectF
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    QSvgRenderer(str(ROOT / "rasterly" / "resources" / "rasterly.svg")).render(painter, QRectF(0, 0, 256, 256))
    painter.end()
    if not image.save(str(output)):
        raise ValueError("Could not render release icon")


def desktop_files(target, icon):
    copy(ROOT / "packaging" / "Rasterly.desktop", target / "usr/share/applications/Rasterly.desktop")
    copy(ROOT / "packaging" / "rasterly.xml", target / "usr/share/mime/packages/rasterly.xml")
    copy(icon, target / "usr/share/icons/hicolor/256x256/apps/rasterly.png")
    copy(ROOT / "rasterly/resources/rasterly.svg", target / "usr/share/icons/hicolor/scalable/apps/rasterly.svg")


def build():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise SystemExit("This release builder requires Linux x86_64")
    if not (ROOT / "LICENSE").is_file():
        raise SystemExit("The project license must be approved before packaging")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    version = project["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("Use a three-part release version")
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/") and ref != f"refs/tags/v{version}":
        raise SystemExit("Release tag and project version do not match")
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
               "--name", "rasterly", "--distpath", WORK / "frozen", "--workpath", WORK / "pyinstaller",
               "--specpath", WORK, "--paths", ROOT,
               "--add-data", f"{ROOT / 'rasterly/resources'}:rasterly/resources",
               "--add-binary", "/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0:.",
               "--exclude-module", "tkinter", "--exclude-module", "cv2", ROOT / "packaging/launcher.py"]
    run(command, cwd=ROOT)
    bundle = WORK / "frozen" / "rasterly"
    notices(bundle, version)
    run([bundle / "rasterly", "--version"])
    run(["xvfb-run", "-a", bundle / "rasterly", "--packaging-smoke-test"],
        env={**os.environ, "QT_QPA_PLATFORM": "xcb"})
    icon = WORK / "rasterly.png"
    render_icon(icon)

    appdir = WORK / "Rasterly.AppDir"
    shutil.copytree(bundle, appdir / "usr/lib/rasterly", symlinks=True)
    desktop_files(appdir, icon)
    (appdir / "usr/bin").mkdir(parents=True)
    (appdir / "usr/bin/rasterly").symlink_to("../lib/rasterly/rasterly")
    copy(ROOT / "packaging/Rasterly.desktop", appdir / "Rasterly.desktop")
    copy(icon, appdir / "rasterly.png")
    (appdir / ".DirIcon").symlink_to("rasterly.png")
    (appdir / "AppRun").write_text(
        '#!/bin/sh\nset -eu\nrasterly_appdir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'exec "$rasterly_appdir/usr/lib/rasterly/rasterly" "$@"\n')
    (appdir / "AppRun").chmod(0o755)
    tools = json.loads((ROOT / "packaging/appimage-tools.json").read_text())
    for name, entry in tools.items():
        download(entry["url"], WORK / name, entry["sha256"]).chmod(0o755)
    appimage = DIST / f"Rasterly-{version}-x86_64.AppImage"
    run([WORK / "appimagetool", "--appimage-extract-and-run", "--runtime-file", WORK / "runtime",
         "--no-appstream", appdir, appimage], env={**os.environ, "ARCH": "x86_64"})
    appimage.chmod(0o755)

    debroot = WORK / "deb"
    shutil.copytree(bundle, debroot / "opt/rasterly", symlinks=True)
    desktop_files(debroot, icon)
    (debroot / "usr/bin").mkdir(parents=True)
    (debroot / "usr/bin/rasterly").symlink_to("/opt/rasterly/rasterly")
    doc = debroot / "usr/share/doc/rasterly"
    doc.mkdir(parents=True)
    copy(ROOT / "README.md", doc / "README.md")
    (doc / "copyright").write_text(
        f"Rasterly {version}\nCopyright 2026 Mads Nørgaard\nSource: {REPO}\n\n" + (ROOT / "LICENSE").read_text())
    installed_size = sum(path.stat().st_size for path in debroot.rglob("*")
                         if path.is_file() and not path.is_symlink()) // 1024
    control = debroot / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(
        f"Package: rasterly\nVersion: {version}\nSection: graphics\nPriority: optional\nArchitecture: amd64\n"
        "Maintainer: Mads Nørgaard <madds.noergaard@gmail.com>\n"
        f"Installed-Size: {installed_size}\nHomepage: {REPO}\n"
        "Depends: libc6 (>= 2.35), libgl1, libegl1, libxcb-cursor0, libxkbcommon-x11-0\n"
        "Recommends: fonts-dejavu-core\n"
        "Description: Lightweight raster image editor\n"
        " A native dark desktop editor with transparent layers, selections,\n"
        " local healing, free transform, multiple image tabs, and action history.\n"
        " Python and application dependencies are included.\n")
    maintenance = (
        "#!/bin/sh\nset -e\n"
        "if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q || true; fi\n"
        "if command -v update-mime-database >/dev/null 2>&1; then update-mime-database /usr/share/mime || true; fi\n"
        "if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi\n")
    for name in ("postinst", "postrm"):
        (control / name).write_text(maintenance)
        (control / name).chmod(0o755)
    deb = DIST / f"rasterly_{version}_amd64.deb"
    run(["dpkg-deb", "--root-owner-group", "-Zxz", "-z6", "--build", debroot, deb])
    run(["dpkg-deb", "--info", deb])

    source = DIST / f"Rasterly-{version}-source.tar.gz"
    run(["git", "archive", "--format=tar.gz", f"--prefix=Rasterly-{version}/", "-o", source, "HEAD"])
    artifacts = [appimage, deb, source, DIST / f"Rasterly-{version}-build-info.json"]
    (DIST / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts))
    print("Release assets:", ", ".join(path.name for path in artifacts), flush=True)


if __name__ == "__main__":
    build()
