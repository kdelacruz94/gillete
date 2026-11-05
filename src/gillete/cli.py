import argparse
import asyncio
import json
import sys

from .devices import discover
from .examples import example_profiles
from .macros import KeyLedger, MacroRunner, RecordingOutput
from .model import ConfigurationError
from .model import MODELS
from .profiles import ProfileStore


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gillete")
    parser.add_argument("--config", help="Alternate profiles.json path")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("devices", help="Read-only connected-device discovery")
    snapshot = sub.add_parser("snapshot", help="Read-only hardware metadata and binding snapshot")
    snapshot.add_argument("--product", required=True, type=lambda x: int(x, 16), choices=(0xB4, 0xE8))
    recovery = sub.add_parser("recover", help="Explicitly restore a matching mouse from its recovery journal")
    recovery.add_argument("--product", required=True, type=lambda x: int(x, 16), choices=(0xB4, 0xE8))
    recovery.add_argument("journal")
    sub.add_parser("validate", help="Validate local profiles without activating them")
    example = sub.add_parser("example", help="Preview a requested macro using simulated output")
    example.add_argument("name", choices=("excel", "vscode", "herdr"))
    gui = sub.add_parser("gui", help="Open the native profile editor")
    gui.add_argument('--background', action='store_true', help='Start in the tray when available')
    gui.add_argument('--start-service', action='store_true', help='Also start the service, using saved startup mouse choices')
    sub.add_parser('daemon', help='Run the user service; startup mouse choices are off by default')
    control = sub.add_parser('control', help='Control the user service')
    control.add_argument('action', choices=('status', 'enable', 'disable', 'pin', 'stop-actions', 'shutdown'))
    control.add_argument('--model', choices=('v2', 'v3'))
    control.add_argument('--profile', help='Profile ID, or automatic')
    args = parser.parse_args(argv)
    from pathlib import Path
    store = ProfileStore(Path(args.config) if args.config else None)
    try:
        if args.command == "devices":
            print(json.dumps([d.json() for d in discover()], indent=2))
        elif args.command == 'daemon':
            from .service import Daemon
            asyncio.run(Daemon(store).run())
        elif args.command == 'control':
            from .service import request
            model = MODELS[0 if args.model == 'v2' else 1] if args.model else None
            result = asyncio.run(request(args.action, model=model, profile=args.profile,
                                         config_path=store.path if args.config else None))
            print(json.dumps(result if args.action == 'status' else result['devices'], indent=2))
        elif args.command in {"snapshot", "recover"}:
            from .hid import snapshot_device
            matches = [d for d in discover() if d.product_id == args.product]
            if len(matches) != 1:
                raise ConfigurationError("Connect exactly one receiver of the requested model")
            if args.command == "snapshot":
                print(json.dumps(snapshot_device(matches[0]), indent=2))
            else:
                from .hardware import restore
                result = restore(matches[0], Path(args.journal))
                print(result['status'])
        elif args.command == "validate":
            config = store.read()
            config.validate()
            print(f"Valid configuration: {len(config.profiles)} profiles, revision {config.revision}")
        elif args.command == "example":
            async def preview():
                output = RecordingOutput()
                runner = MacroRunner(KeyLedger(output))
                profile = example_profiles()[{"excel": 0, "vscode": 1, "herdr": 2}[args.name]]
                await runner.start("preview", profile.common.normal["side_1"])
                await asyncio.gather(*runner.jobs.values())
                print(json.dumps({"simulated": True, "events": output.events}, indent=2))
            asyncio.run(preview())
        else:
            from .gui import start
            return start(store, background=getattr(args, 'background', False),
                         start_service=getattr(args, 'start_service', False))
    except (ValueError, OSError, RuntimeError) as error:
        print(f"gillete: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
