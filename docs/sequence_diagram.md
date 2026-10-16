```mermaid  
sequenceDiagram
    autonumber
    actor Client1 as Client 1 (Player X)
    participant Server as Connect-4 Server
    actor Client2 as Client 2 (Player O)

    Client1 ->>Server: Connect
    Client2 ->>Server: Connect

    Note over Server: Initiate OS Event loop

    Server ->>Client1: Broadcast Starting Game State
    Server ->>Client2: Broadcast Starting Game State
    
    Note over Server: Set Client1 as active Player and await read/write from Client1

    rect rgba(3, 68, 14, 1)
        loop Valid game continuation
            Note over Client1: Client1 player accesses terminal to place game-piece
            Client1->>Server: Place (col: 2)
            Note over Server: Server validates: Is it Client 1's turn?<br>Is cell (2) not full and valid column?
            alt Server Validates Move
                alt Server identifies game end
                    Server-->>Client1: STATE_UPDATE (Game end & winner result, scoreboard, play again prompt)
                    Server-->>Client2: STATE_UPDATE (Game end & winner result, scoreboard, play again prompt)
                else Game Continues
                    Note over Server: Update Game Board<br>Switch Active Turn to Player 2
                    Server-->>Client1: STATE_UPDATE (Game-Board, Turn: Player 2)
                    Server-->>Client2: STATE_UPDATE (Game-Board, Turn: Player 2)
                    Note over Client2: Client2 accesses terminal to place game piece
                    Client2 ->> Server: Place (col: 5)
                    Note over Server: Game continues until error or game end
                end
            end
        end
    end

    rect rgba(61, 3, 3, 1)
        loop ___Errors, misuse, and abuse
            alt Invalid placement
                Server-->>Client1: ERROR ("Invalid game piece placement")
            else Player attempts out of turn write access
                Server-->>Client2: ERROR ("NO WRITE ACCESS: Action out of order, player set for next move is not this client")
            else Improper Payload
                Server-->>Client1: ERROR ("Unknown Input, see usage and attempt transmission again")
            else Abuse Case (WIP)
                Note over Server: This is hypothetical that abuse was from Client1
                Server-->>Client2: ERROR ("Unexpected game end, server malfunction detected")
                Server-->>Client1: ERROR ("ABUSE DETECTED: CONNECTION TERMINATED")
            end
        end
    end

