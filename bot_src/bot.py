"""
Your bot logic. This file is hot-reloaded every tick — just save and your
changes are live in the running game.

    def play(bot, memory):
        bot     — the full BotAI instance (game state + actions)
        memory  — a dict that persists across reloads

Useful state (all from bot.*):
    .workers / .units / .structures       — your stuff
    .enemy_units / .enemy_structures      — visible enemies
    .minerals / .vespene                  — current resources
    .supply_used / .supply_left           — supply
    .townhalls / .gas_buildings           — bases and refineries
    .mineral_field / .vespene_geyser      — resource nodes on map
    .game_info.map_center                 — center of the map
    .start_location                       — your spawn
    .enemy_start_locations                — where they could be
    .time                                 — game time in seconds
    .already_pending(UnitTypeId.X)        — count of units in production

Sending commands:
    worker.gather(mineral_patch)          — harvest
    worker.attack(target)                 — attack-move
    unit.move(position)                   — move
    bot.do(unit.build(UnitTypeId.X, pos)) — build (returns bool)
    townhall.train(UnitTypeId.SCV)        — train a unit
"""

from sc2.ids.unit_typeid import UnitTypeId


async def play(bot, memory):
    # Gather idle workers
    for worker in bot.workers.idle:
        patch = bot.mineral_field.closest_to(worker)
        worker.gather(patch)
