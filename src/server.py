import argparse
import logging
import selectors
import signal
import socket
import time
from collections import deque
from typing import Optional

from connection import Connection
from fsm import FSM, Event, State, IllegalTransition
from framing import FramingError
from protocol import (
    ProtocolError, validate_incoming, build,
    CONNECT, MOVE, REMATCH, ERROR, CLOSE, FORFEIT,
    UNEXPECTED_MESSAGE, OUT_OF_TURN, TIMED_OUT,
)
from session import GameSession

log = logging.getLogger("connect4.server")

TURN_TIMEOUT = 60.0             # seconds per turn (and for answering "Play again?"); --turn-timeout overrides
SELECT_INTERVAL = 0.5
LISTEN_BACKLOG = 8
SHUTDOWN_FLUSH_SECONDS = 1.0


class Server:
    def __init__(self, host: str, port: int, turn_timeout: float = TURN_TIMEOUT) -> None:
        self.host = host
        self.port = port
        self.turn_timeout = turn_timeout
        self.sel = selectors.DefaultSelector()
        self.listener: socket.socket | None = None
        self.waiting: deque[Connection] = deque()
        self.session: GameSession | None = None
        self.running = True
        self.fsm = FSM(actions=self._build_actions())
        self.turn_deadline: float | None = None
        self._deadline_key: tuple | None = None
        # connections to drop once the current event chain finishes (never drop mid-transition)
        self.pending_drops: list[Connection] = []

    # --- setup ---

    def _build_actions(self) -> dict:
        """Server-level actions. Session actions are merged in when a session is created."""
        return {
            "open_listener": self.open_listener,
            "enqueue_player": self.enqueue_player,
            "create_session": self.create_session,
            "close_and_discard_session": self.close_and_discard_session,
        }

    def open_listener(self, **data) -> None:
        """Create the non-blocking listening socket and register it with the selector."""
        lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lsock.bind((self.host, self.port))
        lsock.listen(LISTEN_BACKLOG)
        lsock.setblocking(False)
        self.sel.register(lsock, selectors.EVENT_READ, data=None)   # data=None marks the listener
        self.listener = lsock
        self.port = lsock.getsockname()[1]                          # real port when bound to 0
        log.info("listening on %s:%d", self.host, self.port)

    # --- lifecycle ---

    def run(self) -> None:
        """Startup via FSM, then the selector loop until self.running is False."""
        self._fire(Event.SERVER_READY)
        while self.running:
            for key, mask in self.sel.select(timeout=SELECT_INTERVAL):
                if key.data is None:
                    self._accept()
                else:
                    self._service(key.data, mask)
                self._process_pending_drops()
            self._check_turn_timeout()
        self._shutdown()

    def stop(self, *_) -> None:
        """SIGINT handler. Only sets a flag. No socket work here."""
        self.running = False

    # --- FSM driver ---

    def _fire(self, event: Event, **data) -> None:
        """Run one external event, then keep firing internal follow-up events until the FSM rests.

        Raises IllegalTransition only for the first (external) event, so _dispatch can reply ERROR.
        """
        self.fsm.transition(event, **data)
        self._advance()

    def _advance(self) -> None:
        nxt = self._next_event()
        while nxt is not None:
            self.fsm.transition(nxt)
            nxt = self._next_event()
        self._update_deadline()

    def _next_event(self) -> Optional[Event]:
        """Decide the internal event that follows the current state, or None to wait for I/O."""
        st = self.fsm.state
        s = self.session
        if st is State.MATCHMAKING:
            return Event.MATCH_FULL if len(self.waiting) >= 2 else None
        if st is State.GAME_BEGIN:
            return Event.SETUP_SENT
        if st is State.EVALUATE_PLACEMENT:
            return Event.MOVE_INVALID if s.pending_error else Event.MOVE_VALID
        if st is State.ERROR:
            return Event.ERROR_SENT
        if st is State.STATE_UPDATE:
            return Event.GAME_OVER if s.outcome else Event.STATE_SENT
        if st is State.CLIENT_DISCONNECT:
            return Event.BOTH_DROPPED if len(s.dropped) >= 2 else Event.FORFEIT_DECIDED
        if st is State.GAME_RESULT:
            if s.outcome == FORFEIT or False in s.rematch_votes.values():
                return Event.RESULT_SENT
            if len(s.rematch_votes) == 2:
                return Event.REMATCH
        return None

    # --- accept and register ---

    def _accept(self) -> None:
        """accept() a new socket, make it non-blocking, wrap in Connection, register READ with data=conn.

        Do not fire PLAYER_JOINED here: the player is enqueued when its CONNECT (with player_id) arrives.
        """
        try:
            sock, addr = self.listener.accept()
        except (BlockingIOError, InterruptedError):
            return
        sock.setblocking(False)
        conn = Connection(sock, addr)
        self.sel.register(sock, selectors.EVENT_READ, data=conn)
        log.info("accepted connection from %s:%d", *addr[:2])

    def enqueue_player(self, conn: Connection = None, **data) -> None:
        """FSM action for PLAYER_JOINED. Adds conn to the waiting queue."""
        self.waiting.append(conn)

    def create_session(self, **data) -> None:
        """FSM action for MATCH_FULL. Pops two waiting players and builds a GameSession."""
        players = [self.waiting.popleft(), self.waiting.popleft()]
        self.session = GameSession(players=players, server=self)
        self.fsm.actions = {**self._build_actions(), **self.session.actions()}

    def close_and_discard_session(self, **data) -> None:
        """Queue CLOSE to players still connected, close them after their buffers drain, drop the session."""
        if self.session is not None:
            for conn in self.session.players:
                if not conn.closed:
                    self._send(conn, build(CLOSE, reason="session finished"))
                    conn.close_after_flush = True
        self.session = None
        self.turn_deadline = None
        self.fsm.actions = self._build_actions()

    # --- read and dispatch ---

    def _service(self, conn: Connection, mask: int) -> None:
        """Flush writes first, then read and dispatch each decoded message in order."""
        if mask & selectors.EVENT_WRITE:
            self._flush(conn)
            if conn.closed:
                return
        if mask & selectors.EVENT_READ:
            try:
                messages = conn.read()
            except FramingError as exc:
                log.warning("framing error from %s: %s", conn.addr, exc)
                self._drop(conn)
                return
            except OSError:
                self._drop(conn)
                return
            if messages is None:
                self._drop(conn)
                return
            for msg in messages:
                self._dispatch(conn, msg)

    def _dispatch(self, conn: Connection, raw: dict) -> None:
        """Validate one message and translate it into FSM events. Never lets an exception escape."""
        try:
            msg = validate_incoming(raw)
        except ProtocolError as exc:
            self._send(conn, build(ERROR, code=exc.code, message=exc.message))
            return

        mtype = msg["msg_type"]
        in_game = self.session is not None and conn in self.session.players
        try:
            if mtype == CONNECT:
                if conn.player_id is not None:
                    raise IllegalTransition("already connected")
                conn.player_id = msg["player_id"]
                if self.fsm.can(Event.PLAYER_JOINED):
                    self._fire(Event.PLAYER_JOINED, conn=conn)
                else:
                    # a game is running: hold this client for the next match instead of breaking the FSM
                    self.waiting.append(conn)
            elif mtype == MOVE:
                if not in_game:
                    raise IllegalTransition("not in an active game")
                self._fire(Event.MOVE_RECEIVED, conn=conn, col=msg["col"])
            elif mtype == REMATCH:
                if not in_game or self.fsm.state is not State.GAME_RESULT:
                    raise IllegalTransition("no game result to answer")
                self.session.record_rematch_vote(conn, msg["accept"])
                self._advance()
        except IllegalTransition as exc:
            code = OUT_OF_TURN if mtype == MOVE else UNEXPECTED_MESSAGE
            self._send(conn, build(ERROR, code=code, message=str(exc)))

    def _check_turn_timeout(self) -> None:
        """If the current player has exceeded TURN_TIMEOUT, treat them as dropped.

        Also bounds the "Play again?" wait in GAME_RESULT: an unanswered vote counts as decline.
        """
        if self.turn_deadline is None or time.monotonic() < self.turn_deadline:
            return
        s = self.session
        self.turn_deadline = None
        self._deadline_key = None
        if s is None:
            return
        try:
            if self.fsm.state is State.PLAYER_TURN:
                slow = s.current()
                log.info("turn timeout for %s", slow.player_id)
                self._send(slow, build(ERROR, code=TIMED_OUT,
                                       message=f"No move within {self.turn_timeout:g}s, you forfeit"))
                self._fire(Event.PLAYER_DROPPED, conn=slow)
            elif self.fsm.state is State.GAME_RESULT:
                for i in range(2):
                    s.rematch_votes.setdefault(i, False)
                self._advance()
        except IllegalTransition as exc:
            log.warning("timeout handling ignored: %s", exc)
        self._process_pending_drops()

    def _update_deadline(self) -> None:
        """Start a fresh deadline whenever a new turn (or a new result prompt) begins.

        ERROR -> PLAYER_TURN re-prompts keep the same key, so invalid moves cannot extend the clock.
        """
        s = self.session
        st = self.fsm.state
        if s is None or st not in (State.PLAYER_TURN, State.GAME_RESULT):
            self.turn_deadline = None
            self._deadline_key = None
            return
        key = (id(s), st, s.turn, s.moves)
        if key != self._deadline_key:
            self._deadline_key = key
            self.turn_deadline = time.monotonic() + self.turn_timeout

    # --- write path (non-blocking: queue now, flush when the selector says writable) ---

    def _send(self, conn: Connection, msg: dict) -> None:
        """Queue msg on conn and enable EVENT_WRITE. Flushing happens in the loop."""
        if conn.closed:
            return
        try:
            conn.queue(msg)
        except OverflowError:
            log.warning("outbound buffer cap hit for %s, scheduling drop", conn.addr)
            if conn not in self.pending_drops:
                self.pending_drops.append(conn)
            return
        self.sel.modify(conn.sock, selectors.EVENT_READ | selectors.EVENT_WRITE, data=conn)

    def _flush(self, conn: Connection) -> None:
        """Flush conn; if drained, switch registration back to EVENT_READ only (or close if requested)."""
        try:
            drained = conn.flush()
        except OSError:
            self._drop(conn)
            return
        if not drained:
            return
        if conn.close_after_flush:
            self._unregister(conn)
            conn.close()
        else:
            self.sel.modify(conn.sock, selectors.EVENT_READ, data=conn)

    # --- drop and shutdown ---

    def _unregister(self, conn: Connection) -> None:
        self._unregister_sock(conn.sock)

    def _unregister_sock(self, sock: socket.socket) -> None:
        try:
            self.sel.unregister(sock)
        except (KeyError, ValueError):
            pass

    def _process_pending_drops(self) -> None:
        while self.pending_drops:
            self._drop(self.pending_drops.pop())

    def _drop(self, conn: Connection) -> None:
        """Unregister, close, and fire PLAYER_DROPPED (BOTH_DROPPED/forfeit follow via _next_event)."""
        if conn.closed:
            return
        self._unregister(conn)
        conn.close()
        if conn in self.waiting:
            self.waiting.remove(conn)
            return
        if self.session is not None and conn in self.session.players:
            try:
                self._fire(Event.PLAYER_DROPPED, conn=conn)
            except IllegalTransition as exc:
                log.warning("drop of %s ignored: %s", conn.addr, exc)

    def _shutdown(self) -> None:
        """Send CLOSE to open connections, flush briefly, close all sockets."""
        log.info("shutting down")
        conns = [key.data for key in list(self.sel.get_map().values()) if key.data is not None]
        for conn in conns:
            self._send(conn, build(CLOSE, reason="server shutting down"))
        # bounded, still non-blocking flush: only write to sockets the selector reports writable
        deadline = time.monotonic() + SHUTDOWN_FLUSH_SECONDS
        while time.monotonic() < deadline and any(c.outbuf and not c.closed for c in conns):
            for key, mask in self.sel.select(timeout=0.1):
                if key.data is not None and mask & selectors.EVENT_WRITE:
                    try:
                        key.data.flush()
                    except OSError:
                        self._unregister(key.data)
                        key.data.close()
        for conn in conns:
            self._unregister(conn)
            conn.close()
        if self.listener is not None:
            self._unregister_sock(self.listener)
            self.listener.close()
        self.sel.close()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="server",
        description="Server application to host clients and manage gameplay of CLI Connect-4",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind to")
    parser.add_argument("-p", "--port", type=int, required=True, help="Port to listen on")
    parser.add_argument("--turn-timeout", type=float, default=TURN_TIMEOUT,
                        help="Seconds a player has per turn and to answer Play again? (default 60)")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(name)s %(message)s")
    server = Server(args.host, args.port, turn_timeout=args.turn_timeout)
    signal.signal(signal.SIGINT, server.stop)
    server.run()


if __name__ == "__main__":
    main()
