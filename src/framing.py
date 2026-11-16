import json
import struct

HEADER = struct.Struct(">I")          # 4-byte unsigned, big-endian
MAX_MESSAGE_SIZE = 64 * 1024

# Key placed in a decoded "message" whose frame was intact but whose payload was not a JSON object.
# The frame boundary is still known, so the stream is not corrupt: protocol.validate_incoming turns
# this into an ERROR BAD_PAYLOAD reply and the client may try again.
DECODE_ERROR_KEY = "_decode_error"


class FramingError(Exception):
    """Raised when the byte stream violates the framing rules."""


def encode_message(obj: dict) -> bytes:
    """Serialize obj to compact UTF-8 JSON and prepend its 4-byte length."""
    payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise FramingError(f"message of {len(payload)} bytes exceeds MAX_MESSAGE_SIZE")
    return HEADER.pack(len(payload)) + payload


class FrameDecoder:
    """Accumulates recv() bytes and yields complete decoded messages."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[dict]:
        """Append data and return every complete message now available.

        Raises FramingError if a declared length exceeds MAX_MESSAGE_SIZE.
        Incomplete frames stay in self.buf until more bytes arrive.
        """
        self.buf.extend(data)
        messages: list[dict] = []
        while len(self.buf) >= HEADER.size:
            (length,) = HEADER.unpack_from(self.buf, 0)
            # check the declared size before waiting for (and buffering) the payload
            if length > MAX_MESSAGE_SIZE:
                raise FramingError(f"declared length {length} exceeds MAX_MESSAGE_SIZE")
            end = HEADER.size + length
            if len(self.buf) < end:
                break                                   # partial frame: wait for more bytes
            payload = bytes(self.buf[HEADER.size:end])
            del self.buf[:end]
            try:
                obj = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                obj = {DECODE_ERROR_KEY: str(exc)}
            if not isinstance(obj, dict):
                obj = {DECODE_ERROR_KEY: "payload is not a JSON object"}
            messages.append(obj)
        return messages
