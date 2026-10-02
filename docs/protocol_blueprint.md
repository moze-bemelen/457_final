# Application Protocol & Game State Machine (FSM) Design Blueprint
## Transport Layer & Packet Framing Mechanism
  Transport Protocol: TCP
    Transmission Control Protocol (TCP) is a main data transmission protocol of the internet protocol (IP) suite. TCP is utilized
    to provide a reliable data stream between hosts on computers within the internet protocol. TCP utilizes a three-way
    handshake to initialize connection. Utilizing reserved bits in the TCP header, the protocol provides retransmission for dropped
    packets, ordered packet formatting, error-checking, and data integrity (checksum)
  Serialization Format: Structured JSON (or delimited text / binary - student choice)
  Framing Rule Requirement:
  
### 
