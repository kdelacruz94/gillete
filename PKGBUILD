# tools/build_arch.py stages this recipe and a source archive in a temporary
# directory, pins its SHA256, and runs makepkg. No service is enabled on install.
pkgname=gillete
pkgver=0.1.0
pkgrel=1
pkgdesc='Native Naga profiles, macros and onboard programming for Linux'
arch=('any')
license=('custom')
depends=('python' 'python-evdev' 'pyside6' 'python-gobject' 'glib2>=2.84' 'dbus' 'hyprland' 'libxkbcommon>=1.11' 'xkeyboard-config>=2.43')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP') # Replaced with the generated archive's SHA256 by the builder.

build() {
    cd "$srcdir/$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$srcdir/$pkgname-$pkgver"
    python packaging/install_wheel.py "$pkgdir" dist/gillete-0.1.0-py3-none-any.whl
    install -Dm644 packaging/70-gillete.rules "$pkgdir/usr/lib/udev/rules.d/70-gillete.rules"
    install -Dm644 packaging/org.gillete.Gillete.desktop "$pkgdir/usr/share/applications/org.gillete.Gillete.desktop"
    install -Dm644 packaging/gillete.service "$pkgdir/usr/lib/systemd/user/gillete.service"
}
