# Concurrency Architecture Design Documentation
## Non-Blocking I/O Multiplexing implementation design for Connect-4
### Chosen Concurrency Architecture Background
  Non-Blocking I/O Multiplexing is a method of concurrently servicing multiple connections at once. In this project's case, we only need to service two clients from a single server
  at any given time. This makes the above architecture desirable over multi-threading (threading.Thread / socketserver.ThreadingTCPServer), where the latter has a higher overhead at the 
  tradeoff of higher concurrent client servicing capabilities. I/O Multiplexing was chosen over multi-threading simply because we only need to service two clients transferring relatively 
  simple data to play Connect-4 in a terminal. I/O Multiplexing utilizes event blocking in a register of multiple open sockets to service client events. By blocking in a while loop and 
  continuously checking for one or multiple clients having I/O read or write events ready, a **_selector_** (described below) can service multiple client events concurrently.
### Non-Blocking I/O Multiplexing in Python Using _Selectors_ Class
  The Python **_selectors_** class is a higher-level form of the classic Python **_select_** class. **_selectors_** utilizes sockets creating in non-blocking mode to ensure sockets do
  not block the entire server until it returns. These non-blocking sockets are registered in a **_selectors_** cache and serviced. **_selectors_** services each socket caught in 
  the while true loop iteratively, meaning if multiple sockets are caught in the same loop, **_selectors_** will service the first and then second socket before returning to a blocking
  state. To service each socket **_selectors_** will take a socket out of the caught registrar and determine based off of the socket (key, mask) tuple whether or not the socket is from
  the listening socket or if its a pre-established and accepted client socket. If the socket caught is from the listening socket, it will be parsed into a accept() method implemented to
  handle setting blocking to false, assigned data, events expected from socket, and finally added to the list of sockets **_selectors_** is handling. If the socket was a pre-established
  client socket, the (key, mask) tuple is parsed into a client connection handler function. **This function will be implemented to ensure that the entirety**
  
### Thread Safety Analysis & Lock Acquisition Strategy
  Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."
## State and Score Broadcast Sequence
### Link to diagram
  Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."

## Score and Leaderboard Synchronization Design
### Score Broadcast Mechanism
  Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."

