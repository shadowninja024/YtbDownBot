
import asyncio


class TGAction:

    def __init__(self, bot, chat_id, action, period=4):
        self.bot = bot
        self.action = action
        self.chat_id = chat_id
        self.period = period

    async def update(self):
        while True:
            await self.bot.send_chat_action(self.chat_id, self.action)
            await asyncio.sleep(self.period)

    async def __aenter__(self):
        self.task = asyncio.get_event_loop().create_task(self.update())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self.task:
            return
        if not self.task.cancelled():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass