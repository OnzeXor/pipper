# Local source recipe. Use: python3 scripts/build_arch.py
# The helper supplies the source archive and its SHA-256 in an isolated folder.
pkgname=pipper
pkgver=0.1.0
pkgrel=1
pkgdesc='Use a smartphone as a wireless second monitor on Hyprland'
arch=('any')
license=('MIT')
depends=('python>=3.11' 'python-gobject' 'python-cairo' 'gtk4' 'python-tomlkit' 'wayvnc' 'hyprland>=0.55')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
checkdepends=('desktop-file-utils')
optdepends=(
  'python-qrcode: QR code for the VNC connection'
  'nwg-displays: graphical monitor position editor'
  'wdisplays: alternative graphical position editor'
  'kitty: terminal for Hyprmon and custom editors'
)
source=("pipper-${pkgver}.tar.gz")
sha256sums=('3630586efbb8cb3bd9a4cef004799d3d807fe5142e299c790ad1abd9b8052356')
options=('!debug')

build() {
  cd "${srcdir}/pipper-${pkgver}"
  python -m build --wheel --no-isolation
}

check() {
  cd "${srcdir}/pipper-${pkgver}"
  python -m unittest discover -s tests -v
  desktop-file-validate data/pipper.desktop
}

package() {
  cd "${srcdir}/pipper-${pkgver}"
  python -m installer --destdir="${pkgdir}" --prefix=/usr dist/*.whl
  install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
