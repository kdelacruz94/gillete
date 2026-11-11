"""Validated local native-save artifacts; no hardware or history mutation."""

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import time

from . import native_profile_transaction as tx
from .protocol import ProtocolError


MAX_RECEIPTS = 256
FINISHED = {'saved-readback-verified', 'restored-readback-verified', 'affected-bindings-restored', 'failed-restored'}


def scan(directory, identity, *, stopped=lambda: False):
    root = Path(directory)
    paths = sorted(root.glob('native-*/profile.json'))
    if len(paths) > MAX_RECEIPTS:
        raise ProtocolError('Too many native save receipts for one storage review; archive older receipt folders first')
    stamps, records, owners = [], [], {}
    deadline = time.monotonic() + 20
    for path in paths:
        if stopped(): raise InterruptedError('Native save-history review stopped')
        if time.monotonic() >= deadline:
            raise ProtocolError('Native save-history review exceeded its time limit')
        if path.parent.is_symlink() or path.is_symlink():
            raise ProtocolError('Native save-history links cannot establish managed-object ownership')
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ProtocolError('Native save history must contain regular receipt files')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                raw = stream.read(tx.MAX_JOURNAL_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(raw) > tx.MAX_JOURNAL_BYTES:
            raise ProtocolError('Oversized native save receipt; storage cleanup is blocked')
        try: document = json.loads(raw)
        except (UnicodeError, ValueError) as error:
            raise ProtocolError('Unreadable native save receipt: ' + str(path)) from error
        if not isinstance(document, dict) or document.get('kind') != tx.KIND:
            raise ProtocolError('Unrecognized native save receipt; storage cleanup is blocked')
        name = str(path.relative_to(root))
        stamps.append({'path': name, 'sha256': sha256(raw).hexdigest()})
        before = document.get('before', {})
        if not isinstance(before, dict):
            raise ProtocolError('Malformed native save identity; storage cleanup is blocked')
        if (before.get('product'), before.get('serial')) != (identity['product'], identity['serial']):
            continue
        preview = tx.validate(document)
        if document.get('status') not in FINISHED:
            raise ProtocolError('Finish or recover the interrupted native save before cleanup: ' + name)
        records.append({'path': name, 'profile': document['profile']['name'],
                        'catalog_ids': sorted(document['catalog_before']['ids']),
                        'dependency_ids': sorted(tx.dependencies(before, preview) & set(document['catalog_before']['ids']))})
        for asset in preview.uploads:
            owners.setdefault(asset.identifier, []).append(asset)
    return {'stamp': stamps, 'records': records}, owners
