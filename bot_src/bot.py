from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId


class MyBot(BotAI):
    async def on_step(self, iteration):
        # Gather idle workers
        for worker in self.workers.idle:
            patch = self.mineral_field.closest_to(worker)
            worker.gather(patch)
