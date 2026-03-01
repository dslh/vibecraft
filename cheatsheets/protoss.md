# Protoss Cheatsheet

## Power fields

Most Protoss structures must be within a Pylon's power field to function (produce units, research). Unpowered structures are disabled. Exceptions: Nexus and Assimilator never need power.

```python
unit.is_powered    # bool — structure is powered by nearby Pylon/Warp Prism
# Pylon power radius: ~6.5 tiles
# Warp Prism (phasing mode) also provides power
```

Probes warp in buildings — the Probe initiates construction then is free to leave (unlike Terran SCVs).

## Gateway / Warpgate

After researching Warp Gate, Gateways can morph into Warp Gates for faster unit production.

```python
# Morph Gateway -> Warpgate (after WARPGATERESEARCH is done):
gateway(AbilityId.MORPH_WARPGATE)

# Morph back to Gateway:
warpgate(AbilityId.MORPH_GATEWAY)

# Warp-in a unit (position must be in power field):
warpgate.warp_in(UnitTypeId.ZEALOT, position)
warpgate.warp_in(UnitTypeId.STALKER, pylon.position.random_on_distance(4))

bot.warp_gate_count  # int — number of warp gates

# Type IDs:
# UnitTypeId.GATEWAY, UnitTypeId.WARPGATE
```

## Chrono Boost

Nexus ability that speeds up production/research by 50% for 20 seconds.

```python
nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, target_structure)  # costs 50 energy
```

## Mass Recall

```python
nexus(AbilityId.EFFECT_MASSRECALL_NEXUS, position)  # recall nearby units
```

## Archon merge

Two High Templar or two Dark Templar merge into an Archon.

```python
from sc2.ids.ability_id import AbilityId
ht1(AbilityId.MORPH_ARCHON)  # select 2 templar, one issues the merge

# Note: already_pending(UnitTypeId.ARCHON) divides ability count by 2
```

## Unit transforms

| Unit | Mode A | Mode B | Abilities |
|---|---|---|---|
| Observer | `OBSERVER` | `OBSERVERSIEGEMODE` | `MORPH_SURVEILLANCEMODE` / `MORPH_OBSERVERMODE` |
| Warp Prism | `WARPPRISM` | `WARPPRISMPHASING` | `MORPH_WARPPRISMPHASINGMODE` / `MORPH_WARPPRISMTRANSPORTMODE` |

Warp Prism in phasing mode creates a power field for warp-ins and powers structures.

## Ramp wall

```python
ramp = bot.main_base_ramp
ramp.protoss_wall_pylon       # Point2 — pylon position to power wall
ramp.protoss_wall_buildings   # frozenset[Point2] — 2 building positions (3x3)
ramp.protoss_wall_warpin      # Point2 — unit position to block the gap
```

## Special abilities

```python
# Stalker Blink (requires BLINKTECH):
stalker(AbilityId.EFFECT_BLINK_STALKER, position)

# Adept Shade (phase shift):
adept(AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT, position)

# Sentry Guardian Shield (75 energy):
sentry(AbilityId.GUARDIANSHIELD_GUARDIANSHIELD)

# Sentry Force Field (50 energy):
sentry(AbilityId.FORCEFIELD_FORCEFIELD, position)

# Sentry Hallucination (75 energy):
sentry(AbilityId.HALLUCINATION_ARCHON)  # and other HALLUCINATION_* variants

# High Templar Psi Storm (75 energy, requires PSISTORMTECH):
ht(AbilityId.PSISTORM_PSISTORM, position)

# High Templar Feedback (50 energy):
ht(AbilityId.FEEDBACK_FEEDBACK, target)

# Oracle Revelation (25 energy):
oracle(AbilityId.ORACLEREVELATION_ORACLEREVELATION, position)

# Oracle Stasis Ward (50 energy):
oracle(AbilityId.BUILD_STASISTRAP, position)

# Oracle Pulsar Beam (toggle):
oracle(AbilityId.BEHAVIOR_PULSARBEAMON)
oracle(AbilityId.BEHAVIOR_PULSARBEAMOFF)

# Phoenix Graviton Beam (50 energy):
phoenix(AbilityId.GRAVITONBEAM_GRAVITONBEAM, target)

# Void Ray Prismatic Alignment:
voidray(AbilityId.EFFECT_VOIDRAYPRISMATICALIGNMENT)

# Carrier - Build Interceptors:
carrier(AbilityId.BUILD_INTERCEPTORS)

# Disruptor Purification Nova:
disruptor(AbilityId.EFFECT_PURIFICATIONNOVA, position)

# Mothership Time Warp:
mothership(AbilityId.EFFECT_TIMEWARP, position)

# Mothership Cloaking Field (passive, cloaks nearby units)

# Shield Battery Restore:
shield_battery(AbilityId.EFFECT_RESTORE, target)
```

## Unit type IDs

### Workers & economy
| Unit | UnitTypeId |
|---|---|
| Probe | `PROBE` |

### Gateway units
| Unit | UnitTypeId | Requires |
|---|---|---|
| Zealot | `ZEALOT` | — |
| Adept | `ADEPT` | Cybernetics Core |
| Stalker | `STALKER` | Cybernetics Core |
| Sentry | `SENTRY` | Cybernetics Core |
| High Templar | `HIGHTEMPLAR` | Templar Archive |
| Dark Templar | `DARKTEMPLAR` | Dark Shrine |
| Archon | `ARCHON` | (merge 2 Templar) |

### Robotics Facility units
| Unit | UnitTypeId | Requires |
|---|---|---|
| Observer | `OBSERVER` | — |
| Warp Prism | `WARPPRISM` | — |
| Immortal | `IMMORTAL` | — |
| Colossus | `COLOSSUS` | Robotics Bay |
| Disruptor | `DISRUPTOR` | Robotics Bay |

### Stargate units
| Unit | UnitTypeId | Requires |
|---|---|---|
| Phoenix | `PHOENIX` | — |
| Oracle | `ORACLE` | — |
| Void Ray | `VOIDRAY` | — |
| Tempest | `TEMPEST` | Fleet Beacon |
| Carrier | `CARRIER` | Fleet Beacon |
| Mothership | `MOTHERSHIP` | Fleet Beacon (from Nexus) |

### Structures
| Structure | UnitTypeId |
|---|---|
| Nexus | `NEXUS` |
| Pylon | `PYLON` |
| Assimilator | `ASSIMILATOR` |
| Gateway | `GATEWAY` |
| Warp Gate | `WARPGATE` |
| Cybernetics Core | `CYBERNETICSCORE` |
| Forge | `FORGE` |
| Twilight Council | `TWILIGHTCOUNCIL` |
| Robotics Facility | `ROBOTICSFACILITY` |
| Robotics Bay | `ROBOTICSBAY` |
| Stargate | `STARGATE` |
| Fleet Beacon | `FLEETBEACON` |
| Templar Archive | `TEMPLARARCHIVE` |
| Dark Shrine | `DARKSHRINE` |
| Photon Cannon | `PHOTONCANNON` |
| Shield Battery | `SHIELDBATTERY` |

## Upgrades

### Forge
| Upgrade | UpgradeId |
|---|---|
| Ground Weapons 1/2/3 | `PROTOSSGROUNDWEAPONSLEVEL1/2/3` |
| Ground Armor 1/2/3 | `PROTOSSGROUNDARMORSLEVEL1/2/3` |
| Shields 1/2/3 | `PROTOSSSHIELDSLEVEL1/2/3` |

### Cybernetics Core
| Upgrade | UpgradeId |
|---|---|
| Air Weapons 1/2/3 | `PROTOSSAIRWEAPONSLEVEL1/2/3` |
| Air Armor 1/2/3 | `PROTOSSAIRARMORSLEVEL1/2/3` |
| Warp Gate Research | `WARPGATERESEARCH` |

### Twilight Council
| Upgrade | UpgradeId |
|---|---|
| Charge (Zealot) | `CHARGE` |
| Blink (Stalker) | `BLINKTECH` |
| Resonating Glaives (Adept) | `ADEPTPIERCINGATTACK` |

### Templar Archive
| Upgrade | UpgradeId |
|---|---|
| Psi Storm | `PSISTORMTECH` |

### Dark Shrine
| Upgrade | UpgradeId |
|---|---|
| Shadow Stride (DT Blink) | `DARKTEMPLARBLINKUPGRADE` |

### Robotics Bay
| Upgrade | UpgradeId |
|---|---|
| Extended Thermal Lance (Colossus range) | `EXTENDEDTHERMALLANCE` |
| Gravitic Boosters (Observer speed) | `OBSERVERGRAVITICBOOSTER` |
| Gravitic Drive (Warp Prism speed) | `GRAVITICDRIVE` |

### Fleet Beacon
| Upgrade | UpgradeId |
|---|---|
| Anion Pulse Crystals (Phoenix range) | `PHOENIXRANGEUPGRADE` |
| Flux Vanes (Void Ray speed) | `VOIDRAYSPEEDUPGRADE` |
| Tectonic Destabilizers (Tempest ground) | `TEMPESTGROUNDATTACKUPGRADE` |
