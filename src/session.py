from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from board import create_board, drop_disc, check_winner, is_full, column_has_space
from connection import Connection
from protocol import (
    build, WELCOME, YOUR_TURN, STATE, ERROR, RESULT,
    OUT_OF_TURN, COLUMN_FULL, WIN, DRAW, FORFEIT,
)

GUIDE = "Enter a column number 0-6 on your turn. Connect four in a row to win."


@dataclass
class GameSession:
    """Holds one match: board, two players, whose turn it is, the outcome, and running scores.

    The session never touches sockets. Every outbound message goes through server._send(),
    which only appends to the connection's outbound buffer (non-blocking). The selector loop
    flushes it when the socket is writable.
    """

    players: list[Connection]
    server: Any = None                    # Server instance, used only for _send()
    board: list[list[str]] = field(default_factory=create_board)
    colors: tuple[str, str] = ("X", "O")
    turn: int = 0                         # index into players of the active player
    first: int = 0                        # who moves first this game (alternates on rematch)
    moves: int = 0                        # discs placed this game; lets the server detect a new turn
    outcome: Optional[str] = None         # WIN, DRAW, or FORFEIT
    winner: Optional[str] = None          # player_id of winner, if any
    dropped: set[int] = field(default_factory=set)
    pending_conn: Optional[Connection] = None
    pending_col: Optional[int] = None
    pending_error: Optional[str] = None   # set by record_pending_move, read by Server._next_event
    wins: list[int] = field(default_factory=lambda: [0, 0])
    draws: int = 0
    rematch_votes: dict[int, bool] = field(default_factory=dict)

    # --- queries ---

    def current(self) -> Connection:
        return self.players[self.turn]

    def index_of(self, conn: Connection) -> int:
        return self.players.index(conn)

    def color_of(self, conn: Connection) -> str:
        return self.colors[self.index_of(conn)]

    def scores(self) -> dict[str, int]:
        """Running score across consecutive games between these two clients."""
        return {
            self.players[0].player_id or "Player_1": self.wins[0],
            self.players[1].player_id or "Player_2": self.wins[1],
            "draws": self.draws,
        }

    def validate_move(self, conn: Connection, col: int) -> Optional[str]:
        """Return an error code (OUT_OF_TURN, COLUMN_FULL) or None if the move is legal.

        Column range (0..6) is already enforced by protocol.validate_incoming.
        """
        if conn is not self.current():
            return OUT_OF_TURN
        if not column_has_space(self.board, col):
            return COLUMN_FULL
        return None

    def record_rematch_vote(self, conn: Connection, accept: bool) -> None:
        """Not an FSM action. Server calls this on REMATCH, then lets _next_event decide."""
        self.rematch_votes[self.index_of(conn)] = accept

    def actions(self) -> dict[str, Callable[..., None]]:
        """Build the action dict merged into the FSM. Names must match TRANSITIONS exactly."""
        return {
            "send_welcome_and_state": self.send_welcome_and_state,
            "mark_player_gone": self.mark_player_gone,
            "record_pending_move": self.record_pending_move,
            "queue_error": self.queue_error,
            "apply_move": self.apply_move,
            "queue_your_turn": self.queue_your_turn,
            "broadcast_state_and_switch_turn": self.broadcast_state_and_switch_turn,
            "record_outcome": self.record_outcome,
            "record_forfeit": self.record_forfeit,
            "reset_for_rematch": self.reset_for_rematch,
        }

    # --- helpers ---

    def _send(self, conn: Connection, msg: dict) -> None:
        self.server._send(conn, msg)

    def _broadcast(self, msg: dict) -> None:
        for i, conn in enumerate(self.players):
            if i not in self.dropped:
                self._send(conn, msg)

    # --- FSM actions ---

    def send_welcome_and_state(self, **data) -> None:
        """Queue WELCOME (with color, player number, and who moves first) to each player,
        then YOUR_TURN to the first, so both clients can show turn status immediately."""
        for i, conn in enumerate(self.players):
            opponent = self.players[1 - i].player_id
            self._send(conn, build(
                WELCOME,
                color=self.colors[i],
                player_num=i + 1,
                opponent=opponent,
                next=self.current().player_id,
                board=self.board,
                guide=GUIDE,
                scores=self.scores(),
            ))
        self._send(self.current(), build(YOUR_TURN))

    def mark_player_gone(self, conn: Connection = None, **data) -> None:
        if conn is not None and conn in self.players:
            self.dropped.add(self.index_of(conn))

    def record_pending_move(self, conn: Connection = None, col: int = None, **data) -> None:
        self.pending_conn = conn
        self.pending_col = col
        self.pending_error = self.validate_move(conn, col)

    def queue_error(self, **data) -> None:
        code = self.pending_error
        message = {
            OUT_OF_TURN: "NO WRITE ACCESS: it is not your turn",
            COLUMN_FULL: "Invalid game piece placement: column is full",
        }.get(code, "Invalid move")
        self._send(self.pending_conn, build(ERROR, code=code, message=message))
        self.pending_conn = self.pending_col = self.pending_error = None

    def apply_move(self, **data) -> None:
        """Drop pending_col for the current color, then check win or draw. No broadcast here."""
        drop_disc(self.board, self.pending_col, self.colors[self.turn])
        self.moves += 1
        self.pending_conn = self.pending_col = None
        if check_winner(self.board) is not None:
            self.outcome = WIN
            self.winner = self.current().player_id
        elif is_full(self.board):
            self.outcome = DRAW

    def queue_your_turn(self, **data) -> None:
        """After an ERROR, re-prompt whoever's turn it actually is."""
        self._send(self.current(), build(YOUR_TURN))

    def broadcast_state_and_switch_turn(self, **data) -> None:
        self.turn = 1 - self.turn
        self._broadcast(build(STATE, board=self.board, next=self.current().player_id, scores=self.scores()))
        self._send(self.current(), build(YOUR_TURN))

    def record_outcome(self, **data) -> None:
        """Update running score and send the single end-of-game broadcast (board + result + scores)."""
        if self.outcome == WIN:
            self.wins[self.turn] += 1
        else:
            self.draws += 1
        self._broadcast(build(
            RESULT, outcome=self.outcome, winner=self.winner,
            board=self.board, scores=self.scores(), rematch=True,
        ))

    def record_forfeit(self, **data) -> None:
        remaining = [i for i in range(2) if i not in self.dropped]
        self.outcome = FORFEIT
        if remaining:
            idx = remaining[0]
            self.winner = self.players[idx].player_id
            self.wins[idx] += 1
        self._broadcast(build(
            RESULT, outcome=FORFEIT, winner=self.winner,
            board=self.board, scores=self.scores(), rematch=False,
        ))

    def reset_for_rematch(self, **data) -> None:
        """Keep players and scores, clear the board, alternate who moves first."""
        self.board = create_board()
        self.first = 1 - self.first
        self.turn = self.first
        self.moves = 0
        self.outcome = self.winner = None
        self.pending_conn = self.pending_col = self.pending_error = None
        self.rematch_votes.clear()
