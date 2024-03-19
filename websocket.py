import asyncio
import websockets

async def main():
    uri = 'wss://tms35.nepsetms.com.np//tmsapi/socket?memberId=137&clientId=1974509&dealerId=&userId=36320'
    headers = {
        'Pragma': 'no-cache',
        'Origin': 'https://tms35.nepsetms.com.np',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cookie': 'REDACTED_CREDENTIAL',

        'Sec-WebSocket-Key': 'REDACTED_CREDENTIAL',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Upgrade': 'websocket',
        'Cache-Control': 'no-cache',
        'Sec-GPC': '1'
    }

    async with websockets.connect(uri, extra_headers=headers) as websocket:
        # Define the control messages
        control_messages = [
            '{"header":{"channel":"@control","transaction":"start_ticker"},"payload":{"argument":"undefined"}}',
            # '{"header":{"channel":"@control","transaction":"start_index"},"payload":{"argument":"undefined"}}',
            # '{"header":{"channel":"@control","transaction":"start_clientPortfolio"},"payload":{"argument":"undefined"}}',
            # '{"header":{"channel":"@control","transaction":"start_marketwatch"},"payload":{"argument":"undefined"}}',
        ]

        # Send all control messages first
        for message in control_messages:
            await websocket.send(message)

        # Continuously listen for responses
        count=0
        while True:
            response = await websocket.recv()
            print(response)
            count+=1
            print(count)

asyncio.run(main())
