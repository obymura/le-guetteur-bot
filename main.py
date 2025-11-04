import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
from datetime import datetime
from typing import Optional, Dict, List

# ============================================================
# CONFIG RAILWAY
# ============================================================

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID") or os.getenv("CHANNEL_ID", "0"))

if not DISCORD_TOKEN:
    print("❌ DISCORD_TOKEN non défini")
    sys.exit(1)

if CHANNEL_ID == 0:
    print("❌ CHANNEL_ID non défini")
    sys.exit(1)

print(f"✅ Config chargée: Channel={CHANNEL_ID}")

# ============================================================
# APIs
# ============================================================

DATA_API = "https://data-api.polymarket.com"

# Thresholds
MIN_BET_SIZE = 5000  # $5K minimum
MIN_SCORE = 65  # 65% pour alerte

# ============================================================
# BOT
# ============================================================

class PolymarketBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.checked_trades = set()  # Éviter doublons
        self.alerts_sent = 0
        
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.scan_markets.start()
        
    async def cog_unload(self):
        self.scan_markets.cancel()
        if self.session:
            await self.session.close()

    # ============================================================
    # API CALLS
    # ============================================================
    
    async def get_recent_trades(self, limit: int = 200) -> List[Dict]:
        """Récupère les trades récents"""
        try:
            async with self.session.get(
                f"{DATA_API}/trades",
                params={"limit": limit},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            print(f"❌ Erreur trades API: {e}")
            return []

    async def get_wallet_activity(self, wallet: str) -> Dict:
        """Récupère l'activité d'un wallet"""
        try:
            async with self.session.get(
                f"{DATA_API}/activity",
                params={"proxyWallet": wallet, "limit": 100},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    return {
                        "num_trades": len(trades) if isinstance(trades, list) else 0,
                        "trades": trades if isinstance(trades, list) else []
                    }
                return {"num_trades": 0, "trades": []}
        except Exception as e:
            print(f"❌ Erreur wallet API: {e}")
            return {"num_trades": 0, "trades": []}

    # ============================================================
    # SCORING
    # ============================================================
    
    async def calculate_score(self, trade: Dict, wallet_info: Dict) -> int:
        """Calcule le score d'insider (0-100)"""
        score = 0
        
        try:
            # Taille du trade
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            trade_value = size * price
            
            # 1. TAILLE (max 40pts)
            if trade_value >= 50000:
                score += 40
            elif trade_value >= 10000:
                score += 30
            elif trade_value >= 5000:
                score += 20
            else:
                return 0  # Skip petits trades
            
            # 2. WALLET NEUF (max 35pts)
            num_trades = wallet_info.get("num_trades", 0)
            if num_trades == 0:
                score += 35
            elif num_trades <= 2:
                score += 25
            elif num_trades <= 5:
                score += 15
            elif num_trades > 50:
                score -= 10
            
            # 3. TIMING (max 15pts)
            timestamp = trade.get("timestamp")
            if timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    hour = dt.hour
                    if hour < 6 or hour > 22:  # Late night/early morning
                        if trade_value >= MIN_BET_SIZE:
                            score += 15
                except:
                    pass
            
            # 4. CONCENTRATION (max 10pts)
            if num_trades <= 2 and trade_value >= MIN_BET_SIZE:
                score += 10
            
        except Exception as e:
            print(f"⚠️ Erreur scoring: {e}")
            return 0
        
        return min(100, max(0, score))

    # ============================================================
    # SCAN
    # ============================================================
    
    @tasks.loop(minutes=2)
    async def scan_markets(self):
        """Scanne les trades toutes les 2 minutes"""
        print(f"\n{'='*60}")
        print(f"🔍 [{datetime.now().strftime('%H:%M:%S')}] SCAN POLYMARKET")
        print(f"{'='*60}")
        
        try:
            trades = await self.get_recent_trades(limit=150)
            if not trades:
                print("⚠️ Aucun trade trouvé")
                return
            
            print(f"📊 {len(trades)} trades reçus")
            
            alerts = 0
            for trade in trades[:100]:  # Analyse top 100
                try:
                    # Skip doublons
                    trade_id = f"{trade.get('proxyWallet')}-{trade.get('timestamp')}"
                    if trade_id in self.checked_trades:
                        continue
                    self.checked_trades.add(trade_id)
                    
                    # Limiter le cache
                    if len(self.checked_trades) > 500:
                        self.checked_trades = set(list(self.checked_trades)[-500:])
                    
                    # Skip petits trades
                    size = float(trade.get("size", 0))
                    price = float(trade.get("price", 0))
                    if size * price < MIN_BET_SIZE:
                        continue
                    
                    # Récupère stats wallet
                    wallet = trade.get("proxyWallet", "unknown")
                    wallet_info = await self.get_wallet_activity(wallet)
                    
                    # Calcule score
                    score = await self.calculate_score(trade, wallet_info)
                    
                    # Envoie alerte si bon score
                    if score >= MIN_SCORE:
                        await self.send_alert(trade, wallet_info, score)
                        alerts += 1
                        self.alerts_sent += 1
                        
                except Exception as e:
                    print(f"⚠️ Erreur trade: {e}")
                    continue
            
            print(f"✅ SCAN TERMINÉ - {alerts} alerte(s)")
            print(f"   Total aujourd'hui: {self.alerts_sent}")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"❌ Erreur scan: {e}")

    # ============================================================
    # ALERTES
    # ============================================================
    
    async def send_alert(self, trade: Dict, wallet_info: Dict, score: int):
        """Envoie une alerte Discord"""
        try:
            channel = self.bot.get_channel(CHANNEL_ID)
            if not channel:
                print(f"❌ Channel {CHANNEL_ID} not found")
                return
            
            # Données
            wallet = trade.get("proxyWallet", "unknown")[:10]
            market_name = trade.get("title", "Unknown")
            outcome = trade.get("outcome", "?")
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            trade_value = size * price
            side = trade.get("side", "UNKNOWN")
            
            # Couleur selon score
            if score >= 85:
                color = discord.Color.red()
                emoji = "🚨"
            elif score >= 75:
                color = discord.Color.orange()
                emoji = "⚠️"
            else:
                color = discord.Color.gold()
                emoji = "👀"
            
            # Embed
            embed = discord.Embed(
                title=f"{emoji} INSIDER DÉTECTÉ - {score}%",
                description=f"**{market_name}**\n→ {outcome}",
                color=color,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="💰 Trade",
                value=f"${trade_value:,.0f}\n{side}",
                inline=True
            )
            
            embed.add_field(
                name="👤 Wallet",
                value=f"{wallet_info.get('num_trades')} trades\n`{wallet}...`",
                inline=True
            )
            
            embed.add_field(
                name="🔗 Lien",
                value=f"https://polymarket.com/market/{trade.get('slug', '')}",
                inline=False
            )
            
            await channel.send(embed=embed)
            print(f"✅ Alerte: {market_name[:30]} ({score}%)")
            
        except Exception as e:
            print(f"❌ Erreur alerte: {e}")

    @scan_markets.before_loop
    async def before_scan(self):
        """Attend que le bot soit prêt"""
        await self.bot.wait_until_ready()
        print("✅ Bot prêt, scanner démarré!")

# ============================================================
# BOT DISCORD
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"\n✅ BOT CONNECTÉ: {bot.user}")
    if not bot.cogs.get('PolymarketBot'):
        cog = PolymarketBot(bot)
        await cog.cog_load()
        await bot.add_cog(cog)

# ============================================================
# DÉMARRAGE
# ============================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 POLYMARKET INSIDER BOT")
    print("="*60 + "\n")
    bot.run(DISCORD_TOKEN)
