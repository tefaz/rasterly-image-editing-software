# Third-party components in Rasterly Linux releases

Rasterly is licensed under GNU GPL version 3. See `LICENSE`.
Unmodified shared libraries remain separate files in the bundled runtime.
Copies of dependency license and notice files are included in `licenses/`.
`BUILD-INFO.json` records the exact component versions and source download URLs.

| Component | License / upstream |
| --- | --- |
| Python | PSF license; https://www.python.org/downloads/source/ |
| PyQt6 | GPLv3; https://www.riverbankcomputing.com/software/pyqt/ |
| Qt | LGPLv3 and applicable third-party licenses; https://download.qt.io/archive/qt/ |
| PyQt6-sip | BSD; https://pypi.org/project/PyQt6-sip/ |
| Pillow | HPND and bundled codec licenses; https://pypi.org/project/Pillow/ |
| NumPy | BSD and bundled BLAS licenses; https://pypi.org/project/numpy/ |
| PyInstaller bootloader | GPL with bootloader exception; https://pyinstaller.org/en/stable/license.html |
| AppImage type-2 runtime | MIT and embedded-library licenses; https://github.com/AppImage/type2-runtime |

The release source archive contains Rasterly's source and packaging instructions.
Matching Python-package source distributions are linked in `BUILD-INFO.json`;
Qt's matching source archive is linked there separately. The package also includes
the Debian/Ubuntu copyright files for shared libraries collected from the build host.

The AppImage runtime notice is included in `licenses/AppImage-runtime/`.
