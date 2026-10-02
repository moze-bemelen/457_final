# Application Protocol & Game State Machine (FSM) Design Blueprint
## Transport Layer & Packet Framing Mechanism
  - Transport Protocol: **TCP**  
    Transmission Control Protocol (TCP) is a main data transmission protocol of the internet protocol (IP) suite. TCP is utilized  
    to provide a reliable data stream between hosts on computers within the internet protocol. TCP utilizes a three-way  
    handshake to initialize connection. Utilizing reserved bits in the TCP header, the protocol provides retransmission for dropped  
    packets, ordered packet formatting, error-checking, and data integrity (checksum)  
      
  - Serialization Format: **Structured JSON**  
    Structured JSON is a data representation format that will be utilized in this project as a payload for TCP communications  
    to relay game state, player moves, and possibly more. JSON is Java Script Object Notation, although initially made for   
    JavaScript applications, JSON is utilized and implemented in almost all modern programming languages. Its use  
    will not be extensive in this project but certainly vital.  
      
  - Framing Rule Requirement: **Length-Prefixed Framing (Fixed-Width Binary Header)**   
    Length-Prefixed Framing or Fixed-Width Binary Header is a formatting schema utilized to prevent coalescing or  
    fragmentation in data transmission in TCP. Multiple messages sent in a stream i.e. back to back may result  
    in messages being split and received within the same recv() TCP call. Coalescing is when multiple messages are  
    received in the same recv() call and fragmentation is when a message is split between two. To avoid cleaning up  
    either state when it occurs, Length-Prefixed Framing will be utilized in this project to explicitly define when  
    to delimit message boundaries on the wire.  

    Length-Prefixed framing delimits messages by affixing a Big-Endian binary header with a fixed size to the beginning  
    of each message to be sent across. This header specifies the exact length in bytes of the expected payload so after  
    the receiver reads the header it know exactly how many bytes to read from the stream before parsing.  
    Length-Prefixed framing has several benefits relevant to this project's design.
      
    An example of what several messages may look like in stream is below.
    ```
    [4-Byte Length: 0x00000045 (69 bytes)] {"msg_type":"CONNECT","player_id":"Alice","timestamp":1727000000}
    [4-Byte Length: 0x0000005C (92 bytes)] {"msg_type":"MOVE","player_id":"Alice","payload":{"row":0,"col":2},"timestamp":1727000005}
    ```
      
## Application Message Types  
  ### The table below explicitly defines message structures for all client-server communications
   
  | Message Type | Direction | Purpose & Description |
  | ------------ | --------- | --------------------- |
  | CONNECT | CLIENT -> SERVER | **CONNECT** serves as an initial call for a client to request to join a matchmaking lobby. CONNECT requires the user to set a player username or alias |
  | MATCHMAKING | SERVER -> CLIENT | **MATCHMAKING** notifies a client that a **CONNECT** message was valid and received and that the game lobby is currently waiting for a secondary player to connect before game initialization |
  | GAME_BEGIN | SERVER -> CLIENTS | **GAME_BEGIN** is a global message sent to both clients from the server to notify the beginning of the game. This message will likely be followed immediately with a **STATE_UPDATE** message to relay both clients the starting game state. **GAME_BEGIN** may also provide a short usage/rule description of the game although this may be provided in the **MATCHMAKING** message or not implemented at all.  |
  | PLACE | CLIENT -> SERVER | **PLACE** is sent from client to server to detail when a player would like to place a CONNECT-4 token in a chosen column when it is their turn. |
  | STATE_UPDATE | SERVER -> CLIENTS | **STATE_UPDATE** is sent by server to both clients to update the game state which includes board, previous player moves shown graphically on board, and active player turn. |
  | ERROR | SERVER -> CLIENT | **ERROR** is sent to a client from the server when a player attempts to make a unauthorized or illegal move within the game. This includes out-of-turn moves, improper placement or a malformed message. |
  | DISCONNECT | CLIENT -> SERVER | **DISCONNECT** sent from client to server when a Client intentionally decides to disconnect or "quit" the game early. This will result in a graceful exit and closure of connection for both clients. |
  | GAME_RESULT | SERVER -> CLIENTS | **GAME_RESULT** |
  
