# Terran Cheatsheet

## SCV construction

SCVs must stay at the building site until construction completes. If the SCV dies or is pulled away, the building pauses.

```python
bot.structures_without_construction_SCVs  # Units — unattended buildings in progress
unit.is_constructing_scv                  # bool — SCV currently building
```

## Add-on system

Barracks, Factory, and Starport can each have one add-on (Techlab or Reactor).

```python
unit.has_add_on     # bool
unit.has_techlab    # bool — has techlab attached
unit.has_reactor    # bool — has reactor attached
unit.add_on_tag     # int (0 if none)
bot.techlab_tags    # set[int] — all techlab tags
bot.reactor_tags    # set[int] — all reactor tags

# When placing, check room for add-on (2.5 units to the right):
pos = await bot.find_placement(UnitTypeId.BARRACKS, near=loc, addon_place=True)

# Reactor allows double-queue (bot.train handles this automatically)
# Techlab unlocks advanced units (Marauder, Siege Tank, Banshee, etc.)
```

| Add-on type | UnitTypeId |
|---|---|
| Barracks Techlab | `BARRACKSTECHLAB` |
| Barracks Reactor | `BARRACKSREACTOR` |
| Factory Techlab | `FACTORYTECHLAB` |
| Factory Reactor | `FACTORYREACTOR` |
| Starport Techlab | `STARPORTTECHLAB` |
| Starport Reactor | `STARPORTREACTOR` |

## Flying structures

Barracks, Factory, Starport, Command Center, and Orbital Command can lift off and land.

```python
# Lift off:
barracks(AbilityId.LIFT_BARRACKS)
# Land:
barracks_flying(AbilityId.LAND_BARRACKS, position)
```

| Ground | Flying |
|---|---|
| `BARRACKS` | `BARRACKSFLYING` |
| `FACTORY` | `FACTORYFLYING` |
| `STARPORT` | `STARPORTFLYING` |
| `COMMANDCENTER` | `COMMANDCENTERFLYING` |
| `ORBITALCOMMAND` | `ORBITALCOMMANDFLYING` |

## Supply Depot

```python
depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)   # lower (units walk over)
depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)   # raise (block pathing)
# Lowered type: UnitTypeId.SUPPLYDEPOTLOWERED
```

## Orbital Command

Morph from Command Center (requires Barracks):
```python
cc(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)
```

| Ability | Cost | Usage |
|---|---|---|
| MULE | 50 energy | `oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, mineral_patch)` |
| Scanner Sweep | 50 energy | `oc(AbilityId.SCANNERSWEEP_SCAN, position)` |
| Extra Supply | 50 energy | `oc(AbilityId.SUPPLYDROP_SUPPLYDROP)` |

## Planetary Fortress

Morph from Command Center (requires Engineering Bay):
```python
cc(AbilityId.UPGRADETOPLANETARYFORTRESS_PLANETARYFORTRESS)
```

## Unit transforms

| Unit | Mode A | Mode B | Abilities |
|---|---|---|---|
| Siege Tank | `SIEGETANK` | `SIEGETANKSIEGED` | `SIEGEMODE_SIEGEMODE` / `UNSIEGE_UNSIEGE` |
| Hellion | `HELLION` | `HELLIONTANK` | `MORPH_HELLBAT` / `MORPH_HELLION` |
| Viking | `VIKINGFIGHTER` (air) | `VIKINGASSAULT` (ground) | `MORPH_VIKINGASSAULTMODE` / `MORPH_VIKINGFIGHTERMODE` |
| Liberator | `LIBERATOR` (air) | `LIBERATORAG` (ground) | `MORPH_LIBERATORAGMODE` / `MORPH_LIBERATORAAMODE` |
| Thor | `THOR` (splash) | `THORAP` (single target) | `MORPH_THORHIGHIMPACTMODE` / `MORPH_THOREXPLOSIVEMODE` |
| Widow Mine | `WIDOWMINE` | `WIDOWMINEBURROWED` | `BURROWDOWN` / `BURROWUP` |

## Ramp wall

```python
ramp = bot.main_base_ramp
ramp.corner_depots                 # set[Point2] — 2 depot positions
ramp.barracks_correct_placement    # Point2 — barracks (with addon room)
ramp.depot_in_middle               # Point2 — optional 3rd depot
ramp.barracks_can_fit_addon        # bool
```

## Special abilities

```python
# Stimpack (Marine/Marauder, costs 10 HP):
marine(AbilityId.EFFECT_STIM)

# Ghost cloak (75 energy to activate):
ghost(AbilityId.BEHAVIOR_CLOAKON_GHOST)
ghost(AbilityId.BEHAVIOR_CLOAKOFF_GHOST)

# Banshee cloak (25 energy to activate):
banshee(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
banshee(AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE)

# EMP Round (Ghost, 75 energy):
ghost(AbilityId.EMP_EMP, position)

# Snipe (Ghost, 50 energy):
ghost(AbilityId.EFFECT_GHOSTSNIPE, target)

# Yamato Cannon (BC, 150 energy):
bc(AbilityId.YAMATO_YAMATOGUN, target)

# Tactical Jump (BC):
bc(AbilityId.EFFECT_TACTICALJUMP, position)

# Raven Auto-Turret (50 energy):
raven(AbilityId.BUILDAUTOTURRET_AUTOTURRET, position)

# Raven Interference Matrix (75 energy):
raven(AbilityId.EFFECT_INTERFERENCEMATRIX, target)

# Medivac heal (auto-cast by default)
# Medivac Afterburners:
medivac(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)

# Reaper KD8 Charge (grenade):
reaper(AbilityId.KD8CHARGE_KD8CHARGE, position)

# Nuke (Ghost, requires Ghost Academy + Nuke):
ghost(AbilityId.TACNUKESTRIKE_NUKECALLDOWN, position)

# Repair:
scv(AbilityId.EFFECT_REPAIR, target)
```

## Unit type IDs

### Workers & economy
| Unit | UnitTypeId |
|---|---|
| SCV | `SCV` |
| MULE | `MULE` |

### Infantry (Barracks)
| Unit | UnitTypeId | Requires |
|---|---|---|
| Marine | `MARINE` | — |
| Marauder | `MARAUDER` | Techlab |
| Reaper | `REAPER` | — |
| Ghost | `GHOST` | Techlab + Ghost Academy |

### Vehicles (Factory)
| Unit | UnitTypeId | Requires |
|---|---|---|
| Hellion | `HELLION` | — |
| Hellbat | `HELLIONTANK` | Armory |
| Widow Mine | `WIDOWMINE` | — |
| Cyclone | `CYCLONE` | — |
| Siege Tank | `SIEGETANK` | Techlab |
| Thor | `THOR` | Techlab + Armory |

### Air (Starport)
| Unit | UnitTypeId | Requires |
|---|---|---|
| Medivac | `MEDIVAC` | — |
| Viking | `VIKINGFIGHTER` | — |
| Liberator | `LIBERATOR` | — |
| Banshee | `BANSHEE` | Techlab |
| Raven | `RAVEN` | Techlab |
| Battlecruiser | `BATTLECRUISER` | Techlab + Fusion Core |

### Structures
| Structure | UnitTypeId |
|---|---|
| Command Center | `COMMANDCENTER` |
| Orbital Command | `ORBITALCOMMAND` |
| Planetary Fortress | `PLANETARYFORTRESS` |
| Supply Depot | `SUPPLYDEPOT` |
| Refinery | `REFINERY` |
| Barracks | `BARRACKS` |
| Engineering Bay | `ENGINEERINGBAY` |
| Bunker | `BUNKER` |
| Missile Turret | `MISSILETURRET` |
| Sensor Tower | `SENSORTOWER` |
| Factory | `FACTORY` |
| Ghost Academy | `GHOSTACADEMY` |
| Armory | `ARMORY` |
| Starport | `STARPORT` |
| Fusion Core | `FUSIONCORE` |

## Upgrades

### Barracks Tech Lab
| Upgrade | UpgradeId |
|---|---|
| Stimpack | `STIMPACK` |
| Combat Shield | `SHIELDWALL` |
| Concussive Shells | `PUNISHERGRENADES` |

### Factory Tech Lab
| Upgrade | UpgradeId |
|---|---|
| Infernal Pre-Igniter (Hellbat) | `HIGHCAPACITYBARRELS` |
| Drill Claws (Widow Mine) | `DRILLCLAWS` |
| Rapid Fire Launchers (Cyclone) | `CYCLONELOCKONDAMAGEUPGRADE` |
| Smart Servos (fast transform) | `SMARTSERVOS` |

### Starport Tech Lab
| Upgrade | UpgradeId |
|---|---|
| Banshee Cloak | `BANSHEECLOAK` |
| Banshee Hyperflight Rotors | `BANSHEESPEED` |

### Engineering Bay
| Upgrade | UpgradeId |
|---|---|
| Infantry Weapons 1/2/3 | `TERRANINFANTRYWEAPONSLEVEL1/2/3` |
| Infantry Armor 1/2/3 | `TERRANINFANTRYARMORSLEVEL1/2/3` |
| Hi-Sec Auto Tracking | `HISECAUTOTRACKING` |
| Building Armor | `TERRANBUILDINGARMOR` |

### Armory
| Upgrade | UpgradeId |
|---|---|
| Vehicle Weapons 1/2/3 | `TERRANVEHICLEWEAPONSLEVEL1/2/3` |
| Ship Weapons 1/2/3 | `TERRANSHIPWEAPONSLEVEL1/2/3` |
| Vehicle & Ship Armor 1/2/3 | `TERRANVEHICLEANDSHIPARMORSLEVEL1/2/3` |

### Ghost Academy
| Upgrade | UpgradeId |
|---|---|
| Personal Cloaking | `PERSONALCLOAKING` |

### Fusion Core
| Upgrade | UpgradeId |
|---|---|
| BC Weapon Refit | `BATTLECRUISERENABLESPECIALIZATIONS` |
| Liberator AG Range | `LIBERATORAGRANGEUPGRADE` |
| Medivac Caduceus Reactor | `MEDIVACCADUCEUSREACTOR` |
