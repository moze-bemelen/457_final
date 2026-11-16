from typing import Optional

ROWS = 6
COLS = 7
EMPTY = "."


def create_board() -> list[list[str]]:
    #Return a 6x7 grid of EMPTY cells. Row 0 is the top.
    return [[EMPTY for _ in range(COLS)] for _ in range(ROWS)]


def drop_disc(board: list[list[str]], col: int, color: str) -> Optional[int]:
    """Place color (X or O / P1 or P2) in the lowest empty row of selected col
    returns the row index used, or None if the column is full.
    assume col is already range-checked by protocol.validate_incoming.
    """
    i = ROWS - 1
    while i >= 0:
        """ Top down indexing reversed for lowest available """  
        if board[i][col] == EMPTY:
            board[i][col] = color
            return i
        else:
            i -= 1
            continue

    return None #COLUMN FULL

def check_winner(board: list[list[str]]) -> Optional[str]:
    #check for a winner on the board...
    directions = [(0,1), (1,0), (1,1), (1,-1)] #right down dwon-right down-left
    for row in range(ROWS):
        for col in range(COLS):
            color = board[row][col]
            if color == EMPTY:
                continue
            for dr, dc in directions:
                end_r, end_c = row + 3 *dr, col + 3 * dc
                if not (0 <= end_r < ROWS and 0 <= end_c < COLS):
                    continue
                if all(board[row + i *dr][col + i * dc] == color for i in range(4)):
                    return color
    return None

def is_full(board: list[list[str]]) -> bool:
    # board is full when top row is completely full (no EMPTY cell left in row 0)
    top_row = board[0]
    for item in top_row:
        if item == EMPTY:
            return False
        else:
            continue
    return True

def column_has_space(board: list[list[str]], col: int) -> bool:
    # is top cell of column empty?
    return board[0][col] == EMPTY
