#!/usr/bin/env python3
"""
🚀 POLYMARKET INSIDER BOT - WITH ULTRA-DETAILED LOGGING
Shows EXACTLY what happens with each trade
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

class DebugInsiderBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.processed = set()
        self.alerts = 0
        self.scan_count = 0
        
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
        """Get trades with detailed logging"""
        try:
            url = f"{DATA_API}/trades"
            params = {"limit": 100}  # Smaller limit for debugging
            
            print(f"🔗 API Call: GET {url}?limit=100")
            
            async with self.session.get(url, params=params, timeout=20) as resp:
                print(f"   Status: {resp.status}")
                
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   Response type: {type(data)}")
                    
                    if isinstance(data, list):
                        print(f"   ✅ Got {len(data)} trades (list)")
                        
                        # Log first trade structure
                        if len(data) > 0:
                            first = data[0]
                            print(f"   First trade keys: {list(first.keys())}")
                        
                        return data
                    else:
                        print(f"   ❌ Not a list! Type: {type(data)}")
                        if isinstance(data, dict):
                            print(f"   Keys: {list(data.keys())}")
                        return []
                else:
                    text = await resp.text()
                    print(f"   ❌ Error: {text[:200]}")
                    return []
                    
        except Exception as e:
            print(f"❌ Exception: {e}")
            return []

    async def analyze_trade(self, trade: Dict) -> tuple:
        """Analyze trade with ULTRA detailed logging"""
        
        wallet = trade.get("proxyWallet", "N/A")
        timestamp = trade.get("timestamp", "N/A")
        size = trade.get("size", "N/A")
        usdc = trade.get("usdcSize", "N/A")
        price = trade.get("price", "N/A")
        outcome = trade.get("outcome", "N/A")
        title = trade.get("title", "N/A")[:40]
        side = trade.get("side", "N/A")
        
        print(f"   📊 Trade: {title}")
        print(f"      Wallet: {wallet[:10]}...")
        print(f"      Size: {size} | USDC: {usdc} | Price: {price}")
        print(f"      Outcome: {outcome} | Side: {side}")
        
        score = 0
        signals = []
        
        # Convert to float for comparison
        try:
            usdc_val = float(usdc) if usdc != "N/A" else 0
            price_val = float(price) if price != "N/A" else 0.5
            
            # Check 1: Size
            print(f"      Check 1 - Size: ${usdc_val:,.0f}", end="")
            if usdc_val < 10000:
                print(" ❌ (< $10K)")
                return 0, []
            elif usdc_val >= 50000:
                score += 35
                signals.append(f"💰 ${usdc_val:,.0f}")
                print(f" ✅ +35 pts (${usdc_val:,.0f})")
            elif usdc_val >= 10000:
                score += 20
                signals.append(f"💰 ${usdc_val:,.0f}")
                print(f" ✅ +20 pts (${usdc_val:,.0f})")
            
            # Check 2: Price
            print(f"      Check 2 - Price: {price_val:.1%}", end="")
            if price_val < 0.05 or price_val > 0.95:
                score += 25
                signals.append(f"🚨 {price_val:.1%}")
                print(f" ✅ +25 pts (extreme)")
            elif price_val < 0.10 or price_val > 0.90:
                score += 18
                signals.append(f"⚠️ {price_val:.1%}")
                print(f" ✅ +18 pts (very high/low)")
            else:
                print(f" ⚠️ 0 pts (normal)")
            
            # Final score
            final = min(100, score)
            print(f"      FINAL SCORE: {final}%", end="")
            
            if final >= 80:
                print(" ✅ ALERT!")
                return final, signals
            else:
                print(" ❌ Too low")
                return 0, []
                
        except Exception as e:
            print(f"      ❌ Error parsing: {e}")
            return 0, []

    @tasks.loop(seconds=120)  # Longer interval for debugging
    async def scan(self):
        """Main scan with detailed logging"""
        self.scan_count += 1
        
        print(f"\n{'='*80}")
        print(f"🔍 SCAN #{self.scan_count} - [{datetime.now().strftime('%H:%M:%S')}]")
        print(f"{'='*80}")
        
        trades = await self.get_trades()
        
        if not trades:
            print("❌ No trades fetched!\n")
            return
        
        print(f"\n📊 Analyzing {len(trades)} trades...")
        print()
        
        alerts = 0
        analyzed = 0
        
        for i, trade in enumerate(trades[:20]):  # Only first 20 for debugging
            try:
                trade_id = f"{trade.get('proxyWallet')}-{trade.get('timestamp')}"
                
                if trade_id in self.processed:
                    print(f"   Trade {i+1}: SKIP (already seen)")
                    continue
                
                self.processed.add(trade_id)
                
                print(f"   Trade {i+1}/{min(20, len(trades))}:")
                score, signals = await self.analyze_trade(trade)
                
                if score >= 80:
                    print(f"      → SENDING ALERT!\n")
                    await self.send_alert(trade, score, signals)
                    alerts += 1
                    self.alerts += 1
                else:
                    print()
                
                analyzed += 1
                
            except Exception as e:
                print(f"   Trade {i+1}: ERROR - {e}\n")
                continue
        
        print(f"{'='*80}")
        print(f"✅ Scan complete")
        print(f"   Trades analyzed: {analyzed}")
        print(f"   Alerts sent: {alerts}")
        print(f"   Total alerts today: {self.alerts}")
        print(f"{'='*80}\n")

    async def send_alert(self, trade: Dict, score: int, signals: List[str]):
        """Send Discord alert"""
        try:
            channel = self.bot.get_channel(CHANNEL)
            if not channel:
                print(f"❌ Channel not found!")
                return
            
            title = trade.get("title", "Unknown")[:60]
            outcome = trade.get("outcome", "?")
            usdc = trade.get("usdcSize", 0)
            price = trade.get("price", 0)
            wallet = trade.get("proxyWallet", "unknown")[:10]
            
            embed = discord.Embed(
                title=f"🚨 INSIDER - {score}%",
                description=f"**{title}**\n→ {outcome}",
                color=discord.Color.red()
            )
            
            embed.add_field(name="💰", value=f"${usdc:,.0f}", inline=True)
            embed.add_field(name="📊", value=f"{price:.2%}", inline=True)
            embed.add_field(name="👤", value=f"`{wallet}...`", inline=True)
            
            if signals:
                embed.add_field(name="🔍", value="\n".join(f"• {s}" for s in signals), inline=False)
            
            await channel.send(embed=embed)
            print(f"✅ Alert sent to Discord!")
            
        except Exception as e:
            print(f"❌ Discord error: {e}")

    @scan.before_loop
    async def before_scan(self):
        await self.bot.wait_until_ready()
        print("✅ Scanner ready!")

# BOT
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"\n✅ BOT: {bot.user}\n")
    if not bot.cogs.get('DebugInsiderBot'):
        cog = DebugInsiderBot(bot)
        await cog.cog_load()
        await bot.add_cog(cog)

if __name__ == "__main__":
    print("\n🚀 POLYMARKET INSIDER BOT - DEBUG MODE\n")
    bot.run(TOKEN)
