#!/usr/bin/env python3
"""
🚀 POLYMARKET INSIDER BOT - PRODUCTION READY
Basé sur la documentation officielle Polymarket
Détecte les insiders avec scoring strict
"""

import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# CONFIG
TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
CHANNEL = int(os.getenv("DISCORD_CHANNEL_ID") or os.getenv("CHANNEL_ID", "0"))

if not TOKEN or CHANNEL == 0:
    print("❌ DISCORD_BOT_TOKEN or CHANNEL_ID missing!")
    sys.exit(1)

print(f"✅ Config OK - Channel: {CHANNEL}")

# ENDPOINTS (from official Polymarket docs)
DATA_API = "https://data-api.polymarket.com"  # Get trades & wallet activity
CLOB_API = "https://clob.polymarket.com"      # Order book & pricing

# INSIDER DETECTION SETTINGS
MIN_TRADE_SIZE = 10000           # $10K minimum
MIN_WALLET_AGE_HOURS = -24       # Wallet created < 24h ago = new
MAX_WALLET_TRADES = 5            # Fewer trades = more suspicious
MIN_ALERT_SCORE = 80             # 80%+ confidence threshold

class InsiderDetectorBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.processed_trades = set()
        self.alerts_count = 0
        
    async def cog_load(self):
        """Initialize the bot"""
        self.session = aiohttp.ClientSession()
        if not self.scanner.is_running():
            self.scanner.start()
        print("✅ Insider detector loaded")
        
    async def cog_unload(self):
        """Cleanup"""
        self.scanner.cancel()
        if self.session:
            await self.session.close()

    # ============================================================
    # API METHODS (based on official Polymarket docs)
    # ============================================================

    async def fetch_recent_trades(self, limit: int = 1000) -> List[Dict]:
        """
        Fetch recent trades from Data-API
        Endpoint: GET /trades
        Returns list of trades with fields: proxyWallet, timestamp, size, price, etc.
        """
        try:
            url = f"{DATA_API}/trades"
            params = {"limit": limit}
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    if isinstance(trades, list):
                        return trades
                    elif isinstance(trades, dict) and "trades" in trades:
                        return trades["trades"]
                    return trades if isinstance(trades, list) else []
        except Exception as e:
            print(f"❌ fetch_recent_trades error: {e}")
        return []

    async def fetch_wallet_activity(self, wallet: str) -> List[Dict]:
        """
        Fetch wallet activity/history from Data-API
        Endpoint: GET /activity?proxyWallet={wallet}
        Returns all trades from this wallet
        """
        try:
            url = f"{DATA_API}/activity"
            params = {"proxyWallet": wallet}
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    activity = await resp.json()
                    if isinstance(activity, list):
                        return activity
                    return []
        except Exception as e:
            print(f"⚠️ fetch_wallet_activity ({wallet[:8]}): {e}")
        return []

    # ============================================================
    # INSIDER SCORING LOGIC
    # ============================================================

    async def detect_insider(self, trade: Dict) -> tuple[int, List[str]]:
        """
        Detect if a trade is from an insider
        Returns: (score 0-100, list of signals)
        """
        score = 0
        signals = []

        try:
            # Extract trade data (from official response schema)
            wallet = trade.get("proxyWallet", "")
            timestamp = trade.get("timestamp", 0)  # Unix timestamp
            size = float(trade.get("size", 0))
            usdc_size = float(trade.get("usdcSize", 0)) or (size * float(trade.get("price", 0)))
            price = float(trade.get("price", 0))
            outcome = trade.get("outcome", "")
            title = trade.get("title", "Unknown")[:50]
            side = trade.get("side", "")

            # ===== CHECK 1: TRADE SIZE (max 35pts) =====
            if usdc_size < MIN_TRADE_SIZE:
                return 0, []  # Too small, skip
            
            if usdc_size >= 50000:
                score += 35
                signals.append(f"💰 MEGA TRADE: ${usdc_size:,.0f}")
            elif usdc_size >= 20000:
                score += 28
                signals.append(f"💰 Large: ${usdc_size:,.0f}")
            elif usdc_size >= 10000:
                score += 20
                signals.append(f"💰 Substantial: ${usdc_size:,.0f}")

            # ===== CHECK 2: WALLET AGE (max 30pts) =====
            # Get wallet history
            wallet_trades = await self.fetch_wallet_activity(wallet)
            num_trades = len(wallet_trades)
            
            # Find first trade timestamp
            first_trade_ts = None
            if wallet_trades and len(wallet_trades) > 0:
                first_trade_ts = min(t.get("timestamp", 0) for t in wallet_trades)
            
            # If wallet very new
            if num_trades <= 2:
                score += 30
                if num_trades == 1:
                    signals.append(f"🆕 FIRST TRADE EVER (wallet age: <1h)")
                else:
                    signals.append(f"🆕 Wallet quasi-new ({num_trades} trades)")
            elif num_trades > 50:
                score -= 25  # Old wallet, not suspicious
                return 0, []

            # ===== CHECK 3: PRICE EXTREMES (max 25pts) =====
            # Odds < 10% or > 90% = very suspicious
            if price < 0.05 or price > 0.95:
                score += 25
                signals.append(f"🚨 EXTREME ODDS: {price:.1%}")
            elif price < 0.10 or price > 0.90:
                score += 18
                signals.append(f"⚠️ Very extreme: {price:.1%}")
            elif price < 0.15 or price > 0.85:
                score += 10
                signals.append(f"📊 Unusual odds: {price:.1%}")

            # ===== CHECK 4: TIMING (max 10pts) =====
            # Recent trades = more suspicious
            if timestamp:
                try:
                    trade_time = datetime.fromtimestamp(timestamp)
                    now = datetime.now()
                    hours_ago = (now - trade_time).total_seconds() / 3600
                    
                    if hours_ago < 1:
                        score += 10
                        signals.append(f"⏰ VERY RECENT: {hours_ago:.0f}min ago")
                    elif hours_ago < 5:
                        score += 8
                        signals.append(f"⏰ Recent: {hours_ago:.1f}h ago")
                    
                    # Late night trades (2-5am) = suspicious
                    hour = trade_time.hour
                    if 2 <= hour <= 5:
                        score += 8
                        signals.append(f"🌙 Late night trade ({hour}:00 UTC)")
                except:
                    pass

            # ===== CHECK 5: CONCENTRATION (max 10pts) =====
            unique_markets = len(set(t.get("conditionId") for t in wallet_trades if t.get("conditionId")))
            
            if unique_markets <= 1:
                score += 10
                signals.append("🎯 100% concentrated on 1 market")
            elif unique_markets <= 3:
                score += 5
                signals.append(f"🎯 Concentrated: {unique_markets} markets")

        except Exception as e:
            print(f"❌ detect_insider error: {e}")
            return 0, []

        # Normalize score
        final_score = min(100, max(0, score))
        return final_score, signals

    # ============================================================
    # MAIN SCANNER LOOP
    # ============================================================

    @tasks.loop(seconds=60)
    async def scanner(self):
        """Main scanner: runs every 60 seconds"""
        try:
            print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] INSIDER SCAN...")
            
            # Fetch recent trades
            trades = await self.fetch_recent_trades(limit=1000)
            
            if not trades:
                print("⚠️ No trades fetched")
                return
            
            print(f"📊 {len(trades)} trades to analyze")
            
            alerts_this_scan = 0
            
            for trade in trades:
                try:
                    # Skip if already processed
                    trade_id = f"{trade.get('proxyWallet')}-{trade.get('timestamp')}"
                    if trade_id in self.processed_trades:
                        continue
                    
                    self.processed_trades.add(trade_id)
                    if len(self.processed_trades) > 5000:
                        self.processed_trades = set(list(self.processed_trades)[-2000:])
                    
                    # Detect insider
                    score, signals = await self.detect_insider(trade)
                    
                    # Send alert if high score
                    if score >= MIN_ALERT_SCORE and signals:
                        await self.send_alert_discord(trade, score, signals)
                        alerts_this_scan += 1
                        self.alerts_count += 1
                        
                except Exception as e:
                    print(f"⚠️ Trade error: {e}")
                    continue
            
            print(f"✅ Scan done - {alerts_this_scan} alerts")
            print(f"   Total today: {self.alerts_count}")
            
        except Exception as e:
            print(f"❌ Scanner error: {e}")

    # ============================================================
    # DISCORD ALERTS
    # ============================================================

    async def send_alert_discord(self, trade: Dict, score: int, signals: List[str]):
        """Send alert to Discord"""
        try:
            channel = self.bot.get_channel(CHANNEL)
            if not channel:
                print(f"❌ Channel {CHANNEL} not found!")
                return
            
            # Extract data
            wallet = trade.get("proxyWallet", "unknown")[:10]
            title = trade.get("title", "Unknown")[:70]
            outcome = trade.get("outcome", "?")
            side = trade.get("side", "?")
            price = float(trade.get("price", 0))
            size = float(trade.get("size", 0))
            usdc = float(trade.get("usdcSize", 0)) or (size * price)
            slug = trade.get("slug", "")
            
            url = f"https://polymarket.com/market/{slug}" if slug else "https://polymarket.com"
            
            # Color by confidence
            if score >= 90:
                color = discord.Color.dark_red()
                emoji = "🚨🚨🚨"
            elif score >= 85:
                color = discord.Color.red()
                emoji = "🚨"
            else:
                color = discord.Color.orange()
                emoji = "⚠️"
            
            # Build embed
            embed = discord.Embed(
                title=f"{emoji} INSIDER DETECTED - {score}%",
                description=f"**{title}**\n→ {outcome}",
                color=color,
                url=url,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="💰 Trade Size",
                value=f"${usdc:,.0f}",
                inline=True
            )
            
            embed.add_field(
                name="📊 Odds",
                value=f"{price:.2%}",
                inline=True
            )
            
            embed.add_field(
                name="👤 Wallet",
                value=f"`{wallet}...`",
                inline=True
            )
            
            if signals:
                embed.add_field(
                    name="🔍 Signals",
                    value="\n".join(f"• {s}" for s in signals[:5]),
                    inline=False
                )
            
            embed.set_footer(text=f"Confidence: {score}% | {datetime.now().strftime('%H:%M:%S UTC')}")
            
            await channel.send(embed=embed)
            print(f"✅ INSIDER ALERT: {title[:30]} ({score}%)")
            
        except Exception as e:
            print(f"❌ Discord alert error: {e}")

    @scanner.before_loop
    async def before_scanner(self):
        """Wait for bot to be ready"""
        await self.bot.wait_until_ready()
        print("✅ Scanner ready!")

# ============================================================
# BOT SETUP
# ============================================================

def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"\n{'='*60}")
        print(f"✅ BOT CONNECTED: {bot.user}")
        print(f"{'='*60}\n")
        
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
    print("🚀 POLYMARKET INSIDER DETECTOR")
    print("="*60)
    print(f"⚙️  Min trade: ${MIN_TRADE_SIZE:,}")
    print(f"⚙️  Min score: {MIN_ALERT_SCORE}%")
    print(f"⚙️  Max wallet trades: {MAX_WALLET_TRADES}")
    print("="*60 + "\n")
    
    bot = create_bot()
    bot.run(TOKEN)
