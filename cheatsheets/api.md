# python-sc2 API Cheatsheet

## Imports

```python
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.buff_id import BuffId
from sc2.ids.effect_id import EffectId
from sc2.position import Point2
from sc2.data import Race, Result, Alert
```

## Entry point

Define a `BotAI` subclass in `bot_src/bot.py`:

```python
from sc2.bot_ai import BotAI

class MyBot(BotAI):
    async def on_step(self, iteration):
        ...  # called every tick

    async def on_start(self):
        ...  # called once at game start

    def on_reload(self):
        ...  # called on every hot-reload (optional)
```

`self` is the live BotAI instance — use `self.workers`, `self.minerals`, etc.
Instance variables on `self` persist across reloads. `bot_src/` is hot-reloaded
every tick. Errors are caught and logged without crashing.

---

## Resource & supply state

| Property | Type | Description |
|---|---|---|
| `bot.minerals` | `int` | Current minerals |
| `bot.vespene` | `int` | Current vespene gas |
| `bot.supply_cap` | `int` | Total supply cap |
| `bot.supply_used` | `int` | Supply currently used |
| `bot.supply_left` | `int` | `supply_cap - supply_used` |
| `bot.supply_army` | `int` | Supply used by army |
| `bot.supply_workers` | `int` | Supply used by workers |
| `bot.idle_worker_count` | `int` | Idle workers |
| `bot.army_count` | `int` | Army unit count |
| `bot.warp_gate_count` | `int` | Warp gates (Protoss) |
| `bot.time` | `float` | Game time in seconds |
| `bot.time_formatted` | `str` | `"MM:SS"` |
| `bot.race` | `Race` | Your race |
| `bot.enemy_race` | `Race` | Enemy race (may be `Race.Random` until scouted) |
| `bot.realtime` | `bool` | Realtime mode flag |
| `bot.state.game_loop` | `int` | Current frame (22.4 per second at Faster) |
| `bot.units_created` | `Counter` | Counter of all unit types created this game |

---

## Unit collections

All are `Units` objects, updated every tick.

| Property | Description |
|---|---|
| `bot.units` | Own non-structure units (includes workers and larva) |
| `bot.workers` | Own workers (SCV/Probe/Drone) |
| `bot.larva` | Zerg larva |
| `bot.structures` | All own structures (including under construction) |
| `bot.townhalls` | Own townhalls (CC/Nexus/Hatch/Lair/Hive and variants) |
| `bot.gas_buildings` | Own Refinery/Assimilator/Extractor |
| `bot.all_own_units` | All own units + structures |
| `bot.enemy_units` | Visible enemy non-structure units |
| `bot.enemy_structures` | Visible enemy structures |
| `bot.all_enemy_units` | All visible enemy units + structures |
| `bot.all_units` | Everything visible on the map |
| `bot.mineral_field` | Neutral mineral fields |
| `bot.vespene_geyser` | Neutral vespene geysers |
| `bot.resources` | Mineral fields + geysers |
| `bot.destructables` | Destructable rocks/debris |
| `bot.watchtowers` | Xel'Naga watch towers |
| `bot.placeholders` | Protoss building placeholders |
| `bot.blips` | `set[Blip]` — sensor tower detections |
| `bot.techlab_tags` | `set[int]` — tags of techlab addons |
| `bot.reactor_tags` | `set[int]` — tags of reactor addons |

---

## Unit properties

Every unit/structure is a `Unit` object.

### Identity

| Property | Type | Description |
|---|---|---|
| `unit.type_id` | `UnitTypeId` | e.g. `UnitTypeId.MARINE` |
| `unit.tag` | `int` | Unique ID for this unit |
| `unit.name` | `str` | Human-readable name |
| `unit.race` | `Race` | Unit's race |

### Position & movement

| Property | Type | Description |
|---|---|---|
| `unit.position` | `Point2` | 2D position |
| `unit.position3d` | `Point3` | 3D position with z |
| `unit.position_tuple` | `tuple` | `(x, y)` — faster than `.position` |
| `unit.facing` | `float` | Direction in radians `[0, 2pi)` |
| `unit.radius` | `float` | Collision radius |
| `unit.movement_speed` | `float` | Base speed (normal game speed) |
| `unit.real_speed` | `float` | Actual speed with upgrades/buffs/creep |
| `unit.distance_per_step` | `float` | Distance unit travels per game step |

| Method | Returns | Description |
|---|---|---|
| `unit.distance_to(target)` | `float` | Distance to unit or point |
| `unit.is_facing(other_unit, angle_error=0.05)` | `bool` | Facing toward other unit |

### Health / shield / energy

| Property | Type | Description |
|---|---|---|
| `unit.health` | `float` | Current HP |
| `unit.health_max` | `float` | Max HP |
| `unit.health_percentage` | `float` | `health / health_max` |
| `unit.shield` | `float` | Current shield (Protoss, else 0) |
| `unit.shield_max` | `float` | Max shield |
| `unit.shield_percentage` | `float` | `shield / shield_max` |
| `unit.shield_health_percentage` | `float` | `(shield+hp) / (shield_max+hp_max)` |
| `unit.energy` | `float` | Current energy (spellcasters) |
| `unit.energy_max` | `float` | Max energy |
| `unit.energy_percentage` | `float` | `energy / energy_max` |

### Combat

| Property | Type | Description |
|---|---|---|
| `unit.can_attack` | `bool` | Has any weapon |
| `unit.can_attack_ground` | `bool` | Can attack ground units |
| `unit.can_attack_air` | `bool` | Can attack air units |
| `unit.ground_dps` | `float` | DPS vs ground (no upgrades) |
| `unit.air_dps` | `float` | DPS vs air (no upgrades) |
| `unit.ground_range` | `float` | Attack range vs ground |
| `unit.air_range` | `float` | Attack range vs air |
| `unit.armor` | `float` | Armor value (no upgrades) |
| `unit.sight_range` | `float` | Vision range |
| `unit.weapon_cooldown` | `float` | Frames until next attack; -1 if can't attack |
| `unit.weapon_ready` | `bool` | `weapon_cooldown == 0` |
| `unit.attack_upgrade_level` | `int` | 0/1/2/3 |
| `unit.armor_upgrade_level` | `int` | 0/1/2/3 |
| `unit.bonus_damage` | `tuple\|None` | `(bonus_dmg, type)` e.g. `(10, 'Light')` |

| Method | Returns | Description |
|---|---|---|
| `unit.target_in_range(target, bonus_distance=0)` | `bool` | Can attack target from current position |
| `unit.in_ability_cast_range(ability_id, target, bonus_distance=0)` | `bool` | Ability in range |
| `unit.calculate_dps_vs_target(target)` | `float` | DPS accounting for armor/type |

### Status flags

| Property | Type | Description |
|---|---|---|
| `unit.is_mine` | `bool` | Belongs to you |
| `unit.is_enemy` | `bool` | Belongs to enemy |
| `unit.is_structure` | `bool` | Is a building |
| `unit.is_light` | `bool` | Light attribute |
| `unit.is_armored` | `bool` | Armored attribute |
| `unit.is_biological` | `bool` | Biological attribute |
| `unit.is_mechanical` | `bool` | Mechanical attribute |
| `unit.is_massive` | `bool` | Massive attribute |
| `unit.is_flying` | `bool` | Currently flying |
| `unit.is_burrowed` | `bool` | Currently burrowed |
| `unit.is_cloaked` | `bool` | Cloaked |
| `unit.is_revealed` | `bool` | Cloaked but detected |
| `unit.can_be_attacked` | `bool` | Not cloaked, or revealed |
| `unit.is_detector` | `bool` | Is a ready detector |
| `unit.is_hallucination` | `bool` | Is a hallucination |
| `unit.is_idle` | `bool` | No orders |
| `unit.is_ready` | `bool` | `build_progress == 1` |
| `unit.build_progress` | `float` | `[0.0, 1.0]` |
| `unit.is_powered` | `bool` | Protoss: powered by pylon |
| `unit.is_visible` | `bool` | Currently visible (not fog snapshot) |
| `unit.is_snapshot` | `bool` | Fog-of-war snapshot |
| `unit.is_selected` | `bool` | Selected by human player |

### Worker / harvester

| Property | Type | Description |
|---|---|---|
| `unit.is_idle` | `bool` | No orders |
| `unit.is_gathering` | `bool` | Walking to resource to mine |
| `unit.is_returning` | `bool` | Returning resource to townhall |
| `unit.is_collecting` | `bool` | Gathering or returning |
| `unit.is_carrying_minerals` | `bool` | Carrying minerals |
| `unit.is_carrying_vespene` | `bool` | Carrying gas |
| `unit.is_constructing_scv` | `bool` | SCV building (Terran) |
| `unit.is_repairing` | `bool` | SCV/MULE repairing |
| `unit.assigned_harvesters` | `int` | Workers assigned (townhall/gas) |
| `unit.ideal_harvesters` | `int` | Optimal worker count |
| `unit.surplus_harvesters` | `int` | `assigned - ideal` (negative = needs more) |

### Resource node properties

| Property | Type | Description |
|---|---|---|
| `unit.mineral_contents` | `int` | Minerals remaining in patch |
| `unit.vespene_contents` | `int` | Gas remaining in geyser |
| `unit.has_vespene` | `bool` | Geyser not empty |
| `unit.is_mineral_field` | `bool` | Is a mineral patch |
| `unit.is_vespene_geyser` | `bool` | Is a geyser |

### Orders

| Property | Type | Description |
|---|---|---|
| `unit.orders` | `list[UnitOrder]` | Current order queue |
| `unit.order_target` | `int\|Point2\|None` | Target of first order |
| `unit.is_moving` | `bool` | Has move order |
| `unit.is_attacking` | `bool` | Has attack order |
| `unit.is_using_ability(ability_id_or_set)` | `bool` | Using specific ability |
| `unit.buffs` | `frozenset[BuffId]` | Active buffs |
| `unit.has_buff(BuffId.X)` | `bool` | Has specific buff |

### Add-ons (Terran)

| Property | Type | Description |
|---|---|---|
| `unit.add_on_tag` | `int` | Addon tag (0 if none) |
| `unit.has_add_on` | `bool` | Has any addon |
| `unit.has_techlab` | `bool` | Has techlab |
| `unit.has_reactor` | `bool` | Has reactor |
| `unit.add_on_position` | `Point2` | Where addon goes for this structure |

### Cargo

| Property | Type | Description |
|---|---|---|
| `unit.passengers` | `set[Unit]` | Units inside |
| `unit.cargo_used` | `int` | Cargo space used |
| `unit.cargo_max` | `int` | Max cargo |
| `unit.has_cargo` | `bool` | Has any passengers |

---

## Unit commands

All return `UnitCommand`. Use `queue=True` to queue after current order.

```python
unit.attack(target)                    # target: Unit or Point2
unit.move(position)                    # position: Point2 or Unit
unit.stop()
unit.hold_position()
unit.patrol(position)
unit.gather(target)                    # target: mineral field or gas building
unit.return_resource()                 # return to nearest townhall
unit.repair(target)                    # SCV/MULE only
unit.smart(target)                     # right-click equivalent
unit.train(UnitTypeId.SCV)             # from production building
unit.build(UnitTypeId.BARRACKS, pos)   # from worker
unit.build_gas(geyser_unit)            # build race-appropriate gas building
unit.research(UpgradeId.STIMPACK)      # from research building
unit.warp_in(UnitTypeId.ZEALOT, pos)   # Protoss warpgate only
```

Generic ability call:
```python
unit(AbilityId.EFFECT_STIM)                        # self-cast
unit(AbilityId.CALLDOWNMULE_CALLDOWNMULE, target)  # targeted
unit(AbilityId.EFFECT_BLINK_STALKER, position)     # ground-targeted
```

---

## Units collection

`Units` is a `list[Unit]` subclass with filtering and query methods.

### Type filtering

```python
bot.units(UnitTypeId.MARINE)                           # shorthand for of_type
bot.units({UnitTypeId.MARINE, UnitTypeId.MARAUDER})    # multiple types
units.of_type(UnitTypeId.MARINE)                       # same as calling
units.exclude_type(UnitTypeId.OVERLORD)                # exclude types
units.same_tech({UnitTypeId.HATCHERY})                 # includes Lair/Hive
units.same_unit(UnitTypeId.ROACH)                      # includes burrowed form
```

### Property filters (all return `Units`)

| Filter | Description |
|---|---|
| `.idle` | `is_idle == True` |
| `.ready` | `build_progress == 1` |
| `.not_ready` | Under construction |
| `.flying` | Currently flying |
| `.not_flying` | On ground |
| `.gathering` | Mining resources |
| `.returning` | Returning resources |
| `.collecting` | Mining or returning |
| `.visible` | Currently visible |
| `.prefer_idle` | Sorted with idle first |

### Custom filtering

```python
units.filter(lambda u: u.health_percentage < 0.5)
units.sorted(key=lambda u: u.health, reverse=True)
```

### Distance queries

| Method | Returns | Description |
|---|---|---|
| `.closest_to(pos)` | `Unit` | Nearest unit to position |
| `.furthest_to(pos)` | `Unit` | Farthest unit from position |
| `.closest_distance_to(pos)` | `float` | Distance to nearest unit |
| `.closer_than(dist, pos)` | `Units` | All within distance |
| `.further_than(dist, pos)` | `Units` | All beyond distance |
| `.in_distance_between(pos, d1, d2)` | `Units` | Between d1 and d2 |
| `.closest_n_units(pos, n)` | `Units` | N nearest units |
| `.furthest_n_units(pos, n)` | `Units` | N farthest units |
| `.sorted_by_distance_to(pos)` | `Units` | Sorted by distance |
| `.in_attack_range_of(unit, bonus_distance=0)` | `Units` | In attack range of given unit |
| `.in_distance_of_group(other_units, dist)` | `Units` | Within dist of any unit in group |

### Properties

| Property | Type | Description |
|---|---|---|
| `.amount` | `int` | `len(units)` |
| `.empty` | `bool` | `len == 0` |
| `.exists` | `bool` | `len > 0` |
| `.first` | `Unit` | First unit (asserts non-empty) |
| `.random` | `Unit` | Random unit (asserts non-empty) |
| `.random_or(other)` | `Unit\|Any` | Random or fallback if empty |
| `.center` | `Point2` | Geometric center |
| `.tags` | `set[int]` | All unit tags |

### Set operations

```python
units_a | units_b    # union (no duplicates)
units_a + units_b    # same as union
units_a & units_b    # intersection
units_a - units_b    # difference
```

### Tag filtering

```python
units.find_by_tag(tag)      # -> Unit | None
units.by_tag(tag)           # -> Unit (raises KeyError)
units.tags_in(tag_set)      # -> Units
units.tags_not_in(tag_set)  # -> Units
```

### Slicing

```python
units.take(n)               # first n units
units.random_group_of(n)    # n random units
```

---

## Economy helpers

```python
bot.can_afford(UnitTypeId.MARINE)                  # checks minerals, gas, and supply
bot.can_afford(UpgradeId.STIMPACK)                 # works for upgrades too
bot.can_afford(UnitTypeId.MARINE, check_supply_cost=False)  # skip supply check

bot.calculate_cost(UnitTypeId.MARINE)              # -> Cost(minerals=50, vespene=0)
bot.calculate_cost(UnitTypeId.RAVAGER)             # morph cost: Cost(25, 75)

bot.can_feed(UnitTypeId.MARINE)                    # supply_left >= supply cost
bot.calculate_supply_cost(UnitTypeId.ZERGLING)     # -> 1 (spawns pair)
bot.calculate_unit_value(UnitTypeId.MARINE)        # -> Cost (raw API value)
```

---

## Building placement

```python
# Find valid placement near a position
pos = await bot.find_placement(UnitTypeId.BARRACKS, near=bot.start_location)
pos = await bot.find_placement(UnitTypeId.BARRACKS, near=pos, addon_place=True)  # room for addon

# Check specific position
ok = await bot.can_place_single(UnitTypeId.BARRACKS, pos)

# Batch check
results = await bot.can_place(UnitTypeId.BARRACKS, [pos1, pos2, pos3])  # -> list[bool]

# Select nearest available worker
worker = bot.select_build_worker(pos)             # nearest idle/gathering worker
worker = bot.select_build_worker(pos, force=True)  # any worker if none idle
```

---

## High-level actions

### Building

```python
# All-in-one: find placement, select worker, issue build order
success = await bot.build(UnitTypeId.BARRACKS, near=bot.start_location)
success = await bot.build(UnitTypeId.BARRACKS, near=pos, max_distance=20, build_worker=specific_worker)
```

### Training

```python
# High-level: train from appropriate idle structures
count = bot.train(UnitTypeId.MARINE, amount=4)       # returns number queued
count = bot.train(UnitTypeId.MARINE, closest_to=pos)  # prefer closest structure
# Handles reactors (queues 2), warpgates, tech requirements automatically
```

### Research

```python
# High-level: research from appropriate idle structure
success = bot.research(UpgradeId.STIMPACK)  # returns True if started
```

### Expansion

```python
await bot.expand_now()                              # auto-select next expansion
await bot.expand_now(building=UnitTypeId.HATCHERY)  # specify townhall type

next_exp = await bot.get_next_expansion()           # -> Point2 | None (nearest open)
```

### Worker distribution

```python
await bot.distribute_workers()                # basic auto-distribution
await bot.distribute_workers(resource_ratio=2)  # minerals:gas worker ratio
```

---

## Tech progress

| Method | Returns | Description |
|---|---|---|
| `bot.already_pending(UnitTypeId.BARRACKS)` | `float` | Count in production + en route |
| `bot.already_pending(UpgradeId.STIMPACK)` | `float` | 0 / progress / 1 |
| `bot.already_pending_upgrade(UpgradeId.STIMPACK)` | `float` | 0 (not started), 0<x<1, or 1 (done) |
| `bot.tech_requirement_progress(UnitTypeId.BARRACKS)` | `float` | Progress of prerequisite building |
| `bot.structure_type_build_progress(UnitTypeId.FACTORY)` | `float` | 0/progress/1 for best instance |
| `bot.worker_en_route_to_build(UnitTypeId.BARRACKS)` | `float` | Workers walking to build this |
| `bot.structures_without_construction_SCVs` | `Units` | Terran: unattended buildings |

### Completed upgrades

```python
if UpgradeId.STIMPACK in bot.state.upgrades:
    # stimpack is done
```

---

## Map & terrain

| Property / Method | Type | Description |
|---|---|---|
| `bot.start_location` | `Point2` | Your spawn |
| `bot.enemy_start_locations` | `list[Point2]` | Possible enemy spawns |
| `bot.expansion_locations_list` | `list[Point2]` | All expansion positions |
| `bot.expansion_locations_dict` | `dict[Point2, Units]` | Expansions -> resources (slower) |
| `bot.owned_expansions` | `dict[Point2, Unit]` | Your expansions -> townhalls |
| `bot.main_base_ramp` | `Ramp` | Your main base ramp |
| `bot.game_info.map_center` | `Point2` | Center of playable area |
| `bot.game_info.map_size` | `Size` | Total map size |
| `bot.game_info.map_ramps` | `list[Ramp]` | All ramps on map |
| `bot.is_visible(pos)` | `bool` | Have vision at pos |
| `bot.has_creep(pos)` | `bool` | Zerg creep at pos |
| `bot.in_pathing_grid(pos)` | `bool` | Ground unit can walk through pos |
| `bot.in_placement_grid(pos)` | `bool` | Can place building at pos |
| `bot.in_map_bounds(pos)` | `bool` | Within playable area |
| `bot.get_terrain_height(pos)` | `int` | Height 0-255 |
| `bot.get_terrain_z_height(pos)` | `float` | Z height -16 to +16 |

---

## GameInfo & Ramp

```python
ramp = bot.main_base_ramp
ramp.top_center          # Point2 — top of ramp
ramp.bottom_center       # Point2 — bottom of ramp
ramp.upper               # frozenset[Point2] — upper tiles
ramp.lower               # frozenset[Point2] — lower tiles
ramp.size                # int — number of points

# Terran wall positions:
ramp.barracks_in_middle            # Point2 | None
ramp.barracks_correct_placement    # Point2 | None (adjusted for addon)
ramp.corner_depots                 # set[Point2] (2 depot positions)
ramp.depot_in_middle               # Point2 | None
ramp.barracks_can_fit_addon        # bool

# Protoss wall positions:
ramp.protoss_wall_pylon            # Point2 | None
ramp.protoss_wall_buildings        # frozenset[Point2] (2 building positions)
ramp.protoss_wall_warpin           # Point2 | None (blocks gap)
```

---

## Point2 geometry

```python
pos.distance_to(other)                        # float — distance
pos.towards(target, distance=1)               # Point2 — move toward target
pos.towards(target, -3)                       # move away from target
pos.offset((dx, dy))                          # Point2 — add offset
pos.random_on_distance(5)                     # Point2 — random point 5 away
pos.random_on_distance((3, 7))                # random in distance range
pos.towards_with_random_angle(target, dist)   # toward target with angle jitter
pos.neighbors4                                # set[Point2] — 4 adjacent grid points
pos.neighbors8                                # set[Point2] — 8 surrounding
pos.normalized                                # Point2 — unit vector
pos.length                                    # float — magnitude
pos.manhattan_distance(other)                 # float
pos.direction_vector(other)                   # Point2 — -1/0/+1 components
Point2.center(points_list)                    # Point2 — centroid

# Arithmetic
pos1 + pos2       # offset
pos1 - pos2       # subtract
pos * scalar      # scale
pos / scalar      # divide
```

---

## Event callbacks

Override in BotAI subclass (the harness implements these; useful for understanding when things happen):

| Callback | Args | When |
|---|---|---|
| `on_start` | `()` | Game start (all data available) |
| `on_step` | `(iteration)` | Every game step |
| `on_end` | `(game_result)` | Game over |
| `on_unit_created` | `(unit)` | Your unit created/trained |
| `on_unit_destroyed` | `(unit_tag)` | Any visible unit dies (tag only) |
| `on_unit_type_changed` | `(unit, previous_type)` | Unit morphs |
| `on_building_construction_started` | `(unit)` | Building placed |
| `on_building_construction_complete` | `(unit)` | Building finished |
| `on_upgrade_complete` | `(upgrade)` | Upgrade finished |
| `on_unit_took_damage` | `(unit, amount)` | Your unit/structure damaged |
| `on_enemy_unit_entered_vision` | `(unit)` | Enemy becomes visible |
| `on_enemy_unit_left_vision` | `(unit_tag)` | Enemy leaves vision |

---

## Game state extras

### Effects (active abilities on the ground)

```python
for effect in bot.state.effects:
    effect.id           # EffectId (e.g. EffectId.RAVAGERCORROSIVEBILECP)
    effect.positions    # set[Point2]
    effect.alliance     # Alliance
    effect.is_enemy     # bool
    effect.radius       # float
```

### Score

```python
bot.state.score.collection_rate_minerals    # current mineral income
bot.state.score.collection_rate_vespene     # current gas income
bot.state.score.killed_value_units          # total army value killed
bot.state.score.total_damage_dealt_life     # total damage dealt
bot.state.score.current_apm                 # actions per minute
```

### Alerts

```python
if bot.alert(Alert.NuclearLaunchDetected):
    # react!
# Other alerts: BuildingUnderAttack, UnitUnderAttack, BuildingComplete, etc.
```

### Available abilities

```python
abilities = await bot.get_available_abilities([unit])  # -> list[list[AbilityId]]
can = await bot.can_cast(unit, AbilityId.EFFECT_STIM)  # -> bool
```

### Previous frame maps

```python
bot._units_previous_map           # dict[tag, Unit] — own units last frame
bot._structures_previous_map      # dict[tag, Unit] — own structures last frame
bot._enemy_units_previous_map     # dict[tag, Unit] — enemy units last frame
bot._enemy_structures_previous_map # dict[tag, Unit] — enemy structures last frame
```

### Dead units this frame

```python
bot.state.dead_units              # set[int] — tags that died this frame
```

---

## Debug commands (single-player only)

```python
await bot.client.debug_create_unit([[UnitTypeId.MARINE, 5, pos, 1]])  # spawn units
await bot.client.debug_kill_unit(unit_tags)   # kill by tag
await bot.client.debug_fast_build()           # instant build (toggle)
await bot.client.debug_free()                 # free resources (toggle)
await bot.client.debug_all_resources()        # +5000 minerals + gas
await bot.client.debug_show_map()             # reveal map (toggle)
await bot.client.debug_tech_tree()            # no tech requirements (toggle)
await bot.client.debug_upgrade()              # research all upgrades
await bot.client.debug_god()                  # invincibility (toggle)

# Debug drawing (call each tick):
bot.client.debug_text_simple("hello")                          # top-left text
bot.client.debug_text_screen("hello", (0.5, 0.1))             # screen position [0,1]
bot.client.debug_text_world("hello", unit.position3d)          # 3D world text
bot.client.debug_sphere_out(unit.position3d, 1.0, (255,0,0))  # sphere
bot.client.debug_line_out(p1_3d, p2_3d, (0,255,0))            # line
```

### Pathing queries

```python
distance = await bot.client.query_pathing(start, end)  # -> float | None
```

### Chat

```python
await bot.chat_send("glhf", team_only=False)
```

---

## Common patterns

### Weapon-cooldown kiting

```python
for unit in bot.units(UnitTypeId.MARINE):
    enemies = bot.enemy_units.closer_than(7, unit)
    if not enemies:
        continue
    if unit.weapon_cooldown == 0:
        unit.attack(enemies.closest_to(unit))
    else:
        unit.move(unit.position.towards(enemies.closest_to(unit), -2))
```

### Already-pending guard

```python
barracks_count = bot.structures(UnitTypeId.BARRACKS).ready.amount
if barracks_count + bot.already_pending(UnitTypeId.BARRACKS) < 3:
    if bot.can_afford(UnitTypeId.BARRACKS):
        await bot.build(UnitTypeId.BARRACKS, near=bot.start_location)
```

### Tech gate

```python
if bot.tech_requirement_progress(UnitTypeId.FACTORY) == 1:
    # safe to build Factory (Barracks is done)
    if bot.can_afford(UnitTypeId.FACTORY):
        await bot.build(UnitTypeId.FACTORY, near=bot.start_location)
```

### Effect dodging

```python
for effect in bot.state.effects:
    if effect.id == EffectId.RAVAGERCORROSIVEBILECP:
        for pos in effect.positions:
            for unit in bot.units.closer_than(2, pos):
                unit.move(unit.position.towards(pos, -3))
```

### Worker saturation

```python
for th in bot.townhalls.ready:
    if th.surplus_harvesters < 0:  # needs more workers
        for worker in bot.workers.idle:
            mf = bot.mineral_field.closest_to(th)
            worker.gather(mf)
            break
```
