Rasterly's first Linux release: a focused desktop raster editor with a dark
workspace, independent image tabs, transparent layers, selection unions and
subtractions, local healing, free transform, image/canvas resizing, and history.

### Downloads

- **AppImage:** portable x86_64 Linux application. Make it executable and launch it.
- **Debian package:** amd64 installer for Ubuntu 22.04+, Debian 12+, and compatible
  distributions. Installs Rasterly in the applications menu and adds `rasterly`
  to your PATH.

Both include Python, Qt, Pillow, and NumPy. No Python installation, cloud account,
model download, or API key is required. The release uses the local NumPy healing
engine. The `.deb` resolves desktop system libraries through apt.

```sh
chmod +x Rasterly-0.1.0-x86_64.AppImage
./Rasterly-0.1.0-x86_64.AppImage
# Or, on Debian/Ubuntu:
sudo apt install ./rasterly_0.1.0_amd64.deb
```

AppImage execution requires FUSE support. If FUSE is unavailable, use:
`./Rasterly-0.1.0-x86_64.AppImage --appimage-extract-and-run`.
Linux glibc 2.35 or newer is required; ARM builds are not included in this release.

`SHA256SUMS` contains download checksums. The source archive includes the GPLv3
license and release build scripts. Dependency versions and source links are
included in each installed runtime's `BUILD-INFO.json`.
