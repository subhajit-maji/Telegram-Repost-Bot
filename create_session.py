# create_session.py (run locally where you can receive Telegram codes)
import asyncio
from telethon import TelegramClient
API_ID = int(Add App Api Id)
API_HASH = "Add App Api Hash"
client = TelegramClient('user_session', API_ID, API_HASH)
async def main():
    await client.start()   # will ask for phone -> code -> 2FA
    me = await client.get_me()
    print("Logged in:", me.username or me.first_name, me.id)
    await client.disconnect()
asyncio.run(main())