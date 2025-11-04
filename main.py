#!/usr/bin/env python3
"""
🚀 POLYMARKET INSIDER BOT - TWO-STAGE DETECTION
Stage 1: Quick pre-filter (fast)
Stage 2: Deep analysis if suspicious (comprehensive)
"""

import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import asyncio

# CONFIG
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID") or os.getenv("CHANNEL_ID", "0"))

if not DISCORD_TOKEN or CHANNEL_ID == 0:
    print("❌ Variables manquantes!")
    sys.exit(1)

print(f"✅ Config OK - Channel: {CHANNEL_ID}")

# APIs
DATA_API = "https://data-api.polymarket.com"

# ============================================================
# STAGE 1: PRE-FILTER THRESHOLDS (quick check)
# ============================================================

STAGE1_MIN_SIZE = 5000          # $5K minimum pour même check
STAGE1_PRICE_THRESHOLD = 0.20   # < 20% ou > 80% = suspect

# ============================================================
# STAGE 2: DEEP ANALYSIS CRITERIA (if suspicious)
# Based on insider tweet @polysights
# ============================================================

# Ideal insider profile:
# <1d wallet age + <3 total markets + >$10k size + >50% radar score
# + wc/tx <20% + timestamp <5hrs ago

STAGE2_WALLET_AGE_HOURS = 24        # < 24h = suspect
STAGE2_MIN_MARKETS = 3              # < 3 markets = concentrated
STAGE2_MIN_SIZE = 10000             # $10K+ = meaningful
STAGE2_MIN_RADAR_SCORE = 50         # >50% radar = trustworthy
STAGE2_WALLET_CREATION_RATIO = 20   # wc/tx < 20% = very suspect
STAGE2_TIMESTAMP_HOURS = 5          # < 5h ago = recent
STAGE2_MIN_FINAL_SCORE = 80         # 80%+ = HIGH CONFIDENCE

class TwoStageInsiderBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        self.processed = set()
        self.alerts_sent = 0
        self.stage1_checks = 0
        self.stage2_confirmations = 0
        
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        if not self.scan_loop.is_running():
            self.scan_loop.start()
        print("✅ Two-stage scanner démarré")
        
    async def cog_unload(self):
        self.scan_loop.cancel()
        if self.session:
            await self.session.close()

    # ============================================================
    # API CALLS
    # ============================================================

    async def get_trades(self) -> List[Dict]:
        """Récupère les trades"""
        try:
            async with self.session.get(
                f"{DATA_API}/trades",
                params={"limit": 500},
                timeout=15
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data if isinstance(data, list) else []
        except Exception as e:
            print(f"❌ API trades: {e}")
        return []

    async def get_wallet_history(self, wallet: str) -> Dict:
        """Récupère l'historique complet du wallet"""
        try:
            async with self.session.get(
                f"{DATA_API}/activity",
                params={"proxyWallet": wallet, "limit": 500},
                timeout=15
            ) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    if isinstance(trades, list) and len(trades) > 0:
                        return {
                            "trades": trades,
                            "total_trades": len(trades),
                            "markets": len(set(t.get('conditionId') for t in trades if t.get('conditionId'))),
                            "total_volume": sum(float(t.get('size', 0)) * float(t.get('price', 0)) for t in trades),
                            "first_trade": min((t.get('timestamp') for t in trades if t.get('timestamp')), default=None),
                            "pnl": sum(float(t.get('pnl', 0)) for t in trades)
                        }
        except Exception as e:
            print(f"⚠️ Wallet history error: {e}")
        
        return {
            "trades": [],
            "total_trades": 0,
            "markets": 0,
            "total_volume": 0,
            "first_trade": None,
            "pnl": 0
        }

    # ============================================================
    # STAGE 1: PRE-FILTER (fast, simple check)
    # ============================================================

    def stage1_pre_filter(self, trade: Dict) -> Tuple[bool, str]:
        """
        Stage 1: Quick pre-filter
        Return: (is_suspicious, reason)
        """
        try:
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            value = size * price
            
            # Check 1: Minimum size
            if value < STAGE1_MIN_SIZE:
                return False, "too_small"
            
            # Check 2: Extreme price (< 20% or > 80%)
            if price < STAGE1_PRICE_THRESHOLD or price > (1 - STAGE1_PRICE_THRESHOLD):
                return True, "extreme_price"
            
            # Check 3: Just high enough to investigate
            if value >= STAGE1_MIN_SIZE:
                return True, "substantial_trade"
            
        except Exception as e:
            print(f"❌ Stage1 error: {e}")
        
        return False, "error"

    # ============================================================
    # STAGE 2: DEEP ANALYSIS (comprehensive, if suspicious)
    # ============================================================

    async def stage2_deep_analysis(self, trade: Dict, wallet_history: Dict) -> Tuple[int, List[str]]:
        """
        Stage 2: Deep analysis based on insider criteria
        Return: (final_score 0-100, signals)
        """
        score = 0
        signals = []

        try:
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            value = size * price
            
            # ===== CRITERION 1: WALLET AGE (max 25pts) =====
            # Ideal: < 24h = brand new wallet
            first_trade_str = wallet_history.get("first_trade")
            if first_trade_str:
                try:
                    first_trade_dt = datetime.fromisoformat(first_trade_str.replace('Z', '+00:00'))
                    wallet_age = (datetime.now(first_trade_dt.tzinfo) - first_trade_dt).total_seconds() / 3600
                    
                    if wallet_age < 24:
                        score += 25
                        signals.append(f"🆕 Wallet <24h old ({wallet_age:.1f}h)")
                    elif wallet_age < 72:
                        score += 15
                        signals.append(f"🆕 Wallet <3d old ({wallet_age:.0f}h)")
                    elif wallet_age > 365:
                        score -= 15
                        return 0, []  # Old wallet, not insider
                except:
                    pass
            
            # ===== CRITERION 2: TOTAL MARKETS (max 20pts) =====
            # Ideal: < 3 markets = concentrated
            total_markets = wallet_history.get("markets", 0)
            
            if total_markets <= 3:
                score += 20
                signals.append(f"🎯 Concentrated: {total_markets} market(s)")
            elif total_markets <= 5:
                score += 10
                signals.append(f"📊 {total_markets} markets")
            elif total_markets > 50:
                score -= 20
                return 0, []  # Too diversified, not insider
            
            # ===== CRITERION 3: TRADE SIZE (max 20pts) =====
            # Ideal: > $10K
            if value >= 50000:
                score += 20
                signals.append(f"💰 MEGA: ${value:,.0f}")
            elif value >= 10000:
                score += 15
                signals.append(f"💰 Large: ${value:,.0f}")
            elif value >= 5000:
                score += 8
                signals.append(f"💵 ${value:,.0f}")
            
            # ===== CRITERION 4: WALLET CREATION TO TRADE RATIO (max 15pts) =====
            # wc/tx = minutes between wallet creation and trade
            # Ideal: < 20% of wallet age
            total_trades = wallet_history.get("total_trades", 1)
            first_trade_ts = wallet_history.get("first_trade")
            current_trade_ts = trade.get("timestamp")
            
            if first_trade_ts and current_trade_ts:
                try:
                    first_dt = datetime.fromisoformat(first_trade_ts.replace('Z', '+00:00'))
                    current_dt = datetime.fromisoformat(current_trade_ts.replace('Z', '+00:00'))
                    wallet_age_minutes = (current_dt - first_dt).total_seconds() / 60
                    
                    if wallet_age_minutes > 0:
                        wc_tx_ratio = (wallet_age_minutes / wallet_age_minutes) * 100 if total_trades > 0 else 0
                        
                        # If first trade ever, very suspicious
                        if total_trades == 1:
                            score += 15
                            signals.append("🎯 FIRST TRADE EVER (100% concentration)")
                        elif wc_tx_ratio < 20:
                            score += 12
                            signals.append(f"⚡ Fast trade: {wc_tx_ratio:.0f}% ratio")
                except:
                    pass
            
            # ===== CRITERION 5: TIMESTAMP (max 10pts) =====
            # Ideal: < 5 hours ago = very recent
            if current_trade_ts:
                try:
                    current_dt = datetime.fromisoformat(current_trade_ts.replace('Z', '+00:00'))
                    now = datetime.now(current_dt.tzinfo)
                    hours_ago = (now - current_dt).total_seconds() / 3600
                    
                    if hours_ago < 5:
                        score += 10
                        signals.append(f"⏰ Very recent: {hours_ago:.1f}h ago")
                    elif hours_ago < 24:
                        score += 5
                        signals.append(f"⏰ Recent: {hours_ago:.0f}h ago")
                except:
                    pass
            
            # ===== CRITERION 6: PRICE EXTREMES (max 10pts) =====
            if price < 0.05 or price > 0.95:
                score += 10
                signals.append(f"🚨 Extreme odds: {price:.1%}")
            elif price < 0.10 or price > 0.90:
                score += 6
                signals.append(f"⚠️ High odds: {price:.1%}")
            
            # ===== RADAR SCORE (simulated, max 10pts) =====
            # In real scenario, you'd fetch from Hashdive/PolymarketAnalytics API
            # For now, we simulate based on wallet behavior
            simulated_radar = min(100, total_trades * 5 + 30)  # Rough estimate
            
            if simulated_radar >= 50:
                score += 8
                signals.append(f"📈 Radar score: {simulated_radar}%")
            
        except Exception as e:
            print(f"❌ Stage2 error: {e}")
            return 0, []
        
        # Normalize to 0-100
        final_score = min(100, max(0, score))
        return final_score, signals

    # ============================================================
    # MAIN SCAN LOOP
    # ============================================================

    @tasks.loop(seconds=60)
    async def scan_loop(self):
        """Main scanning loop: Stage 1 → Stage 2 → Alert"""
        try:
            print(f"\n🔍 [{datetime.now().strftime('%H:%M:%S')}] TWO-STAGE SCAN...")
            
            trades = await self.get_trades()
            if not trades:
                print("⚠️ No trades")
                return
            
            print(f"📊 {len(trades)} trades (Stage 1 pre-filter)")
            
            stage1_suspicious = 0
            stage2_confirmed = 0
            
            for trade in trades:
                try:
                    # Create unique ID
                    trade_id = f"{trade.get('proxyWallet')}-{trade.get('conditionId')}-{trade.get('timestamp')}"
                    
                    if trade_id in self.processed:
                        continue
                    
                    self.processed.add(trade_id)
                    if len(self.processed) > 2000:
                        self.processed = set(list(self.processed)[-1000:])
                    
                    # ===== STAGE 1: Quick pre-filter =====
                    is_suspicious, reason = self.stage1_pre_filter(trade)
                    
                    if is_suspicious:
                        stage1_suspicious += 1
                        self.stage1_checks += 1
                        
                        # ===== STAGE 2: Deep analysis if suspicious =====
                        wallet = trade.get("proxyWallet", "unknown")
                        wallet_history = await self.get_wallet_history(wallet)
                        
                        score, signals = await self.stage2_deep_analysis(trade, wallet_history)
                        
                        # ===== ALERT if HIGH CONFIDENCE =====
                        if score >= STAGE2_MIN_FINAL_SCORE:
                            stage2_confirmed += 1
                            self.stage2_confirmations += 1
                            await self.send_alert(trade, wallet_history, score, signals)
                            self.alerts_sent += 1
                    
                except Exception as e:
                    print(f"⚠️ Trade error: {e}")
                    continue
            
            print(f"✅ Stage 1: {stage1_suspicious} suspicious → Stage 2: {stage2_confirmed} confirmed")
            print(f"   Total alerts today: {self.alerts_sent}")
            print(f"   Efficiency: {stage2_confirmed}/{stage1_suspicious} Stage 2 conversions")
            
        except Exception as e:
            print(f"❌ Scan error: {e}")

    # ============================================================
    # ALERT
    # ============================================================

    async def send_alert(self, trade: Dict, wallet_history: Dict, score: int, signals: List[str]):
        """Envoie une alerte Discord"""
        try:
            channel = self.bot.get_channel(CHANNEL_ID)
            if not channel:
                return
            
            wallet = trade.get("proxyWallet", "unknown")[:10]
            market = trade.get("title", "Unknown")[:60]
            outcome = trade.get("outcome", "?")
            side = trade.get("side", "UNKNOWN")
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            value = size * price
            slug = trade.get("slug", "")
            
            url = f"https://polymarket.com/market/{slug}" if slug else "https://polymarket.com"
            
            # Color based on confidence
            if score >= 90:
                color = discord.Color.dark_red()
                emoji = "🚨🚨🚨"
                confidence = "ULTRA HIGH"
            elif score >= 85:
                color = discord.Color.red()
                emoji = "🚨🚨"
                confidence = "VERY HIGH"
            else:
                color = discord.Color.dark_orange()
                emoji = "🚨"
                confidence = "HIGH"
            
            embed = discord.Embed(
                title=f"{emoji} INSIDER CONFIRMED - {score}%",
                description=f"**{market}**\n→ {outcome}",
                color=color,
                url=url,
                timestamp=datetime.now()
            )
            
            # Trade info
            embed.add_field(
                name="💰 Trade Value",
                value=f"**${value:,.0f}**\n{side}",
                inline=True
            )
            
            embed.add_field(
                name="📊 Odds",
                value=f"**{price:.2%}**\n{size:.0f} shares",
                inline=True
            )
            
            # Wallet stats
            total_trades = wallet_history.get("total_trades", 0)
            total_markets = wallet_history.get("markets", 0)
            total_volume = wallet_history.get("total_volume", 0)
            
            embed.add_field(
                name="👤 Wallet Profile",
                value=f"Trades: **{total_trades}**\nMarkets: **{total_markets}**\nVolume: **${total_volume:,.0f}**",
                inline=False
            )
            
            # Signals
            if signals:
                embed.add_field(
                    name="🔍 Insider Signals (Stage 2)",
                    value="\n".join(f"• {s}" for s in signals[:6]),
                    inline=False
                )
            
            # Confidence
            embed.add_field(
                name="⚡ Confidence Level",
                value=f"**{confidence}** ({score}%)",
                inline=True
            )
            
            embed.add_field(
                name="🔗 Wallet",
                value=f"`{wallet}...`",
                inline=True
            )
            
            await channel.send(embed=embed)
            print(f"✅ CONFIRMED INSIDER: {market[:30]} (Score: {score}%)")
            
        except Exception as e:
            print(f"❌ Alert error: {e}")

    @scan_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()
        print("✅ Two-stage insider detector ready!")

# ============================================================
# BOT
# ============================================================

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"\n{'='*60}")
    print(f"✅ BOT CONNECTÉ: {bot.user}")
    print(f"{'='*60}\n")
    
    if not bot.cogs.get('TwoStageInsiderBot'):
        cog = TwoStageInsiderBot(bot)
        await cog.cog_load()
        await bot.add_cog(cog)

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🚀 POLYMARKET INSIDER BOT - TWO-STAGE DETECTION")
    print("="*60)
    print("Stage 1: Pre-filter (quick checks)")
    print("Stage 2: Deep analysis (comprehensive)")
    print(f"Final Score Threshold: {STAGE2_MIN_FINAL_SCORE}%")
    print("="*60 + "\n")
    
    bot.run(DISCORD_TOKEN)
