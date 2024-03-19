import asyncio
import websockets

async def main():
    uri = 'wss://tms35.nepsetms.com.np//tmsapi/socket?memberId=137&clientId=1974509&dealerId=&userId=36320'
    headers = {
        'Pragma': 'no-cache',
        'Origin': 'https://tms35.nepsetms.com.np',
        'Accept-Language': 'en-US,en;q=0.9',
        'Cookie': 'pdfcc=2; _rid=eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..vyfw8_QV6vgk0_05.1nAEYYuMpAK8yRw2GbdreSBRnSxI7hyGCM_Vmv5izSouPGuwquWpKnQaH-xGy0A2WWlfOP_lit1ROdtG5pkKMRU_QTzvRzi14oeqJQEb_p8VQEb2PCG6PMVRrcQJkmJnwY7VuiZlMxfzQN8yk9O_IXH4ldaKma02lrGFUeeYTLJFhGIdKOt9nQbyxxFKHcYL-DbU__7xBf5IjVK1UXtM3lhWoq50nYRC5ycSGHSjL795Sl5bZeet2KSrFBelEafqFSqMKdvwEO-A4D_JmmJeozFrThI-QoFMYaaHs-pnIRNDx3IzKnqlYCsyTwmGHys5cFadLS3gfG8UsIrRlv_C2p24PZA4Rzvi1gqccWBwyQfkszmMGABJMYiGwNOWG6cwk4N-r6bYYaUT4G-6KmPo1ss3H341KOkhORZK2au8Vh4mNi7nfPb_AyrURp1oF2Q8Tb_lK28ElcMMlXRVZsYMNjC1dEKFnP0oUOMfULtydTuFyjEpr1ViOH-au2Cs_jkJj8-pORJXNqPKi0KmSn1FAfsJ0oTt0YjKxC_wzDHkOVugrVUSHB7b4j7amBtYN652LO0.R2b-ewLmnjVtua3Ua2XTYA; _aid=eyJlbmMiOiJBMTI4R0NNIiwiYWxnIjoiZGlyIn0..UD89FYTZf6vnomYH.Ez1brVtAYHKiZgXN5k7YedWuXkyfeEWOhUzsTC1OjYBXHZGfQ008ASHEHv8jRFc6IA11-4EPfIcMPx7rAxViFVhV_2Jeji1kcHdBvs0clIWEBRXVCj-4PiMyPVG99BeqU9c2nQl44HNAzv5_aR3p2rr2-9qYiWIGgNAfMOWeZx62vh2JBBmmXW6cfONBjDwt7wyHLtFjGU7A-1IlegVbbyk6mfbFynuFczpickmOpUe7jUkqCRQRH5SbhrRHoyjuqHouAwtk98rYiX_N2UO1G9s0gFplsFksbBq_1Rg4OqaVS3vK1nobC-tjTi_eontOM1Ez8GY9hbuGNidW0i0TQBxUtioPQLW3erj_m7wxYOMCRF4gV9EIU9qaaUz5TBmR84TyRJJKOUIevYlm0beLEE8SBxoAwp7YQ1lOtjBctHT8E_AH8am-AFQe7RxHK3BGS-A58w1M2QL-ysGrGgAfSuT1gXsqwxQTyZ4LvVt4V65DbW-wXF1wPFlAXb7TuCSP0RhbK5sClgjAht4PLOuggXhdhQm585prTITGTvUdWlL6xetXqW8aYCvQ9K4v15-6ZD4.cZNxegIYC92BZaJFLeFsDQ; XSRF-TOKEN=3bfbe976-89de-45a3-a5a4-19acec428c81',

        'Sec-WebSocket-Key': 'ReNjK4R8wr9pTTW9SaKPng==',
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
