"""Read-only sysfs discovery. Never opens an input device or changes its mode."""

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path

from .model import MODELS

PRODUCTS = {
    0x00B4: (MODELS[0], "Naga V2 HyperSpeed", "2.4 GHz"),
    0x00E7: (MODELS[1], "Naga V3 Pro", "USB wired"),
    0x00E8: (MODELS[1], "Naga V3 Pro", "2.4 GHz"),
}


def read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return ""


@dataclass
class Device:
    model: str
    name: str
    transport: str
    product_id: int
    usb_path: str
    serial: str
    interfaces: list[dict] = field(default_factory=list)

    @property
    def identity(self) -> str:
        # Port-scoped identity is explicitly weaker and unsuitable as sole proof
        # when restoring a permanent backup to a reconnected receiver.
        return f"{self.model}:{self.serial}" if self.serial else f"port:{self.usb_path}"

    def json(self) -> dict:
        return {**asdict(self), "identity": self.identity,
                "identity_strength": "serial" if self.serial else "port-only"}


def discover(sysfs: Path = Path("/sys"), dev_root: Path = Path("/dev")) -> list[Device]:
    devices: dict[str, Device] = {}
    for usb in sorted((sysfs / "bus/usb/devices").glob("*")):
        if read(usb / "idVendor") != "1532":
            continue
        try:
            pid = int(read(usb / "idProduct"), 16)
        except ValueError:
            continue
        if pid not in PRODUCTS:
            continue
        model, name, transport = PRODUCTS[pid]
        serial = read(usb / "serial")
        if not serial or set(serial) <= {"0"}:
            serial = ""
        resolved = str(usb.resolve())
        devices[resolved] = Device(model, name, transport, pid, resolved, serial)
    for category, pattern, device_dir in (("hidraw", "hidraw*", ""), ("input", "event*", "input")):
        for node in sorted((sysfs / "class" / category).glob(pattern)):
            real = (node / "device").resolve()
            parent = next((str(p) for p in (real, *real.parents) if str(p) in devices), None)
            if parent is None:
                continue
            interface = next((p for p in (real, *real.parents) if (p / "bInterfaceNumber").exists()), None)
            path = dev_root / device_dir / node.name
            driver_link = next((p / 'driver' for p in (real, *real.parents)
                                if str(p).startswith(parent + '/') and (p / 'driver').is_symlink()), None)
            devices[parent].interfaces.append({
                "kind": category, "path": str(path),
                "number": read(interface / "bInterfaceNumber") if interface else "",
                "readable": os.access(path, os.R_OK), "writable": os.access(path, os.W_OK),
                "driver": driver_link.resolve().name if driver_link is not None else None,
            })
    return list(devices.values())
