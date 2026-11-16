import sys
import argparse
import queue
import socket
import threading
from typing import Optional

from board import COLS, EMPTY
from framing import FrameDecoder, FramingError, encode_message
from protocol import (
    CONNECT, MOVE, REMATCH, WELCOME, YOUR_TURN, STATE, ERROR, RESULT, CLOSE,
    WIN, DRAW, FORFEIT, build,
)

RECV_SIZE = 4096


def reader(sock: socket.socket, inbox: queue.Queue) -> None:
    """Background thread: recv, decode, and push each message onto inbox.

    Pushes None when the connection ends (EOF, reset, or bad framing) so the main thread can exit.
    """
    decoder = FrameDecoder()
    try:
        while True:
            data = sock.recv(RECV_SIZE)
            if not data:
                break
            for msg in decoder.feed(data):
                inbox.put(msg)
    except FramingError as exc:
        print(f"\n[ERROR] Bad data from server: {exc}")
    except OSError:
        pass
    finally:
        inbox.put(None)


def send(sock: socket.socket, msg: dict) -> None:
    sock.sendall(encode_message(msg))


# --- display helpers ---

class View:
    """What this client knows about the match, used to label players, turns, and scores."""

    def __init__(self, me: str) -> None:
        self.me = me
        self.labels: dict[str, str] = {}   # player_id -> "Player N (name, X)"
        self.nums: dict[str, int] = {}     # player_id -> 1 or 2

    def on_welcome(self, msg: dict) -> None:
        mine = msg.get("player_num", 1)
        theirs = 3 - mine
        my_color = msg.get("color", "?")
        their_color = "O" if my_color == "X" else "X"
        opp = msg.get("opponent", "opponent")
        self.nums = {self.me: mine, opp: theirs}
        self.labels = {
            self.me: f"Player {mine} ({self.me}, {my_color})",
            opp: f"Player {theirs} ({opp}, {their_color})",
        }

    def label(self, pid: Optional[str]) -> str:
        return self.labels.get(pid, str(pid))

    def turn_status(self, next_pid: Optional[str]) -> str:
        if next_pid == self.me:
            return ">>> Your Turn"
        return f"... Waiting for Player {self.nums.get(next_pid, 2)} ({next_pid})..."

    def scores(self, scores: Optional[dict]) -> str:
        if not scores:
            return ""
        parts = [f"{self.label(pid)}: {n}" for pid, n in scores.items() if pid != "draws"]
        parts.append(f"Draws: {scores.get('draws', 0)}")
        return "Score  |  " + "  |  ".join(parts)


def render_board(board: list[list[str]]) -> str:
    """Grid with column numbers on top; empty cells shown blank so discs stand out."""
    cols = len(board[0])
    header = "    " + "   ".join(str(c) for c in range(cols))
    border = "  +" + "---+" * cols
    rows = ["  |" + "|".join(f" {' ' if cell == EMPTY else cell} " for cell in row) + "|" for row in board]
    return "\n".join([header, border, *rows, border])


def turn_banner(board: list[list[str]]) -> str:
    placed = sum(cell != EMPTY for row in board for cell in row)
    return f"\n========== Turn {placed + 1} ==========" if placed < len(board) * len(board[0]) else ""


# --- input helpers (blocking input() is fine: the reader thread keeps receiving meanwhile) ---

def prompt_column() -> Optional[int]:
    """Ask for a column until the input is an int in 0..COLS-1. Returns None if the user quits."""
    while True:
        try:
            raw = input(f"Your move, column 0-{COLS - 1} (q to quit): ").strip()
        except EOFError:
            return None
        if raw.lower() in ("q", "quit", "exit"):
            return None
        if raw.isdigit() and 0 <= int(raw) < COLS:
            return int(raw)
        print(f"Please enter a whole number from 0 to {COLS - 1}.")


def prompt_yes_no(question: str) -> bool:
    while True:
        try:
            raw = input(f"{question} (y/n): ").strip().lower()
        except EOFError:
            return False
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="client",
        description="Client application to connect with other clients and initialize gameplay of CLI Connect-4",
    )
    parser.add_argument("-i", "--host", default="127.0.0.1",
                        help="Server IP or DNS hostname (e.g. server.bemelen.edu), resolved via socket.gethostbyname()")
    parser.add_argument("-p", "--port", type=int, required=True, help="Server listening port")
    parser.add_argument("--name", required=True, help="Your player id")
    args = parser.parse_args(argv)

    try:
        server_ip = socket.gethostbyname(args.host)
    except socket.gaierror:
        print(f"[ERROR] Unable to resolve DNS hostname '{args.host}'.")
        print("Please check your Cisco router DNS configuration ('ip dns server' / 'ip host') or verify domain spelling.")
        sys.exit(1)

    # IPv4 TCP socket, created explicitly (gethostbyname above returns an IPv4 address)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((server_ip, args.port))
    except OSError as exc:
        sock.close()
        print(f"[ERROR] Could not connect to {args.host}:{args.port} ({exc}).")
        sys.exit(1)

    inbox: queue.Queue = queue.Queue()
    threading.Thread(target=reader, args=(sock, inbox), daemon=True).start()
    send(sock, build(CONNECT, player_id=args.name))
    print(f"Connected to {args.host} ({server_ip}:{args.port}) as {args.name}.")
    print("Waiting for an opponent...")
    view = View(args.name)

    # Client-side validation is a convenience only; the server stays the authority on turns and columns.
    try:
        while True:
            msg = inbox.get()
            if msg is None:
                print("Connection to server closed.")
                break
            mtype = msg.get("msg_type")

            if mtype == WELCOME:
                view.on_welcome(msg)
                print("\n************ GAME START ************")
                print(f"You are {view.label(args.name)}  vs  {view.label(msg.get('opponent'))}")
                print(msg.get("guide", ""))
                print(view.scores(msg.get("scores")))
                print(turn_banner(msg["board"]))
                print(render_board(msg["board"]))
                print(view.turn_status(msg.get("next")))

            elif mtype == YOUR_TURN:
                col = prompt_column()
                if col is None:
                    print("Leaving the game (counts as a forfeit).")
                    break
                send(sock, build(MOVE, col=col))

            elif mtype == STATE:
                print(turn_banner(msg["board"]))
                print(render_board(msg["board"]))
                print(view.turn_status(msg.get("next")))

            elif mtype == ERROR:
                print(f"[{msg.get('code')}] {msg.get('message')}")

            elif mtype == RESULT:
                print("\n************ GAME OVER *************")
                if msg.get("board"):
                    print(render_board(msg["board"]))
                outcome, winner = msg.get("outcome"), msg.get("winner")
                if outcome == DRAW:
                    print("Result: Draw, the board is full.")
                elif outcome == WIN:
                    print("Result: You win!" if winner == args.name else f"Result: {view.label(winner)} wins.")
                elif outcome == FORFEIT:
                    print(f"Result: Opponent left or timed out. {view.label(winner)} wins by forfeit.")
                print(view.scores(msg.get("scores")))
                if msg.get("rematch"):
                    again = prompt_yes_no("Play again?")
                    send(sock, build(REMATCH, accept=again))
                    if again:
                        print("Waiting for opponent's answer...")

            elif mtype == CLOSE:
                print(f"Server closed the session: {msg.get('reason', '')}")
                break
    except KeyboardInterrupt:
        print("\nInterrupted, leaving the game.")
    except OSError as exc:
        print(f"[ERROR] Connection problem: {exc}")
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
