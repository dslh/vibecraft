# Zerg Cheatsheet

## Larva

Most Zerg units are trained from Larva, which spawn at Hatcheries/Lairs/Hives.

```python
bot.larva                             # Units — all available larva
bot.larva.first.train(UnitTypeId.DRONE)  # train from larva directly
bot.train(UnitTypeId.ZERGLING)        # high-level: auto-selects larva

# Queen inject adds 3 larva to a Hatchery:
queen(AbilityId.EFFECT_INJECTLARVA, hatchery)  # costs 25 energy
```

Queens are trained from Hatchery/Lair/Hive (not from larva):
```python
hatchery.train(UnitTypeId.QUEEN)
```

## Drone sacrifice

Drones morph into buildings — the Drone is consumed (dies to become the building).

```python
drone.build(UnitTypeId.SPAWNINGPOOL, position)  # drone is consumed
# Use already_pending to avoid overspending:
if bot.already_pending(UnitTypeId.SPAWNINGPOOL) == 0:
    await bot.build(UnitTypeId.SPAWNINGPOOL, near=bot.start_location)
```

Extractor is built on a geyser:
```python
drone.build_gas(geyser_unit)
# or: drone.build(UnitTypeId.EXTRACTOR, geyser_unit)
```

## Overlord supply

Each Overlord provides 8 supply. First Overlord is free.

```python
# Train from larva:
bot.train(UnitTypeId.OVERLORD)

# Morph Overlord -> Overseer (requires Lair):
overlord(AbilityId.MORPH_OVERSEER)

# Morph Overlord -> Transport Overlord:
overlord(AbilityId.MORPH_OVERLORDTRANSPORT)
```

| Form | UnitTypeId |
|---|---|
| Overlord | `OVERLORD` |
| Overlord Transport | `OVERLORDTRANSPORT` |
| Overseer | `OVERSEER` |
| Overseer (siege mode) | `OVERSEERSIEGEMODE` |

## Creep

Zerg ground units get a speed bonus on creep. Hatcheries generate creep automatically.

```python
bot.has_creep(pos)  # bool — is there creep at this position

# Queen places creep tumor (25 energy):
queen(AbilityId.BUILD_CREEPTUMOR_QUEEN, position)

# Existing tumor spreads (one-time use, then it burrows):
tumor(AbilityId.BUILD_CREEPTUMOR_TUMOR, position)
```

| Type | UnitTypeId |
|---|---|
| Creep Tumor (building) | `CREEPTUMOR` |
| Creep Tumor (burrowed, can spread) | `CREEPTUMORBURROWED` |
| Creep Tumor (from queen) | `CREEPTUMORQUEEN` |

Speed bonuses on creep (multiplier): Queen 2.67x, most ground units 1.3x, Locust 1.4x.

## Burrow

Global upgrade `UpgradeId.BURROW` researched from Hatchery. After researching, most Zerg ground units can burrow.

```python
unit.is_burrowed    # bool

# Per-unit burrow abilities follow the pattern:
zergling(AbilityId.BURROWDOWN_ZERGLING)
zergling_burrowed(AbilityId.BURROWUP_ZERGLING)
# Same pattern: BURROWDOWN_ROACH, BURROWUP_ROACH, etc.
```

## Hatchery / Lair / Hive progression

The Zerg townhall upgrades in place. Tech aliases mean `bot.townhalls` includes all three.

```python
hatchery(AbilityId.UPGRADETOLAIR_LAIR)       # requires Spawning Pool
lair(AbilityId.UPGRADETOHIVE_HIVE)           # requires Infestation Pit

# Tech progress checks work through aliases:
bot.structure_type_build_progress(UnitTypeId.LAIR)  # returns 1 if Hive exists too
```

## Unit morphs

Several Zerg units morph from existing units (consuming them).

| From | To | UnitTypeId | Ability |
|---|---|---|---|
| Zergling | Baneling | `BANELING` | `MORPHZERGLINGTOBANELING_BANELING` |
| Roach | Ravager | `RAVAGER` | `MORPHTORAVAGER_RAVAGER` |
| Hydralisk | Lurker | `LURKERMP` | `MORPH_LURKER` |
| Corruptor | Brood Lord | `BROODLORD` | `MORPHTOBROODLORD_BROODLORD` |
| Overlord | Overseer | `OVERSEER` | `MORPH_OVERSEER` |
| Overlord | Transport | `OVERLORDTRANSPORT` | `MORPH_OVERLORDTRANSPORT` |

Morph costs are deltas (e.g., Ravager costs 25 minerals + 75 gas on top of Roach). `bot.calculate_cost()` returns the correct delta.

Cocoon types while morphing: `BANELINGCOCOON`, `RAVAGERCOCOON`, `LURKERMPEGG`, `BROODLORDCOCOON`, `OVERLORDCOCOON`.

## Queen abilities

Queens are trained from Hatchery/Lair/Hive (not larva). They don't cost supply.

```python
# Inject Larva (25 energy) — adds 3 larva:
queen(AbilityId.EFFECT_INJECTLARVA, hatchery)

# Transfuse (50 energy) — heals 125 HP on biological unit:
queen(AbilityId.TRANSFUSION_TRANSFUSION, target)

# Creep Tumor (25 energy):
queen(AbilityId.BUILD_CREEPTUMOR_QUEEN, position)
```

## Spine / Spore Crawler

Can uproot, move, and re-root on creep.

```python
spine(AbilityId.SPINECRAWLERUPROOT_SPINECRAWLERUPROOT)       # uproot
spine_uprooted(AbilityId.SPINECRAWLERROOT_SPINECRAWLERROOT, pos)  # root at pos

spore(AbilityId.SPORECRAWLERUPROOT_SPORECRAWLERUPROOT)       # uproot
spore_uprooted(AbilityId.SPORECRAWLERROOT_SPORECRAWLERROOT, pos)  # root at pos
```

| Form | UnitTypeId |
|---|---|
| Spine Crawler | `SPINECRAWLER` |
| Spine Crawler (uprooted) | `SPINECRAWLERUPROOTED` |
| Spore Crawler | `SPORECRAWLER` |
| Spore Crawler (uprooted) | `SPORECRAWLERUPROOTED` |

## Special abilities

```python
# Ravager Corrosive Bile (no energy cost, cooldown):
ravager(AbilityId.EFFECT_CORROSIVEBILE, position)

# Infestor Fungal Growth (75 energy):
infestor(AbilityId.FUNGALGROWTH_FUNGALGROWTH, position)

# Infestor Neural Parasite (100 energy, requires upgrade):
infestor(AbilityId.NEURALPARASITE_NEURALPARASITE, target)

# Viper Abduct (75 energy):
viper(AbilityId.EFFECT_ABDUCT, target)

# Viper Parasitic Bomb (125 energy):
viper(AbilityId.PARASITICBOMB_PARASITICBOMB, target)

# Viper Blinding Cloud (100 energy):
viper(AbilityId.BLINDINGCLOUD_BLINDINGCLOUD, position)

# Overseer Contaminate:
overseer(AbilityId.CONTAMINATE_CONTAMINATE, target)

# Overseer Spawn Changeling:
overseer(AbilityId.SPAWNCHANGELING_SPAWNCHANGELING)

# Nydus Network — spawn Nydus Worm:
nydus(AbilityId.BUILD_NYDUSWORM, position)

# Swarm Host — spawn Locusts:
swarmhost(AbilityId.EFFECT_SPAWNLOCUSTS, position)
```

## Unit type IDs

### Workers & economy
| Unit | UnitTypeId |
|---|---|
| Drone | `DRONE` |
| Drone (burrowed) | `DRONEBURROWED` |
| Larva | `LARVA` |
| Egg | `EGG` |

### Ground units (from Larva)
| Unit | UnitTypeId | Requires |
|---|---|---|
| Zergling | `ZERGLING` | Spawning Pool |
| Roach | `ROACH` | Roach Warren |
| Hydralisk | `HYDRALISK` | Hydralisk Den |
| Infestor | `INFESTOR` | Infestation Pit |
| Swarm Host | `SWARMHOSTMP` | Infestation Pit |
| Ultralisk | `ULTRALISK` | Ultralisk Cavern |

### Morphed ground units
| Unit | UnitTypeId | From |
|---|---|---|
| Baneling | `BANELING` | Zergling |
| Ravager | `RAVAGER` | Roach |
| Lurker | `LURKERMP` | Hydralisk |

### Air units (from Larva)
| Unit | UnitTypeId | Requires |
|---|---|---|
| Overlord | `OVERLORD` | — |
| Mutalisk | `MUTALISK` | Spire |
| Corruptor | `CORRUPTOR` | Spire |
| Viper | `VIPER` | Hive |

### Morphed air units
| Unit | UnitTypeId | From |
|---|---|---|
| Brood Lord | `BROODLORD` | Corruptor |
| Overseer | `OVERSEER` | Overlord |

### Other units
| Unit | UnitTypeId |
|---|---|
| Queen | `QUEEN` |
| Changeling | `CHANGELING` |
| Broodling | `BROODLING` |
| Locust | `LOCUSTMP` |
| Locust (flying) | `LOCUSTMPFLYING` |

### Burrowed forms
| Unit | UnitTypeId |
|---|---|
| Zergling | `ZERGLINGBURROWED` |
| Baneling | `BANELINGBURROWED` |
| Roach | `ROACHBURROWED` |
| Hydralisk | `HYDRALISKBURROWED` |
| Lurker | `LURKERMPBURROWED` |
| Infestor | `INFESTORBURROWED` |
| Ultralisk | `ULTRALISKBURROWED` |
| Queen | `QUEENBURROWED` |
| Swarm Host | `SWARMHOSTBURROWEDMP` |

### Structures
| Structure | UnitTypeId |
|---|---|
| Hatchery | `HATCHERY` |
| Lair | `LAIR` |
| Hive | `HIVE` |
| Extractor | `EXTRACTOR` |
| Spawning Pool | `SPAWNINGPOOL` |
| Baneling Nest | `BANELINGNEST` |
| Roach Warren | `ROACHWARREN` |
| Hydralisk Den | `HYDRALISKDEN` |
| Lurker Den | `LURKERDENMP` |
| Evolution Chamber | `EVOLUTIONCHAMBER` |
| Infestation Pit | `INFESTATIONPIT` |
| Spire | `SPIRE` |
| Greater Spire | `GREATERSPIRE` |
| Ultralisk Cavern | `ULTRALISKCAVERN` |
| Nydus Network | `NYDUSNETWORK` |
| Nydus Canal | `NYDUSCANAL` |
| Spine Crawler | `SPINECRAWLER` |
| Spore Crawler | `SPORECRAWLER` |

## Upgrades

### Hatchery / Lair / Hive
| Upgrade | UpgradeId |
|---|---|
| Burrow | `BURROW` |
| Pneumatized Carapace (Overlord speed) | `OVERLORDSPEED` |

### Spawning Pool
| Upgrade | UpgradeId |
|---|---|
| Metabolic Boost (Zergling speed) | `ZERGLINGMOVEMENTSPEED` |
| Adrenal Glands (Zergling attack speed) | `ZERGLINGATTACKSPEED` |

### Baneling Nest
| Upgrade | UpgradeId |
|---|---|
| Centrifugal Hooks (Baneling speed) | `CENTRIFICALHOOKS` |

### Roach Warren
| Upgrade | UpgradeId |
|---|---|
| Glial Reconstitution (Roach speed) | `GLIALRECONSTITUTION` |
| Tunneling Claws (burrowed move) | `TUNNELINGCLAWS` |

### Hydralisk Den
| Upgrade | UpgradeId |
|---|---|
| Grooved Spines (range) | `EVOLVEGROOVEDSPINES` |
| Muscular Augments (speed) | `EVOLVEMUSCULARAUGMENTS` |
| Frenzy | `FRENZY` |

### Lurker Den
| Upgrade | UpgradeId |
|---|---|
| Seismic Spines (range) | `LURKERRANGE` |
| Digging Claws (burrowed move) | `DIGGINGCLAWS` |

### Evolution Chamber
| Upgrade | UpgradeId |
|---|---|
| Melee Weapons 1/2/3 | `ZERGMELEEWEAPONSLEVEL1/2/3` |
| Missile Weapons 1/2/3 | `ZERGMISSILEWEAPONSLEVEL1/2/3` |
| Ground Armor 1/2/3 | `ZERGGROUNDARMORSLEVEL1/2/3` |

### Spire / Greater Spire
| Upgrade | UpgradeId |
|---|---|
| Flyer Weapons 1/2/3 | `ZERGFLYERWEAPONSLEVEL1/2/3` |
| Flyer Armor 1/2/3 | `ZERGFLYERARMORSLEVEL1/2/3` |

### Ultralisk Cavern
| Upgrade | UpgradeId |
|---|---|
| Chitinous Plating (armor) | `CHITINOUSPLATING` |
| Anabolic Synthesis (speed) | `ANABOLICSYNTHESIS` |

### Infestation Pit
| Upgrade | UpgradeId |
|---|---|
| Neural Parasite | `NEURALPARASITE` |
