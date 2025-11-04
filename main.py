#!/usr/bin/env python3
"""
🚀 POLYMARKET INSIDER BOT - VERSION PRODUCTION
Détecte les insiders avec score ≥ 50%
"""

import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import asyncio
import json

# ============================================================
# CONFIG RAILWAY
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID") or os.getenv("CHANNEL_ID", "0"))

if not DISCORD_TOKEN:
    print("❌ ERREUR: DISCORD_TOKEN manquant")
    sys.exit(1)

if CHANNEL_ID == 0:
    print("❌ ERREUR: CHANNEL_ID manquant")
    sys.exit(1)

print(f"✅ Config OK - Channel: {CHANNEL_ID}")

# ============================================================
# POLYMARKET APIs
# ============================================================

# Les endpoints Polymarket documentés qui marchent
GAMMA_API = "https://gamma-api.polymarket.com"  # Marchés et data
DATA_API = "https://data-api.polymarket.com"    # Trades en temps réel
CLOB_API = "https://clob.polymarket.com"        # Order book

# ============================================================
# SETTINGS
# ============================================================

MIN_BET_THRESHOLD = 1000      # $1000 minimum pour tracker
MIN_INSIDER_SCORE = 50        # 50% minimum pour alerte
SCAN_INTERVAL = 30            # Scan toutes les 30 secondes
MAX_TRADES_CHECK = 1000       # Analyser jusqu'à 1000 trades

# ============================================================
# BOT PRINCIPAL
# ============================================================

class InsiderDetectorBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.processed_trades: set = set()  # Track trades déjà vus
        self.alerts_today = 0
        self.start_time = datetime.now()
        
    async def cog_load(self):
        """Initialise le bot"""
        self.session = aiohttp.ClientSession()
        if not self.detector_loop.is_running():
            self.detector_loop.start()
        print("✅ Bot chargé, scanner démarré")
        
    async def cog_unload(self):
        """Arrête le bot proprement"""
        self.detector_loop.cancel()
        if self.session:
            await self.session.close()

    # ============================================================
    # RÉCUPÉRATION DONNÉES
    # ============================================================

    async def fetch_markets(self) -> List[Dict]:
        """Récupère les marchés actifs"""
        try:
            async with self.session.get(
                f"{GAMMA_API}/markets",
                params={
                    'limit': 100,
                    'closed': 'false',
                    '_sort': 'volume24hr',
                    '_order': 'desc'
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else data.get('data', [])
        except Exception as e:
            print(f"⚠️ Erreur fetch_markets: {e}")
        return []

    async def fetch_trades(self, limit: int = 500) -> List[Dict]:
        """Récupère les trades récents depuis Data API"""
        try:
            async with self.session.get(
                f"{DATA_API}/trades",
                params={'limit': limit},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # L'API retourne un array directement
                    return data if isinstance(data, list) else []
        except Exception as e:
            print(f"⚠️ Erreur fetch_trades: {e}")
        return []

    async def fetch_wallet_trades(self, wallet: str, limit: int = 100) -> List[Dict]:
        """Récupère l'historique de trades d'un wallet"""
        try:
            async with self.session.get(
                f"{DATA_API}/activity",
                params={
                    'proxyWallet': wallet,
                    'limit': limit
                },
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else []
        except Exception as e:
            print(f"⚠️ Erreur fetch_wallet_trades: {e}")
        return []

    # ============================================================
    # SCORING INSIDER
    # ============================================================

    async def score_insider(self, trade: Dict) -> tuple[int, List[str]]:
        """
        Calcule le score d'insider (0-100)
        Retourne: (score, raisons)
        """
        score = 0
        signals = []

        try:
            # Extraction données
            wallet = trade.get('proxyWallet', 'unknown')
            size = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            trade_value = size * price
            title = trade.get('title', 'Unknown')[:50]
            outcome = trade.get('outcome', '?')
            
            # Skip trop petit
            if trade_value < MIN_BET_THRESHOLD:
                return 0, []

            # ========== FACTEUR 1: TAILLE DU TRADE (max 35pts) ==========
            if trade_value >= 50000:
                score += 35
                signals.append(f"💰 MEGA TRADE: ${trade_value:,.0f}")
            elif trade_value >= 10000:
                score += 28
                signals.append(f"💰 Grosse mise: ${trade_value:,.0f}")
            elif trade_value >= 5000:
                score += 20
                signals.append(f"💰 Mise significative: ${trade_value:,.0f}")
            elif trade_value >= 1000:
                score += 10
                signals.append(f"💵 Mise: ${trade_value:,.0f}")

            # ========== FACTEUR 2: PRIX EXTRÊME (max 20pts) ==========
            # Si les odds sont très hauts (>0.8) ou très bas (<0.1), c'est suspect
            if price > 0.85 or price < 0.10:
                score += 20
                signals.append(f"📊 Prix extrême: {price:.2%} odds")
            elif price > 0.75 or price < 0.15:
                score += 12
                signals.append(f"📊 Prix très haut/bas: {price:.2%} odds")

            # ========== FACTEUR 3: TIMING (max 20pts) ==========
            # Les insiders tradent souvent à heures bizarres
            timestamp_str = trade.get('timestamp')
            if timestamp_str:
                try:
                    # Parse ISO format timestamp
                    dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    hour = dt.hour
                    
                    # 00:00-06:00 ou 22:00-23:59 = heures bizarres
                    if hour < 6 or hour >= 22:
                        if trade_value >= MIN_BET_THRESHOLD:
                            score += 18
                            signals.append(f"⏰ Trade à {hour}h (suspect)")
                    # 09:00-17:00 = heures normales (moins suspect)
                    elif 9 <= hour <= 17:
                        score -= 5  # Pénalité mineure
                except:
                    pass

            # ========== FACTEUR 4: NOUVEAU WALLET (max 25pts) ==========
            wallet_trades = await self.fetch_wallet_trades(wallet, limit=50)
            num_wallet_trades = len(wallet_trades)
            
            if num_wallet_trades == 0:
                score += 25
                signals.append("🆕 WALLET NEUF (0 trades)")
            elif num_wallet_trades == 1:
                score += 20
                signals.append("🆕 Wallet quasi-neuf (1 trade)")
            elif num_wallet_trades <= 3:
                score += 15
                signals.append(f"⚠️ Peu d'activité ({num_wallet_trades} trades)")
            elif num_wallet_trades >= 100:
                score -= 10  # Whale établi = moins suspect

            # ========== FACTEUR 5: CONCENTRATION (max 10pts) ==========
            # Si le wallet parie 100% sur UN seul résultat = suspect
            if num_wallet_trades <= 2 and trade_value >= MIN_BET_THRESHOLD:
                score += 10
                signals.append("🎯 100% concentration sur ce marché")

        except Exception as e:
            print(f"❌ Erreur scoring: {e}")
            return 0, []

        # Normalise entre 0-100
        final_score = min(100, max(0, score))
        return final_score, signals

    # ============================================================
    # LOOP DÉTECTION
    # ============================================================

    @tasks.loop(seconds=SCAN_INTERVAL)
    async def detector_loop(self):
        """Boucle principale - scanne toutes les 30 secondes"""
        try:
            print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] SCAN EN COURS...")
            
            # Récupère les trades
            trades = await self.fetch_trades(limit=MAX_TRADES_CHECK)
            
            if not trades:
                print("⚠️ Aucun trade reçu")
                return
            
            print(f"📊 {len(trades)} trades analysés")
            
            alerts_this_scan = 0
            
            # Analyse chaque trade
            for trade in trades:
                try:
                    # Crée un ID unique pour chaque trade
                    trade_id = f"{trade.get('proxyWallet')}-{trade.get('conditionId')}-{trade.get('timestamp')}"
                    
                    # Skip si déjà traité
                    if trade_id in self.processed_trades:
                        continue
                    
                    self.processed_trades.add(trade_id)
                    
                    # Garde seulement les 2000 derniers
                    if len(self.processed_trades) > 2000:
                        self.processed_trades = set(list(self.processed_trades)[-1000:])
                    
                    # Score le trade
                    score, signals = await self.score_insider(trade)
                    
                    # Envoie alerte si score >= 50%
                    if score >= MIN_INSIDER_SCORE and signals:
                        await self.send_alert(trade, score, signals)
                        alerts_this_scan += 1
                        self.alerts_today += 1
                        
                except Exception as e:
                    print(f"⚠️ Erreur trade: {e}")
                    continue
            
            # Affiche résumé
            uptime = datetime.now() - self.start_time
            print(f"✅ Scan terminé - {alerts_this_scan} alerte(s)")
            print(f"   Alertes aujourd'hui: {self.alerts_today}")
            print(f"   Uptime: {str(uptime).split('.')[0]}")
            
        except Exception as e:
            print(f"❌ Erreur loop: {e}")

    # ============================================================
    # ENVOI ALERTES DISCORD
    # ============================================================

    async def send_alert(self, trade: Dict, score: int, signals: List[str]):
        """Envoie une alerte Discord"""
        try:
            channel = self.bot.get_channel(CHANNEL_ID)
            if not channel:
                print(f"❌ Channel {CHANNEL_ID} not found!")
                return
            
            # Extraction données
            wallet = trade.get('proxyWallet', 'unknown')[:10]
            market = trade.get('title', 'Unknown')[:60]
            outcome = trade.get('outcome', '?')
            side = trade.get('side', 'UNKNOWN')
            size = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            trade_value = size * price
            slug = trade.get('slug', '')
            
            # URL du marché
            market_url = f"https://polymarket.com/market/{slug}" if slug else "https://polymarket.com"
            
            # Couleur selon score
            if score >= 80:
                color = discord.Color.red()
                emoji = "🚨"
                severity = "TRÈS ÉLEVÉ"
            elif score >= 70:
                color = discord.Color.orange()
                emoji = "⚠️"
                severity = "ÉLEVÉ"
            elif score >= 60:
                color = discord.Color.gold()
                emoji = "👀"
                severity = "MOYEN"
            else:
                color = discord.Color.blue()
                emoji = "💡"
                severity = "À SURVEILLER"
            
            # Créé l'embed
            embed = discord.Embed(
                title=f"{emoji} INSIDER DÉTECTÉ - {score}%",
                description=f"**{market}**\n→ {outcome}",
                color=color,
                url=market_url,
                timestamp=datetime.now()
            )
            
            # Données principales
            embed.add_field(
                name="💰 Trade",
                value=f"**${trade_value:,.0f}**\n{side}",
                inline=True
            )
            
            embed.add_field(
                name="📊 Odds",
                value=f"**{price:.2%}**\n{size:.0f} shares",
                inline=True
            )
            
            # Signaux détectés
            if signals:
                signals_text = "\n".join(f"• {s}" for s in signals[:5])
                embed.add_field(
                    name="🔍 Signaux",
                    value=signals_text,
                    inline=False
                )
            
            # Info wallet
            embed.add_field(
                name="👤 Wallet",
                value=f"`{wallet}...`",
                inline=True
            )
            
            embed.add_field(
                name="⏰ Sévérité",
                value=severity,
                inline=True
            )
            
            # Footer
            embed.set_footer(
                text=f"Insider Score: {score}% | {datetime.now().strftime('%H:%M:%S UTC')}"
            )
            
            # Envoie l'alerte
            await channel.send(embed=embed)
            print(f"✅ ALERTE ENVOYÉE: {market[:30]} (Score: {score}%)")
            
        except Exception as e:
            print(f"❌ Erreur send_alert: {e}")

    @detector_loop.before_loop
    async def before_detector_loop(self):
        """Attend que le bot soit prêt"""
        await self.bot.wait_until_ready()
        print("✅ Bot prêt, détecteur d'insiders démarré!")

# ============================================================
# BOT DISCORD
# ============================================================

def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True
    
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"\n{'='*60}")
        print(f"✅ BOT CONNECTÉ: {bot.user}")
        print(f"{'='*60}\n")
        
        # Ajoute le cog si pas déjà présent
        if not bot.cogs.get('InsiderDetectorBot'):
            cog = InsiderDetectorBot(bot)
            await cog.cog_load()
            await bot.add_cog(cog)
    
    return bot

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 POLYMARKET INSIDER DETECTOR BOT")
    print("="*60)
    print(f"⚙️  Seuil minimum d'alerte: {MIN_INSIDER_SCORE}%")
    print(f"⚙️  Scan interval: {SCAN_INTERVAL} secondes")
    print(f"⚙️  Min bet: ${MIN_BET_THRESHOLD}")
    print("="*60 + "\n")
    
    bot = create_bot()
    bot.run(DISCORD_TOKEN)
