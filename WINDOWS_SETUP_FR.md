# Guide d'installation Windows

## Prérequis

### 1. StarCraft II

Installez SC2 depuis [Battle.net](https://battle.net). L'édition Starter gratuite suffit — pas besoin d'acheter le jeu. Il devrait s'installer à l'emplacement par défaut :

```
C:\Program Files (x86)\StarCraft II
```

Si vous l'installez ailleurs, définissez la variable d'environnement `SC2PATH` vers le répertoire d'installation.

### 2. Cartes

Le bot utilise `Simple64` par défaut, mais fonctionne avec n'importe quelle carte melee. Téléchargez le pack de cartes **Melee** depuis le [dépôt de cartes de Blizzard](https://github.com/Blizzard/s2client-proto#map-packs) et extrayez les fichiers `.SC2Map` dans :

```
C:\Program Files (x86)\StarCraft II\Maps\
```

Les cartes peuvent être dans des sous-dossiers (par ex. `Maps\Melee\Simple64.SC2Map`) — le bot cherche sur un niveau de profondeur.

### 3. Python 3.10+

Installez Python **3.10 ou plus récent** depuis [python.org](https://www.python.org/downloads/). Pendant l'installation, cochez **« Add Python to PATH »**.

Vérifiez que ça fonctionne :

```
python --version
```

### 4. Git

Installez Git depuis [git-scm.com](https://git-scm.com/downloads/win). Les options par défaut conviennent.

### 5. Terminal

Il vous faut un terminal qui supporte les couleurs ANSI et qui soit agréable à utiliser. Au choix :

- **Windows Terminal** — préinstallé sur Windows 11, ou disponible sur le Microsoft Store. Recommandé.
- **Terminal intégré de VS Code** — fonctionne bien si vous utilisez déjà VS Code.

Évitez `cmd.exe` tout seul — ça marche mais l'expérience est médiocre.

## Installation du projet

### Cloner les dépôts

```bash
mkdir sc2
cd sc2
git clone https://github.com/dslh/vibecraft.git bot
git clone https://github.com/dslh/python-sc2.git
```

### Créer le venv et installer les dépendances

```bash
cd bot
python -m venv .venv
.venv\Scripts\pip install -e ..\python-sc2
.venv\Scripts\pip install claude-agent-sdk mcp rich prompt_toolkit
```

Ceci installe `python-sc2` en mode éditable avec toutes ses dépendances (aiohttp, protobuf, numpy, scipy, etc.), ainsi que les dépendances de l'interface chat.

### Vérifier que tout fonctionne

```bash
.venv\Scripts\python run.py --map Simple64 --race terran --difficulty medium
```

SC2 devrait se lancer, se connecter et démarrer une partie. Le bot recharge automatiquement le code de `bot_src/` à chaque tick — modifiez et sauvegardez vos fichiers pour mettre à jour le comportement en cours de partie.

## Développement assisté par IA

Si vous avez déjà un outil de programmation agentique (Claude Code, Cursor, Windsurf, etc.), vous êtes prêt — ouvrez simplement le projet dedans. Le fichier `CLAUDE.md` à la racine du projet contient la documentation complète sur le harness, les cheatsheets, les fichiers de log en temps réel et l'outil `cmd.py` pour envoyer des commandes ponctuelles dans une partie en cours.

Sinon, le projet inclut une interface chat intégrée. Ouvrez un deuxième terminal dans le répertoire `bot/` et lancez :

```bash
.venv\Scripts\python chat.py
```

Au premier lancement, il vous demandera une [clé API Anthropic](https://console.anthropic.com/) et la sauvegardera dans `.env`. L'agent chat peut lire l'état du jeu, modifier le code du bot et exécuter des commandes dans une partie en cours — le tout via une interface conversationnelle.

## Dépannage

- **« Map not found »** — Vérifiez que les fichiers `.SC2Map` sont bien dans `StarCraft II\Maps\` (ou un sous-dossier). Le nom de carte passé à `--map` doit correspondre au nom du fichier sans extension.
- **SC2 ne se lance pas** — Vérifiez que `SC2_x64.exe` existe dans `StarCraft II\Versions\BaseXXXXX\`. Si vous avez plusieurs dossiers `Base*`, le bot utilise le plus récent.
- **« SC2 installation not found »** — Définissez la variable d'environnement `SC2PATH=C:\Program Files (x86)\StarCraft II`.
- **Erreurs d'import Python** — Assurez-vous d'avoir installé python-sc2 dans le venv du bot, pas dans votre Python système. Utilisez `.venv\Scripts\python` et non simplement `python`.
