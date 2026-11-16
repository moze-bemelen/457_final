import time
from typing import Any

from board import COLS as BOARD_COLS
from framing import DECODE_ERROR_KEY

MAX_PLAYER_ID = 32

# Message types
CONNECT = "CONNECT"
WELCOME = "WELCOME"
YOUR_TURN = "YOUR_TURN"
MOVE = "MOVE"
STATE = "STATE"
ERROR = "ERROR"
RESULT = "RESULT"
CLOSE = "CLOSE"
REMATCH = "REMATCH"   # client -> server, payload {"accept": bool}, answer to "Play again?"

CLIENT_TYPES = {CONNECT, MOVE, REMATCH}

# Outcome values carried in RESULT messages
WIN = "WIN"
DRAW = "DRAW"
FORFEIT = "FORFEIT"

# Error codes sent in ERROR messages
OUT_OF_TURN = "OUT_OF_TURN"
COLUMN_RANGE = "COLUMN_RANGE"
COLUMN_FULL = "COLUMN_FULL"
BAD_PAYLOAD = "BAD_PAYLOAD"
UNKNOWN_TYPE = "UNKNOWN_TYPE"
UNEXPECTED_MESSAGE = "UNEXPECTED_MESSAGE"
TIMED_OUT = "TURN_TIMEOUT"           # sent to a player who exceeded the turn time limit before forfeit


class ProtocolError(Exception):
    """A client message is malformed. Carries an error code for the ERROR reply."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_incoming(msg: dict) -> dict:
    """Check msg_type, required fields, and field types for a client message.

    Returns the message if valid (for MOVE, a copy with col lifted to the top level when the
    client used the blueprint form {"payload": {"col": n}}). Raises ProtocolError otherwise.
    For MOVE, col must be an int in 0..6 (bool is rejected explicitly).
    For REMATCH, accept must be a bool.
    """
    if not isinstance(msg, dict) or DECODE_ERROR_KEY in msg:
        detail = msg.get(DECODE_ERROR_KEY, "") if isinstance(msg, dict) else ""
        raise ProtocolError(BAD_PAYLOAD, f"Unknown Input, payload is not valid JSON {detail}".strip())

    msg_type = msg.get("msg_type")
    if not isinstance(msg_type, str):
        raise ProtocolError(BAD_PAYLOAD, "Unknown Input, missing msg_type")
    if msg_type not in CLIENT_TYPES:
        raise ProtocolError(UNKNOWN_TYPE, f"Unknown msg_type {msg_type!r}")

    if msg_type == CONNECT:
        pid = msg.get("player_id")
        if not isinstance(pid, str) or not pid.strip():
            raise ProtocolError(BAD_PAYLOAD, "CONNECT requires a non-empty string player_id")
        if len(pid) > MAX_PLAYER_ID:
            raise ProtocolError(BAD_PAYLOAD, f"player_id longer than {MAX_PLAYER_ID} characters")
        return {**msg, "player_id": pid.strip()}

    if msg_type == MOVE:
        col = msg.get("col")
        if col is None and isinstance(msg.get("payload"), dict):
            col = msg["payload"].get("col")
        # bool is a subclass of int in Python, so reject it explicitly
        if not isinstance(col, int) or isinstance(col, bool):
            raise ProtocolError(BAD_PAYLOAD, "MOVE requires an integer col")
        if not 0 <= col < BOARD_COLS:
            raise ProtocolError(COLUMN_RANGE, f"col must be 0..{BOARD_COLS - 1}")
        return {**msg, "col": col}

    # REMATCH
    if not isinstance(msg.get("accept"), bool):
        raise ProtocolError(BAD_PAYLOAD, "REMATCH requires a boolean accept")
    return msg


def build(msg_type: str, **fields: Any) -> dict:
    """Build an outbound message with msg_type and a timestamp attached."""
    return {"msg_type": msg_type, "timestamp": int(time.time()), **fields}
