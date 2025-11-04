import discord
from discord.ext import tasks
import aiohttp
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
import os
from typing import Dict, List, Optional
import json

class PolymarketInsiderBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        
        # Configuration
        self.channel_id = int(os.getenv('DISCORD_CHANNEL_ID', '0'))
        self.polymarket_api = "https://gamma-api.polymarket.com"
        self.clob_api = "https://clob.polymarket.com"
        
        # Tracking data
        self.tracked_markets: Dict[str, dict] = {}
        self.wallet_history: Dict[str, List[dict]] = defaultdict(list)
        self.last_check = datetime.now()
        
        # Thresholds for insider detection
        self.MIN_BET_SIZE = 1000  # $1k minimum (baissé pour plus d'alertes)
        self.PRICE_SPIKE_THRESHOLD = 0.15  # 15% price change
        self.NEW_WALLET_DAYS = 90  # Consider wallet "new" if < 90 days (élargi)
        self.MAX_MARKETS_TO_ANALYZE = None  # None = tous, ou nombre spécifique (ex: 200)
        
    async def on_ready(self):
        print(f'✅ Bot connecté en tant que {self.user}')
        print(f'📊 Surveillance des insiders Polymarket activée')
        
        # ENVOYER UN MESSAGE DE TEST AU DÉMARRAGE
        await self.send_test_alert()
        
        self.check_insider_activity.start()
    
    async def send_test_alert(self):
        """Envoie une alerte de test au démarrage pour vérifier que tout fonctionne"""
        channel = self.get_channel(self.channel_id)
        if not channel:
            print(f'❌ Channel {self.channel_id} non trouvé pour le test')
            return
        
        # Créer l'embed de test
        embed = discord.Embed(
            title="🧪 TEST - ALERTE INSIDER DÉTECTÉ",
            description="**Will Bitcoin reach $150,000 by end of 2025?**\n\n*Ceci est une alerte de test pour vérifier le bon fonctionnement du bot*",
            color=0xFF0000,  # Rouge
            timestamp=datetime.now()
        )
        
        # Lien marché
        embed.add_field(
            name="📊 Marché",
            value="[Voir sur Polymarket](https://polymarket.com/event/will-bitcoin-reach-150k)",
            inline=False
        )
        
        # Jauge de probabilité
        probability = 87
        gauge = "█" * 8 + "░" * 2
        embed.add_field(
            name=f"🎲 Probabilité Insider: **{probability}%**",
            value=f"{gauge} 🔥 **TRÈS ÉLEVÉE**",
            inline=False
        )
        
        # Recommandation et taille
        embed.add_field(
            name="💡 Recommandation",
            value="**Suivre l'insider:** YES ✅",
            inline=True
        )
        
        embed.add_field(
            name="💰 Taille du pari",
            value="**$47,500**",
            inline=True
        )
        
        # Info wallet
        embed.add_field(
            name="👤 Wallet",
            value="`0x1a2b3c...def456`",
            inline=True
        )
        
        embed.add_field(
            name="📝 Premier trade?",
            value="✅ **OUI**",
            inline=True
        )
        
        # Timestamp
        embed.add_field(
            name="⏰ Heure du trade",
            value="2025-11-04T02:15:33Z",
            inline=True
        )
        
        # Raisons
        reasons = "\n".join([
            "• 🆕 Wallet créé spécifiquement pour ce trade",
            "• 💰 Mise massive ($47,500)",
            "• 🎯 100% focus sur ce marché uniquement",
            "• ⏰ Trade à 2h (heures suspectes)"
        ])
        
        embed.add_field(
            name="🔍 Signaux détectés",
            value=reasons,
            inline=False
        )
        
        # Footer
        embed.set_footer(text="🧪 ALERTE DE TEST • Polymarket Insider Detector")
        
        # Envoyer
        try:
            await channel.send("🚀 **Le Guetteur est maintenant en ligne!**\n✅ Surveillance des insiders activée\n⏰ Vérification toutes les 30 secondes\n💰 Seuil: $1,000+ (MODE SENSIBLE)\n🎯 Probabilité min: 20%\n\n*Voici un exemple d'alerte:*", embed=embed)
            print('✅ Alerte de test envoyée avec succès!')
        except Exception as e:
            print(f'❌ Erreur lors de l\'envoi du test: {e}')
    
    @tasks.loop(seconds=30)  # Check every 30 seconds
    async def check_insider_activity(self):
        """Main loop to detect insider activity"""
        try:
            print(f'🔍 [{datetime.now().strftime("%H:%M:%S")}] Checking markets...')
            async with aiohttp.ClientSession() as session:
                # Get active markets
                markets = await self.get_active_markets(session)
                print(f'📊 Analysing {len(markets)} marchés actifs...')
                
                # Limiter le nombre de marchés si configuré
                markets_to_scan = markets
                if self.MAX_MARKETS_TO_ANALYZE:
                    markets_to_scan = markets[:self.MAX_MARKETS_TO_ANALYZE]
                    print(f'⚙️  Limite: analyse des {self.MAX_MARKETS_TO_ANALYZE} premiers marchés')
                
                alerts_found = 0
                for i, market in enumerate(markets_to_scan):  # Analyser TOUS les marchés
                    market_id = market.get('condition_id')
                    if not market_id:
                        continue
                    
                    # Afficher progression tous les 100 marchés
                    if (i + 1) % 100 == 0:
                        print(f'   ⏳ Progression: {i + 1}/{len(markets)} marchés analysés...')
                    
                    # Get recent trades for this market
                    trades = await self.get_recent_trades(session, market_id)
                    
                    # Analyze for insider patterns
                    insider_signals = await self.analyze_trades(session, market, trades)
                    
                    if insider_signals:
                        for signal in insider_signals:
                            await self.send_insider_alert(signal)
                            alerts_found += 1
                            await asyncio.sleep(2)  # Rate limiting
                
                print(f'✅ Check terminé: {alerts_found} alerte(s) trouvée(s)')
                
        except Exception as e:
            print(f'❌ Erreur dans check_insider_activity: {e}')
    
    async def get_active_markets(self, session: aiohttp.ClientSession) -> List[dict]:
        """Fetch ALL active markets from Polymarket using pagination"""
        all_markets = []
        offset = 0
        limit = 100
        
        try:
            while True:
                url = f"{self.polymarket_api}/markets"
                params = {
                    'closed': 'false',
                    'limit': limit,
                    'offset': offset,
                    '_sort': 'volume24hr',
                    '_order': 'desc'
                }
                
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        markets = await resp.json()
                        if not markets:  # Plus de marchés à récupérer
                            break
                        all_markets.extend(markets)
                        offset += limit
                        
                        # Limite de sécurité: max 1000 marchés (évite boucle infinie)
                        if len(all_markets) >= 1000:
                            break
                    else:
                        break
                
                # Petit délai pour ne pas surcharger l'API
                await asyncio.sleep(0.5)
            
            print(f'📊 Total marchés récupérés: {len(all_markets)}')
            return all_markets
            
        except Exception as e:
            print(f'Erreur get_active_markets: {e}')
            return all_markets if all_markets else []
    
    async def get_recent_trades(self, session: aiohttp.ClientSession, market_id: str) -> List[dict]:
        """Get recent trades for a specific market"""
        try:
            url = f"{self.clob_api}/trades"
            params = {
                'market': market_id,
                'limit': 100
            }
            
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            print(f'Erreur get_recent_trades: {e}')
            return []
    
    async def get_wallet_history(self, session: aiohttp.ClientSession, wallet: str) -> dict:
        """Get trading history for a wallet"""
        if wallet in self.wallet_history:
            return {
                'trades': self.wallet_history[wallet],
                'first_trade_date': min(t['timestamp'] for t in self.wallet_history[wallet]) if self.wallet_history[wallet] else None
            }
        
        try:
            url = f"{self.clob_api}/trades"
            params = {
                'maker': wallet,
                'limit': 100
            }
            
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    self.wallet_history[wallet] = trades
                    return {
                        'trades': trades,
                        'first_trade_date': min(t['timestamp'] for t in trades) if trades else None
                    }
        except Exception as e:
            print(f'Erreur get_wallet_history: {e}')
        
        return {'trades': [], 'first_trade_date': None}
    
    async def analyze_trades(self, session: aiohttp.ClientSession, market: dict, trades: List[dict]) -> List[dict]:
        """Analyze trades for insider patterns"""
        insider_signals = []
        
        # Get market price history
        current_price = float(market.get('outcomes', [{}])[0].get('price', 0))
        
        # Group trades by wallet in last hour
        recent_cutoff = datetime.now() - timedelta(hours=1)
        wallet_bets = defaultdict(lambda: {'size': 0, 'trades': []})
        
        for trade in trades:
            trade_time = datetime.fromisoformat(trade.get('timestamp', '').replace('Z', '+00:00'))
            if trade_time < recent_cutoff:
                continue
            
            wallet = trade.get('maker', '')
            size = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            
            wallet_bets[wallet]['size'] += size * price
            wallet_bets[wallet]['trades'].append(trade)
        
        # Analyze each wallet
        for wallet, data in wallet_bets.items():
            bet_size_usd = data['size']
            
            # Check if bet size is significant
            if bet_size_usd < self.MIN_BET_SIZE:
                continue
            
            # Get wallet history
            wallet_info = await self.get_wallet_history(session, wallet)
            
            # Calculate insider probability score
            score = await self.calculate_insider_score(
                wallet_info,
                bet_size_usd,
                market,
                data['trades']
            )
            
            if score['probability'] > 20:  # More than 20% chance of insider (baissé pour plus d'alertes)
                insider_signals.append({
                    'market': market,
                    'wallet': wallet,
                    'bet_size': bet_size_usd,
                    'trades': data['trades'],
                    'wallet_info': wallet_info,
                    'score': score,
                    'timestamp': datetime.now()
                })
        
        return insider_signals
    
    async def calculate_insider_score(self, wallet_info: dict, bet_size: float, market: dict, trades: List[dict]) -> dict:
        """Calculate probability that this is an insider trade"""
        score = 0
        max_score = 0
        reasons = []
        
        # Factor 1: New wallet (40 points)
        max_score += 40
        if len(wallet_info['trades']) <= 1:
            score += 40
            reasons.append("🆕 Wallet créé spécifiquement pour ce trade")
        elif len(wallet_info['trades']) <= 5:
            score += 25
            reasons.append("🆕 Wallet très récent (<5 trades)")
        elif wallet_info['first_trade_date']:
            days_old = (datetime.now() - datetime.fromisoformat(wallet_info['first_trade_date'].replace('Z', '+00:00'))).days
            if days_old < self.NEW_WALLET_DAYS:
                score += 20
                reasons.append(f"🆕 Wallet récent ({days_old} jours)")
        
        # Factor 2: Large bet size (30 points)
        max_score += 30
        if bet_size > 50000:
            score += 30
            reasons.append(f"💰 Mise massive (${bet_size:,.0f})")
        elif bet_size > 20000:
            score += 20
            reasons.append(f"💰 Grosse mise (${bet_size:,.0f})")
        elif bet_size > 10000:
            score += 15
            reasons.append(f"💰 Mise significative (${bet_size:,.0f})")
        else:
            score += 10
            reasons.append(f"💵 Mise moyenne (${bet_size:,.0f})")
        
        # Factor 3: Single market focus (20 points)
        max_score += 20
        unique_markets = len(set(t.get('market', '') for t in wallet_info['trades']))
        if unique_markets == 1:
            score += 20
            reasons.append("🎯 100% focus sur ce marché uniquement")
        elif unique_markets <= 3:
            score += 10
            reasons.append(f"🎯 Focus limité ({unique_markets} marchés)")
        
        # Factor 4: Timing (10 points) - trading outside normal hours
        max_score += 10
        trade_hour = datetime.fromisoformat(trades[0].get('timestamp', '').replace('Z', '+00:00')).hour
        if 0 <= trade_hour <= 6 or 22 <= trade_hour <= 23:
            score += 10
            reasons.append(f"⏰ Trade à {trade_hour}h (heures suspectes)")
        
        probability = int((score / max_score) * 100)
        
        return {
            'probability': probability,
            'score': score,
            'max_score': max_score,
            'reasons': reasons
        }
    
    async def send_insider_alert(self, signal: dict):
        """Send formatted alert to Discord channel"""
        channel = self.get_channel(self.channel_id)
        if not channel:
            print(f'❌ Channel {self.channel_id} non trouvé')
            return
        
        market = signal['market']
        score = signal['score']
        wallet = signal['wallet']
        
        # Create embed
        embed = discord.Embed(
            title="🚨 ALERTE INSIDER DÉTECTÉ",
            description=f"**{market.get('question', 'N/A')}**",
            color=self.get_alert_color(score['probability']),
            timestamp=signal['timestamp']
        )
        
        # Market info
        market_slug = market.get('slug', '')
        market_url = f"https://polymarket.com/event/{market_slug}" if market_slug else "N/A"
        embed.add_field(
            name="📊 Marché",
            value=f"[Voir sur Polymarket]({market_url})",
            inline=False
        )
        
        # Probability gauge
        probability = score['probability']
        gauge = self.create_probability_gauge(probability)
        embed.add_field(
            name=f"🎲 Probabilité Insider: **{probability}%**",
            value=gauge,
            inline=False
        )
        
        # Trading recommendation
        outcome = signal['trades'][0].get('outcome', 'N/A')
        side = signal['trades'][0].get('side', 'N/A')
        recommendation = "YES ✅" if side == "BUY" else "NO ❌"
        
        embed.add_field(
            name="💡 Recommandation",
            value=f"**Suivre l'insider:** {recommendation}",
            inline=True
        )
        
        # Bet size
        embed.add_field(
            name="💰 Taille du pari",
            value=f"**${signal['bet_size']:,.0f}**",
            inline=True
        )
        
        # Wallet info
        is_first_trade = len(signal['wallet_info']['trades']) <= 1
        trade_count = len(signal['wallet_info']['trades'])
        
        embed.add_field(
            name="👤 Wallet",
            value=f"`{wallet[:8]}...{wallet[-6:]}`",
            inline=True
        )
        
        embed.add_field(
            name="📝 Premier trade?",
            value="✅ **OUI**" if is_first_trade else f"❌ Non ({trade_count} trades)",
            inline=True
        )
        
        # Timestamp of trade
        trade_time = signal['trades'][0].get('timestamp', 'N/A')
        embed.add_field(
            name="⏰ Heure du trade",
            value=f"{trade_time}",
            inline=True
        )
        
        # Add reasons
        reasons_text = "\n".join(f"• {reason}" for reason in score['reasons'])
        embed.add_field(
            name="🔍 Signaux détectés",
            value=reasons_text,
            inline=False
        )
        
        # Footer with links
        embed.set_footer(text="Polymarket Insider Detector • Données en temps réel")
        
        # Add blockchain explorer link if available
        view = discord.ui.View()
        if market_url != "N/A":
            button = discord.ui.Button(
                label="📈 Voir le marché",
                url=market_url,
                style=discord.ButtonStyle.link
            )
            view.add_item(button)
        
        try:
            await channel.send(embed=embed, view=view)
            print(f'✅ Alerte envoyée: {market.get("question", "N/A")[:50]}...')
        except Exception as e:
            print(f'❌ Erreur envoi message: {e}')
    
    def get_alert_color(self, probability: int) -> int:
        """Get color based on insider probability"""
        if probability >= 80:
            return 0xFF0000  # Red - Very high
        elif probability >= 65:
            return 0xFF6600  # Orange - High
        elif probability >= 50:
            return 0xFFCC00  # Yellow - Medium
        elif probability >= 20:
            return 0x00BFFF  # Blue - Low but notable
        else:
            return 0x808080  # Gray - Very low
    
    def create_probability_gauge(self, probability: int) -> str:
        """Create visual probability gauge"""
        filled = int(probability / 10)
        empty = 10 - filled
        gauge = "█" * filled + "░" * empty
        
        if probability >= 80:
            return f"{gauge} 🔥 **TRÈS ÉLEVÉE**"
        elif probability >= 65:
            return f"{gauge} ⚠️ **ÉLEVÉE**"
        elif probability >= 50:
            return f"{gauge} ⚡ **MOYENNE**"
        elif probability >= 20:
            return f"{gauge} 💡 **FAIBLE**"
        else:
            return f"{gauge} ℹ️ **TRÈS FAIBLE**"


def main():
    """Launch the bot"""
    # Load environment variables
    DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not DISCORD_TOKEN:
        print("❌ DISCORD_BOT_TOKEN non défini dans les variables d'environnement")
        return
    
    # Create and run bot
    bot = PolymarketInsiderBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
