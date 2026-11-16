import socket
from typing import Optional

from framing import FrameDecoder, encode_message

OUTBUF_LIMIT = 256 * 1024   # disconnect clients that stop reading
RECV_SIZE = 4096


class Connection:
    """One accepted client socket plus its per-connection buffers."""

    def __init__(self, sock: socket.socket, addr: tuple) -> None:
        self.sock = sock
        self.addr = addr
        self.decoder = FrameDecoder()
        self.outbuf = bytearray()
        self.player_id: Optional[str] = None
        self.closed = False
        self.close_after_flush = False   # set when CLOSE is queued; server closes once outbuf drains

    def fileno(self) -> int:
        return self.sock.fileno()

    def read(self) -> Optional[list[dict]]:
        """recv() once and return decoded messages.

        Returns None if the peer closed the connection (TCP EOF, 0-byte recv).
        Returns [] if the socket had nothing after all (spurious wakeup) or only a partial frame.
        Raises FramingError on malformed framing. Other OSErrors (reset, etc.) propagate.
        """
        try:
            data = self.sock.recv(RECV_SIZE)
        except (BlockingIOError, InterruptedError):
            return []
        if not data:
            return None
        return self.decoder.feed(data)

    def queue(self, msg: dict) -> None:
        """Encode msg onto outbuf. Raises OverflowError if OUTBUF_LIMIT is exceeded."""
        frame = encode_message(msg)
        if len(self.outbuf) + len(frame) > OUTBUF_LIMIT:
            raise OverflowError(f"outbound buffer for {self.addr} would exceed {OUTBUF_LIMIT} bytes")
        self.outbuf.extend(frame)

    def flush(self) -> bool:
        """Send as much of outbuf as the kernel accepts. Returns True if outbuf is now empty.

        Never blocks: a full kernel send buffer just leaves the rest for the next EVENT_WRITE.
        OSErrors such as BrokenPipeError / ConnectionResetError propagate to the server.
        """
        if not self.outbuf:
            return True
        try:
            sent = self.sock.send(self.outbuf)
        except (BlockingIOError, InterruptedError):
            return False
        del self.outbuf[:sent]
        return not self.outbuf

    def wants_write(self) -> bool:
        return bool(self.outbuf)

    def close(self) -> None:
        """Close the socket once. Safe to call more than once."""
        if self.closed:
            return
        self.closed = True
        self.outbuf.clear()
        try:
            self.sock.close()
        except OSError:
            pass
