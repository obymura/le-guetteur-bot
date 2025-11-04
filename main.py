import discord
from discord.ext import commands, tasks
import aiohttp
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import asyncio

# Configuration
DISCORD_TOKEN = "YOUR_DISCORD_BOT_TOKEN"
CHANNEL_ID = YOUR_CHANNEL_ID  # Channel où envoyer les alertes
DATA_API = "https://data-api.polymarket.com"
POLYMARKET_ANALYTICS_API = "https://polymarketanalytics.com/api"

# Scoring thresholds
MIN_ALERT_SCORE = 65  # Minimum score pour envoyer une alerte
WHALE_TRADE_SIZE = 5000  # $5K minimum
MEGA_WHALE = 10000  # $10K
GIGANTIC_WHALE = 50000  # $50K

class PolymarketInsiderBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.markets_cache = {}
        self.wallet_stats_cache = {}
        
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.check_insider_activity.start()
        
    async def cog_unload(self):
        self.check_insider_activity.cancel()
        if self.session:
            await self.session.close()

    # ============================================================
    # FONCTIONS D'API
    # ============================================================
    
    async def get_recent_trades(self, limit: int = 500) -> List[Dict]:
        """Récupère les trades récents depuis l'API Polymarket"""
        try:
            async with self.session.get(
                f"{DATA_API}/trades",
                params={"limit": limit},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    return trades if isinstance(trades, list) else []
                return []
        except Exception as e:
            print(f"❌ Erreur API trades: {e}")
            return []

    async def get_wallet_stats(self, wallet: str) -> Dict:
        """Récupère les stats d'un wallet (nombre de trades, P&L, win rate)"""
        try:
            # Cherche le wallet dans les stats publiques
            async with self.session.get(
                f"{DATA_API}/activity",
                params={"proxyWallet": wallet, "limit": 1000},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    if isinstance(trades, list) and len(trades) > 0:
                        return self._calculate_wallet_stats(trades, wallet)
            
            # Fallback: Retourne des stats basiques
            return {
                "num_trades": 0,
                "pnl": 0,
                "win_rate": 0,
                "markets_traded": 0,
                "total_volume": 0
            }
        except Exception as e:
            print(f"❌ Erreur stats wallet {wallet}: {e}")
            return {
                "num_trades": 0,
                "pnl": 0,
                "win_rate": 0,
                "markets_traded": 0,
                "total_volume": 0
            }

    async def get_market_info(self, condition_id: str) -> Dict:
        """Récupère les infos d'un marché"""
        try:
            async with self.session.get(
                f"{DATA_API}/markets",
                params={"condition_id": condition_id},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    markets = await resp.json()
                    return markets[0] if markets else {}
            return {}
        except Exception as e:
            print(f"❌ Erreur info marché: {e}")
            return {}

    def _calculate_wallet_stats(self, trades: List[Dict], wallet: str) -> Dict:
        """Calcule les stats d'un wallet à partir de ses trades"""
        if not trades:
            return {
                "num_trades": 0,
                "pnl": 0,
                "win_rate": 0,
                "markets_traded": 0,
                "total_volume": 0
            }
        
        num_trades = len(trades)
        winning_trades = len([t for t in trades if t.get("pnl", 0) > 0])
        total_volume = sum(float(t.get("size", 0)) * float(t.get("price", 0)) for t in trades)
        total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
        markets = len(set(t.get("conditionId") for t in trades if t.get("conditionId")))
        win_rate = (winning_trades / num_trades * 100) if num_trades > 0 else 0
        
        return {
            "num_trades": num_trades,
            "pnl": total_pnl,
            "win_rate": round(win_rate, 1),
            "markets_traded": markets,
            "total_volume": round(total_volume, 2)
        }

    # ============================================================
    # SCORING D'INSIDERS
    # ============================================================
    
    async def calculate_insider_score(self, trade: Dict, wallet_stats: Dict) -> tuple[int, List[str]]:
        """Calcule le score d'insider basé sur critères réalistes"""
        score = 0
        signals = []
        
        try:
            trade_size = float(trade.get("size", 0)) * float(trade.get("price", 0))
            num_trades = wallet_stats.get("num_trades", 0)
            win_rate = wallet_stats.get("win_rate", 0)
            
            # 1. TAILLE DU TRADE
            if trade_size >= GIGANTIC_WHALE:  # $50K+
                score += 30
                signals.append(f"💰 Grosse mise: ${trade_size:,.0f}")
            elif trade_size >= MEGA_WHALE:  # $10K+
                score += 20
                signals.append(f"💰 Mise importante: ${trade_size:,.0f}")
            elif trade_size >= WHALE_TRADE_SIZE:  # $5K+
                score += 10
                signals.append(f"💰 Mise: ${trade_size:,.0f}")
            
            # 2. NOMBRE DE TRADES (insider = peu de trades = nouveau compte)
            if num_trades == 0:
                score += 25
                signals.append("🆕 Wallet neuf (0 trades)")
            elif num_trades == 1:
                score += 20
                signals.append("🆕 Compte quasi-neuf (1 trade)")
            elif num_trades <= 3:
                score += 10
                signals.append(f"⚠️ Compte peu actif ({num_trades} trades)")
            elif num_trades > 50:
                score -= 10  # Whale établi, moins suspect
                signals.append(f"👤 Trader établi ({num_trades} trades)")
            
            # 3. WIN RATE
            if win_rate >= 80 and num_trades >= 5:
                score += 15
                signals.append(f"🎯 Win rate excellent: {win_rate}%")
            elif win_rate >= 60 and num_trades >= 10:
                score += 10
                signals.append(f"📊 Win rate bon: {win_rate}%")
            elif win_rate <= 30 and num_trades >= 5:
                score -= 5  # Losing trader, moins crédible
                signals.append(f"❌ Win rate faible: {win_rate}%")
            
            # 4. TIMING (heures bizarres = 23h-6h)
            hour = datetime.utcnow().hour
            if 23 <= hour or hour <= 6:
                if trade_size >= WHALE_TRADE_SIZE:
                    score += 10
                    signals.append("⏰ Trade à heures bizarres")
            
            # 5. PREMIÈRE POSITION UNIQUE (si c'est son premier trade sur ce marché)
            if num_trades <= 2 and trade_size >= WHALE_TRADE_SIZE:
                score += 15
                signals.append("🎯 Concentration: trade unique sur ce marché")
            
        except Exception as e:
            print(f"⚠️ Erreur scoring: {e}")
        
        return max(0, min(100, score)), signals  # Score entre 0-100

    # ============================================================
    # DÉTECTION ET ALERTES
    # ============================================================
    
    @tasks.loop(minutes=1)
    async def check_insider_activity(self):
        """Scanne les trades toutes les minutes"""
        print(f"🔍 [{datetime.utcnow().strftime('%H:%M:%S')}] SCAN POLYMARKET - Recherche d'insiders...")
        
        # Récupère les trades récents
        trades = await self.get_recent_trades(limit=200)
        if not trades:
            print("❌ Aucun trade trouvé")
            return
        
        alerts_sent = 0
        
        for trade in trades[:50]:  # Analyse les 50 premiers
            try:
                wallet = trade.get("proxyWallet", "unknown")
                trade_size = float(trade.get("size", 0)) * float(trade.get("price", 0))
                
                # Skip les petits trades
                if trade_size < WHALE_TRADE_SIZE:
                    continue
                
                # Récupère les stats du wallet
                wallet_stats = await self.get_wallet_stats(wallet)
                
                # Calcule le score d'insider
                score, signals = await self.calculate_insider_score(trade, wallet_stats)
                
                # Si score >= seuil, envoie une alerte
                if score >= MIN_ALERT_SCORE:
                    await self.send_alert(trade, wallet_stats, score, signals)
                    alerts_sent += 1
                    await asyncio.sleep(2)  # Rate limiting
                    
            except Exception as e:
                print(f"⚠️ Erreur traitement trade: {e}")
                continue
        
        print(f"✅ SCAN TERMINÉ - {alerts_sent} alerte(s) envoyée(s)")

    async def send_alert(self, trade: Dict, wallet_stats: Dict, score: int, signals: List[str]):
        """Envoie une alerte Discord"""
        try:
            channel = self.bot.get_channel(CHANNEL_ID)
            if not channel:
                return
            
            # Prépare les données
            wallet = trade.get("proxyWallet", "unknown")[:6] + "..."
            market_name = trade.get("title", "Marché inconnu")
            outcome = trade.get("outcome", "?")
            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            trade_value = size * price
            market_url = f"https://polymarket.com/market/{trade.get('slug', '')}" if trade.get('slug') else "https://polymarket.com"
            
            # Score color
            if score >= 90:
                color = discord.Color.red()  # 🔴 RED - Insider PROBABLE
                emoji = "🚨"
            elif score >= 75:
                color = discord.Color.orange()  # 🟠 ORANGE - Suspect
                emoji = "⚠️"
            else:
                color = discord.Color.yellow()  # 🟡 YELLOW - À surveiller
                emoji = "👀"
            
            # Crée l'embed
            embed = discord.Embed(
                title=f"{emoji} INSIDER DÉTECTÉ (Score: {score}%)",
                description=f"**{market_name}**\n→ {outcome}",
                color=color,
                url=market_url,
                timestamp=datetime.utcnow()
            )
            
            # Infos du trade
            embed.add_field(
                name="💰 Trade Info",
                value=f"Size: {size:.0f} @ ${price:.4f}\nValeur: **${trade_value:,.2f}**",
                inline=True
            )
            
            # Stats du wallet
            embed.add_field(
                name="👤 Wallet Stats",
                value=(
                    f"Trades: **{wallet_stats['num_trades']}**\n"
                    f"P&L: **${wallet_stats['pnl']:,.2f}**\n"
                    f"Win Rate: **{wallet_stats['win_rate']}%**"
                ),
                inline=True
            )
            
            # Signaux détectés
            if signals:
                embed.add_field(
                    name="🔍 Signaux",
                    value="\n".join(signals),
                    inline=False
                )
            
            # Adresse wallet
            embed.add_field(
                name="🔗 Wallet",
                value=f"`{trade.get('proxyWallet', 'unknown')}`",
                inline=False
            )
            
            embed.set_footer(text=f"Analyser sur PolymarketAnalytics | {datetime.utcnow().strftime('%H:%M:%S UTC')}")
            
            await channel.send(embed=embed)
            print(f"✅ Alerte envoyée: {market_name} (Score: {score}%)")
            
        except Exception as e:
            print(f"❌ Erreur envoi alerte: {e}")

# ============================================================
# INITIALISATION BOT
# ============================================================

class MyBot(commands.Bot):
    async def on_ready(self):
        print(f"✅ Bot connecté: {self.user}")
        await self.add_cog(PolymarketInsiderBot(self))

bot = MyBot(command_prefix="!", intents=discord.Intents.default())

@bot.event
async def on_ready():
    print(f"✅ {bot.user} connecté et prêt!")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
