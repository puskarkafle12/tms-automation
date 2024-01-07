import asyncio
import websockets

async def connect_to_websocket():
    # Construct the WebSocket URL with query parameters
    uri = "wss://tms35.nepsetms.com.np//tmsapi/socket?memberId=137&clientId=1974509&dealerId=1&userId=36320&access_token=eyJhbGciOiJIUzI1NiJ9.eyJqdGkiOiIzNjMyMCIsImlhdCI6MTY5NjM4NzQzNiwic3ViIjoiTUFELVJVQyxGTS1SVUExQ0EyREEzLE1JTkZPLVIsT00tUlVDLFNCSS1SVUExQ0EyREEzLExGLVJVQTFDQTJEQTMsR0wtUixUQi1SVUUMS1FZFA5LTzY1FLE1XzU+UjlYzMyNjA0GhdTTzIwU1NZLA=="

    # Define the WebSocket message
    message = '{"header":{"channel":"@control","transaction":"start_index"},"payload":{"argument":"undefined"}}'

    try:
        # Create a custom WebSocket handshake request with headers
        async with websockets.connect(uri) as websocket:
            # WebSocket connection is established, you can send and receive messages here.
            # Sending the specified JSON message:
            await websocket.send(message)

            # Receiving a response:
            response = await websocket.recv()
            print(f"Received response: {response}")

    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(connect_to_websocket())
