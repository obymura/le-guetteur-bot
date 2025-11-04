# 🔍 Polymarket Insider Detector Bot

Bot Discord ultra-performant qui détecte en temps réel les mouvements suspects d'insiders sur Polymarket et envoie des alertes visuelles magnifiques.

## 🎯 Fonctionnalités

### Détection Intelligente
- ✅ **Nouveaux wallets** avec gros paris uniques
- ✅ **Mise massive** sur un seul marché (>$5K)
- ✅ **Pattern d'activité** suspect (focus unique, timing étrange)
- ✅ **Score de probabilité** d'insider (0-100%)
- ✅ **Analyse en temps réel** toutes les 5 minutes

### Alertes Discord Magnifiques
- 🎨 **Embeds colorés** selon probabilité (rouge=très élevée, orange=élevée, jaune=moyenne)
- 📊 **Jauge visuelle** de probabilité avec emojis
- 💡 **Recommandation claire**: quel pari suivre (YES/NO)
- 💰 **Taille du pari** en dollars
- 👤 **Info wallet**: premier trade ou non, nombre total de trades
- 🔍 **Raisons détaillées** pourquoi c'est suspect
- 🔗 **Liens directs** vers le marché Polymarket
- ⏰ **Timestamp précis** du trade

## 📦 Installation

### 1. Prérequis
```bash
# Python 3.8+
python --version

# Git
git clone <votre-repo>
cd polymarket-insider-bot
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Configuration Discord

#### Créer le bot Discord:
1. Va sur https://discord.com/developers/applications
2. Clique "New Application"
3. Nom: "Polymarket Insider"
4. Va dans "Bot" → "Add Bot"
5. Copie le **TOKEN** (garde-le secret!)
6. Active ces **Privileged Gateway Intents**:
   - ✅ MESSAGE CONTENT INTENT
   - ✅ SERVER MEMBERS INTENT

#### Inviter le bot sur ton serveur:
1. Va dans "OAuth2" → "URL Generator"
2. Sélectionne:
   - **Scopes**: `bot`
   - **Permissions**: 
     - Send Messages
     - Embed Links
     - Use External Emojis
3. Copie l'URL générée et ouvre-la dans ton navigateur
4. Sélectionne ton serveur Discord

#### Récupérer l'ID du channel:
1. Dans Discord: Paramètres → Avancés → Activer "Mode développeur"
2. Clique droit sur ton channel → "Copier l'identifiant"

### 4. Configuration des variables d'environnement

```bash
# Copie le template
cp .env.example .env

# Édite le fichier .env avec tes valeurs
nano .env
```

Remplis:
```env
DISCORD_BOT_TOKEN=MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.GhJkLm.OpQrStUvWxYzAbCdEfGhIjKlMnOpQrStUvWx
DISCORD_CHANNEL_ID=1234567890123456789
```

## 🚀 Lancer le bot

```bash
python polymarket_insider_bot.py
```

Tu devrais voir:
```
✅ Bot connecté en tant que Polymarket Insider#1234
📊 Surveillance des insiders Polymarket activée
```

## 📊 Exemple d'alerte

Voici à quoi ressemble une alerte quand un insider est détecté:

```
╔══════════════════════════════════════════╗
║     🚨 ALERTE INSIDER DÉTECTÉ           ║
╚══════════════════════════════════════════╝

Will Trump win the 2024 election?

📊 Marché: [Voir sur Polymarket](https://polymarket.com/...)

🎲 Probabilité Insider: 85%
████████░░ 🔥 TRÈS ÉLEVÉE

💡 Recommandation          💰 Taille du pari
Suivre l'insider: YES ✅   $47,500

👤 Wallet                  📝 Premier trade?
0x1a2b3c...def456          ✅ OUI

⏰ Heure du trade
2025-11-04T02:15:33Z

🔍 Signaux détectés
• 🆕 Wallet créé spécifiquement pour ce trade
• 💰 Mise massive ($47,500)
• 🎯 100% focus sur ce marché uniquement
• ⏰ Trade à 2h (heures suspectes)
```

## 🎛️ Configuration Avancée

### Ajuster les seuils de détection

Dans `polymarket_insider_bot.py`, ligne ~18-20:

```python
self.MIN_BET_SIZE = 5000  # Minimum $5K pour alerte
self.PRICE_SPIKE_THRESHOLD = 0.15  # 15% de changement de prix
self.NEW_WALLET_DAYS = 30  # Wallet "nouveau" si < 30 jours
```

### Changer la fréquence de vérification

Ligne ~34:
```python
@tasks.loop(minutes=5)  # Change à 1, 3, 10, etc.
```

## 🧮 Comment fonctionne le Score Insider?

Le bot calcule un score sur 100 basé sur:

| Critère | Points Max | Description |
|---------|------------|-------------|
| **Nouveau wallet** | 40 pts | Wallet créé pour ce trade = 40, <5 trades = 25, <30 jours = 20 |
| **Taille du pari** | 30 pts | >$50K = 30, >$20K = 20, >$10K = 15, >$5K = 10 |
| **Focus unique** | 20 pts | 1 seul marché = 20, ≤3 marchés = 10 |
| **Timing suspect** | 10 pts | Trade entre 00h-06h ou 22h-23h = 10 |

**Score ≥ 80%** 🔥 = TRÈS ÉLEVÉE (rouge)
**Score ≥ 65%** ⚠️ = ÉLEVÉE (orange)  
**Score ≥ 50%** ⚡ = MOYENNE (jaune)
**Score < 50%** ℹ️ = FAIBLE (gris) → pas d'alerte

## 🔧 Architecture Technique

### APIs Utilisées
- **Gamma API** (`gamma-api.polymarket.com`): Récupère les marchés actifs
- **CLOB API** (`clob.polymarket.com`): Récupère les trades en temps réel
- Pas besoin de clé API! Tout est public sur la blockchain

### Flux de données
```
1. Récupère top 50 marchés par volume (toutes les 5 min)
   ↓
2. Pour chaque marché: récupère 100 derniers trades
   ↓
3. Groupe les trades par wallet (dernière heure)
   ↓
4. Analyse l'historique de chaque wallet
   ↓
5. Calcule le score d'insider
   ↓
6. Si score >50%: envoie alerte Discord
```

## 🛡️ Limitations & Avertissements

⚠️ **Disclaimer légal**: 
- Ce bot est à usage éducatif et informatif
- Suivre des "insiders" n'est PAS une garantie de profit
- Les marchés de prédiction comportent des risques
- Ce n'est pas un conseil financier

⚠️ **Limitations techniques**:
- APIs publiques = rate limits (le bot respecte les limites)
- Détection basée sur patterns = faux positifs possibles
- Certains "insiders" peuvent être simplement chanceux
- Délai de ~5 min entre détection et alerte

## 🐛 Troubleshooting

### Le bot ne se connecte pas
```
❌ Vérifie DISCORD_BOT_TOKEN dans .env
❌ Le token doit être sans guillemets ni espaces
```

### Pas d'alertes reçues
```
❌ Vérifie DISCORD_CHANNEL_ID
❌ Le bot a-t-il les permissions sur le channel?
❌ Baisse MIN_BET_SIZE pour tester (ex: 1000)
```

### Erreur "channel not found"
```
❌ Active le Mode Développeur dans Discord
❌ L'ID doit être un nombre, pas un nom
```

## 📈 Améliorations Futures

- [ ] Tracking multi-wallet (identifier des clusters)
- [ ] ML pour prédire l'issue finale après alerte
- [ ] Graphiques de prix en temps réel
- [ ] Support Telegram en plus de Discord
- [ ] Base de données pour historique des alertes
- [ ] Backtesting: % de réussite des alertes passées
- [ ] Notifications push mobile

## 📝 Licence

MIT - Utilise, modifie, partage librement!

## 🤝 Contribution

Les PRs sont bienvenues! Idées:
- Améliorer l'algo de scoring
- Ajouter d'autres patterns d'insider
- Optimiser les appels API
- Ajouter des tests unitaires

---

**Made with 🔥 by [ton nom]**  
Si ce bot t'aide à dénicher des insiders, pense à ⭐ le repo!
