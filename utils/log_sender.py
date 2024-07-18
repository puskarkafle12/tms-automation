# send_logs.py

import websockets

# Initialize active_websockets dictionary
active_websockets = {}

# Function to send logs to all connected clients
async def send_logs(logs: str):
    # Create a copy of the dictionary to avoid RuntimeError
    for ws, _ in list(active_websockets.items()):
        try:
            await ws.send_text(logs)
        except websockets.exceptions.ConnectionClosedError:
            del active_websockets[ws]
        except websockets.ConnectionClosedOK:
            del active_websockets[ws]
