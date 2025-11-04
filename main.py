#!/usr/bin/env python3
"""
🚀 POLYMARKET INSIDER BOT - FIXED & WORKING
Calcul correct du trade value depuis l'API response réelle
"""

import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# CONFIG
TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
CHANNEL = int(os.getenv("DISCORD_CHANNEL_ID") or os.getenv("CHANNEL_ID", "0"))

if not TOKEN or CHANNEL == 0:
    print("❌ Missing TOKEN or CHANNEL!")
    sys.exit(1)

print(f"✅ Config: Channel={CHANNEL}")

DATA_API = "https://data-api.polymarket.com"

class WorkingInsiderBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.processed = set()
        self.alerts = 0
        
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        if not self.scan.is_running():
            self.scan.start()
        print("✅ Bot loaded")
        
    async def cog_unload(self):
        self.scan.cancel()
        if self.session:
            await self.session.close()

    async def get_trades(self) -> list:
        """Récupère les trades depuis l'API"""
        try:
            url = f"{DATA_API}/trades"
            params = {"limit": 500}
            
            async with self.session.get(url, params=params, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        return data
                    return []
        except Exception as e:
            print(f"❌ API error: {e}")
        return []

    def calculate_trade_value(self, trade: Dict) -> float:
        """
        Calcule la vraie valeur du trade en USDC
        
        IMPORTANT: L'API retourne:
        - size: nombre de shares
        - price: odds (0-1)
        - usdcSize: OPTIONNEL (souvent N/A)
        
        Pour Polymarket:
        Le vrai coût = size * price (en USDC)
        car Polymarket = binary options
        """
        try:
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            
            # usdcSize si disponible (préféré)
            usdc_size = trade.get("usdcSize")
            if usdc_size:
                try:
                    return float(usdc_size)
                except:
                    pass
            
            # Sinon calcule: size * price
            # C'est la vraie valeur en Polymarket
            return size * price
            
        except:
            return 0

    async def detect_insider(self, trade: Dict) -> tuple:
        """Détecte les insiders avec scoring simple et bon"""
        
        # Calcule la vraie valeur
        trade_value = self.calculate_trade_value(trade)
        
        # Données
        wallet = trade.get("proxyWallet", "")
        price = float(trade.get("price", 0))
        outcome = trade.get("outcome", "")
        title = trade.get("title", "Unknown")[:40]
        side = trade.get("side", "")
        
        # Seuil minimum
        if trade_value < 5000:
            return 0, []
        
        score = 0
        signals = []
        
        # CHECK 1: TAILLE
        print(f"      Trade value: ${trade_value:,.0f}", end="")
        if trade_value >= 50000:
            score += 40
            signals.append(f"💰 ${trade_value:,.0f}")
            print(" ✅ +40")
        elif trade_value >= 10000:
            score += 25
            signals.append(f"💰 ${trade_value:,.0f}")
            print(" ✅ +25")
        elif trade_value >= 5000:
            score += 15
            signals.append(f"💰 ${trade_value:,.0f}")
            print(" ✅ +15")
        
        # CHECK 2: PRICE EXTREME
        print(f"      Price: {price:.1%}", end="")
        if price < 0.05 or price > 0.95:
            score += 30
            signals.append(f"🚨 {price:.1%}")
            print(" ✅ +30")
        elif price < 0.10 or price > 0.90:
            score += 20
            signals.append(f"⚠️ {price:.1%}")
            print(" ✅ +20")
        else:
            print(" ⚠️ normal")
        
        # Final
        final = min(100, score)
        print(f"      SCORE: {final}%", end="")
        
        if final >= 70:
            print(" ✅ ALERT!")
            return final, signals
        else:
            print()
            return 0, []

    @tasks.loop(seconds=60)
    async def scan(self):
        """Main scan"""
        print(f"\n🔍 SCAN - [{datetime.now().strftime('%H:%M:%S')}]")
        print("-" * 60)
        
        trades = await self.get_trades()
        print(f"📊 {len(trades)} trades")
        print()
        
        if not trades:
            print("❌ No trades\n")
            return
        
        alerts = 0
        
        for i, trade in enumerate(trades[:50]):
            try:
                trade_id = f"{trade.get('proxyWallet')}-{trade.get('timestamp')}"
                
                if trade_id in self.processed:
                    continue
                
                self.processed.add(trade_id)
                
                print(f"Trade {i+1}: {trade.get('title', 'Unknown')[:30]}")
                score, signals = await self.detect_insider(trade)
                
                if score >= 70:
                    print(f"   → SENDING ALERT!\n")
                    await self.send_alert(trade, score, signals)
                    alerts += 1
                    self.alerts += 1
                
            except Exception as e:
                print(f"Error: {e}\n")
                continue
        
        print("-" * 60)
        print(f"✅ {alerts} alerts | Total today: {self.alerts}\n")

    async def send_alert(self, trade: Dict, score: int, signals: List[str]):
        """Send Discord alert"""
        try:
            channel = self.bot.get_channel(CHANNEL)
            if not channel:
                return
            
            title = trade.get("title", "Unknown")[:60]
            outcome = trade.get("outcome", "?")
            trade_value = self.calculate_trade_value(trade)
            price = float(trade.get("price", 0))
            wallet = trade.get("proxyWallet", "unknown")[:10]
            slug = trade.get("slug", "")
            
            url = f"https://polymarket.com/market/{slug}" if slug else "https://polymarket.com"
            
            embed = discord.Embed(
                title=f"🚨 INSIDER - {score}%",
                description=f"**{title}**\n→ {outcome}",
                color=discord.Color.red(),
                url=url
            )
            
            embed.add_field(name="💰 Trade Value", value=f"${trade_value:,.0f}", inline=True)
            embed.add_field(name="📊 Odds", value=f"{price:.2%}", inline=True)
            embed.add_field(name="👤 Wallet", value=f"`{wallet}...`", inline=True)
            
            if signals:
                embed.add_field(name="🔍 Signals", value="\n".join(f"• {s}" for s in signals), inline=False)
            
            await channel.send(embed=embed)
            
        except Exception as e:
            print(f"❌ Discord error: {e}")

    @scan.before_loop
    async def before_scan(self):
        await self.bot.wait_until_ready()
        print("✅ Scanner ready!\n")

# BOT
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"\n✅ BOT: {bot.user}\n")
    if not bot.cogs.get('WorkingInsiderBot'):
        cog = WorkingInsiderBot(bot)
        await cog.cog_load()
        await bot.add_cog(cog)

if __name__ == "__main__":
    print("\n🚀 POLYMARKET INSIDER BOT - WORKING VERSION\n")
    bot.run(TOKEN)
