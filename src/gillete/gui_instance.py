"""One editor per profile file, with a private local show/start notification."""

import fcntl
import hashlib
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class EditorInstance(QObject):
    received = Signal(object)

    def __init__(self, config_path, parent=None, runtime=None):
        super().__init__(parent)
        root = runtime or Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
        directory = root / 'gillete'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
            raise PermissionError('Editor socket directory must be owned by you with mode 0700')
        identity = hashlib.sha256(str(config_path.resolve()).encode()).hexdigest()[:16]
        self.path = directory / f'editor-{identity}.sock'
        self.fd = os.open(directory / f'editor-{identity}.lock', os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        self.owned = False
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.accept_connections)

    def claim(self, *, show, start_service):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            client = QLocalSocket()
            try:
                client.connectToServer(str(self.path))
                if not client.waitForConnected(3000):
                    raise RuntimeError('The existing Gillete editor is starting or not responding; try opening it again')
                client.write((json.dumps({'show': show, 'start_service': start_service}) + '\n').encode())
                if not client.waitForBytesWritten(3000) or not client.waitForReadyRead(3000):
                    raise RuntimeError('The existing Gillete editor did not acknowledge the request')
                if bytes(client.readLine()) != b'ok\n':
                    raise RuntimeError('The existing Gillete editor rejected the request')
                return False
            finally:
                client.abort()
        self.owned = True
        self.path.unlink(missing_ok=True)
        if not self.server.listen(str(self.path)):
            raise RuntimeError('Cannot listen for editor requests: ' + self.server.errorString())
        return True

    def accept_connections(self):
        while self.server.hasPendingConnections():
            client = self.server.nextPendingConnection()
            timer = QTimer(client)
            timer.setSingleShot(True)
            timer.timeout.connect(client.abort)
            timer.start(5000)
            client.readyRead.connect(lambda c=client: self.read_request(c))
            client.disconnected.connect(client.deleteLater)
            if client.bytesAvailable():
                self.read_request(client)

    def read_request(self, client):
        if client.bytesAvailable() > 1024:
            client.abort()
            return
        if not client.canReadLine():
            return
        try:
            data = json.loads(bytes(client.readLine()))
            if (not isinstance(data, dict) or set(data) != {'show', 'start_service'}
                    or any(type(v) is not bool for v in data.values())):
                raise ValueError('Invalid editor request')
            self.received.emit(data)
            client.write(b'ok\n')
            client.disconnectFromServer()
        except (ValueError, TypeError):
            client.abort()

    def close(self):
        if self.owned:
            self.server.close()
            self.path.unlink(missing_ok=True)
            self.owned = False
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
