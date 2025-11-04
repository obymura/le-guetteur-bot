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
        # CORRECTION: Utiliser les bons endpoints
        self.gamma_api = "https://gamma-api.polymarket.com"
        self.data_api = "https://data-api.polymarket.com"  # Pour les trades!
        
        # Tracking data
        self.tracked_markets: Dict[str, dict] = {}
        self.wallet_history: Dict[str, List[dict]] = defaultdict(list)
        self.last_check = datetime.now()
        
        # Thresholds for insider detection (MODE TEST)
        self.MIN_BET_SIZE = 100  # $100 minimum pour tester
        self.PRICE_SPIKE_THRESHOLD = 0.15
        self.NEW_WALLET_DAYS = 365
        self.MAX_MARKETS_TO_ANALYZE = 50  # Top 50 pour commencer
        
    async def on_ready(self):
        print(f'✅ Bot connecté en tant que {self.user}')
        print(f'📊 Surveillance des insiders Polymarket activée')
        
        # Test d'alerte
        await self.send_test_alert()
        
        # Démarrer la surveillance
        self.check_insider_activity.start()
    
    async def send_test_alert(self):
        """Envoie une alerte de test au démarrage"""
        channel = self.get_channel(self.channel_id)
        if not channel:
            print(f'❌ Channel {self.channel_id} non trouvé')
            return
        
        embed = discord.Embed(
            title="🧪 TEST - Bot Démarré",
            description="**Le Guetteur est maintenant opérationnel!**",
            color=0x00FF00,
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="⚙️ Configuration",
            value=f"**Seuil:** ${self.MIN_BET_SIZE}+\n**Marchés:** Top {self.MAX_MARKETS_TO_ANALYZE}\n**Fréquence:** 30 secondes",
            inline=False
        )
        
        try:
            await channel.send("🚀 **Bot en ligne et prêt à détecter les insiders!**", embed=embed)
            print('✅ Alerte de test envoyée')
        except Exception as e:
            print(f'❌ Erreur test: {e}')
    
    @tasks.loop(seconds=30)
    async def check_insider_activity(self):
        """Boucle principale de détection"""
        try:
            print(f'\n{"="*70}')
            print(f'🔍 [{datetime.now().strftime("%H:%M:%S")}] DÉBUT DU SCAN')
            print(f'{"="*70}')
            
            async with aiohttp.ClientSession() as session:
                # Récupérer les marchés actifs
                markets = await self.get_active_markets(session)
                
                if not markets:
                    print('❌ Aucun marché récupéré')
                    return
                
                print(f'✅ {len(markets)} marchés récupérés')
                
                # Limiter aux top marchés
                markets_to_scan = markets[:self.MAX_MARKETS_TO_ANALYZE]
                print(f'📊 Analyse des {len(markets_to_scan)} premiers marchés...')
                
                alerts_found = 0
                trades_analyzed = 0
                
                for i, market in enumerate(markets_to_scan):
                    condition_id = market.get('condition_id')
                    if not condition_id:
                        continue
                    
                    # Progression
                    if (i + 1) % 10 == 0:
                        print(f'   ⏳ {i+1}/{len(markets_to_scan)} | {trades_analyzed} trades | {alerts_found} alertes')
                    
                    # Récupérer les trades récents
                    trades = await self.get_recent_trades(session, condition_id)
                    trades_analyzed += len(trades)
                    
                    if not trades:
                        continue
                    
                    # Analyser pour détecter les insiders
                    insider_signals = await self.analyze_trades(session, market, trades)
                    
                    if insider_signals:
                        for signal in insider_signals:
                            print(f'🚨 INSIDER: {market.get("question", "N/A")[:50]}... ({signal["score"]["probability"]}%)')
                            await self.send_insider_alert(signal)
                            alerts_found += 1
                            await asyncio.sleep(2)
                
                print(f'\n{"="*70}')
                print(f'✅ SCAN TERMINÉ')
                print(f'   📊 Marchés: {len(markets_to_scan)}')
                print(f'   💰 Trades: {trades_analyzed}')
                print(f'   🚨 Alertes: {alerts_found}')
                print(f'{"="*70}\n')
                
        except Exception as e:
            print(f'❌ Erreur: {e}')
            import traceback
            traceback.print_exc()
    
    async def get_active_markets(self, session: aiohttp.ClientSession) -> List[dict]:
        """Récupère les marchés actifs depuis Gamma API"""
        try:
            url = f"{self.gamma_api}/markets"
            params = {
                'closed': 'false',
                'limit': 100,
                '_sort': 'volume24hr',
                '_order': 'desc'
            }
            
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f'❌ Gamma API error: {resp.status}')
                    return []
        except Exception as e:
            print(f'❌ get_active_markets error: {e}')
            return []
    
    async def get_recent_trades(self, session: aiohttp.ClientSession, condition_id: str) -> List[dict]:
        """Récupère les trades récents depuis Data API"""
        try:
            # CORRECTION: Utiliser le bon endpoint
            url = f"{self.data_api}/trades"
            params = {
                'market': condition_id,
                'limit': 100
            }
            
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Data API retourne un array directement
                    return data if isinstance(data, list) else []
                else:
                    return []
        except Exception as e:
            # Pas de log pour chaque marché sans trades
            return []
    
    async def get_wallet_history(self, session: aiohttp.ClientSession, wallet: str) -> dict:
        """Récupère l'historique d'un wallet"""
        if wallet in self.wallet_history:
            return {
                'trades': self.wallet_history[wallet],
                'first_trade_date': min(t.get('timestamp', 0) for t in self.wallet_history[wallet]) if self.wallet_history[wallet] else None
            }
        
        try:
            url = f"{self.data_api}/trades"
            params = {
                'proxyWallet': wallet,
                'limit': 100
            }
            
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    trades = trades if isinstance(trades, list) else []
                    self.wallet_history[wallet] = trades
                    return {
                        'trades': trades,
                        'first_trade_date': min(t.get('timestamp', 0) for t in trades) if trades else None
                    }
        except Exception as e:
            pass
        
        return {'trades': [], 'first_trade_date': None}
    
    async def analyze_trades(self, session: aiohttp.ClientSession, market: dict, trades: List[dict]) -> List[dict]:
        """Analyse les trades pour détecter des patterns d'insider"""
        insider_signals = []
        
        # Grouper par wallet (dernière heure)
        recent_cutoff = int((datetime.now() - timedelta(hours=1)).timestamp())
        wallet_bets = defaultdict(lambda: {'size': 0, 'trades': []})
        
        for trade in trades:
            try:
                timestamp = trade.get('timestamp', 0)
                if timestamp < recent_cutoff:
                    continue
                
                wallet = trade.get('proxyWallet', '')
                if not wallet:
                    continue
                
                size = float(trade.get('size', 0))
                price = float(trade.get('price', 0))
                
                wallet_bets[wallet]['size'] += size * price
                wallet_bets[wallet]['trades'].append(trade)
            except (ValueError, TypeError):
                continue
        
        # Analyser chaque wallet
        for wallet, data in wallet_bets.items():
            bet_size_usd = data['size']
            
            if bet_size_usd < self.MIN_BET_SIZE:
                continue
            
            # Historique du wallet
            wallet_info = await self.get_wallet_history(session, wallet)
            
            # Score insider
            score = await self.calculate_insider_score(
                wallet_info,
                bet_size_usd,
                market,
                data['trades']
            )
            
            if score['probability'] > 10:  # Seuil 10% pour test
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
        """Calcule la probabilité d'insider"""
        score = 0
        max_score = 0
        reasons = []
        
        # Nouveau wallet (40 pts)
        max_score += 40
        trade_count = len(wallet_info['trades'])
        if trade_count <= 1:
            score += 40
            reasons.append("🆕 Wallet créé pour ce trade")
        elif trade_count <= 5:
            score += 25
            reasons.append(f"🆕 Wallet récent ({trade_count} trades)")
        elif trade_count <= 20:
            score += 15
            reasons.append(f"🆕 Peu d'activité ({trade_count} trades)")
        
        # Taille du pari (30 pts)
        max_score += 30
        if bet_size > 50000:
            score += 30
            reasons.append(f"💰 Mise énorme (${bet_size:,.0f})")
        elif bet_size > 10000:
            score += 20
            reasons.append(f"💰 Grosse mise (${bet_size:,.0f})")
        elif bet_size > 1000:
            score += 15
            reasons.append(f"💰 Mise significative (${bet_size:,.0f})")
        else:
            score += 10
            reasons.append(f"💵 Mise moyenne (${bet_size:,.0f})")
        
        # Focus marché (20 pts)
        max_score += 20
        unique_markets = len(set(t.get('conditionId', '') for t in wallet_info['trades']))
        if unique_markets == 1:
            score += 20
            reasons.append("🎯 100% focus sur ce marché")
        elif unique_markets <= 3:
            score += 10
            reasons.append(f"🎯 Focus limité ({unique_markets} marchés)")
        
        # Timing (10 pts)
        max_score += 10
        try:
            timestamp = trades[0].get('timestamp', 0)
            trade_hour = datetime.fromtimestamp(timestamp).hour
            if 0 <= trade_hour <= 6 or 22 <= trade_hour <= 23:
                score += 10
                reasons.append(f"⏰ Trade à {trade_hour}h (suspect)")
        except:
            pass
        
        probability = int((score / max_score) * 100)
        
        return {
            'probability': probability,
            'score': score,
            'max_score': max_score,
            'reasons': reasons
        }
    
    async def send_insider_alert(self, signal: dict):
        """Envoie l'alerte Discord"""
        channel = self.get_channel(self.channel_id)
        if not channel:
            return
        
        market = signal['market']
        score = signal['score']
        wallet = signal['wallet']
        
        # Créer l'embed
        embed = discord.Embed(
            title="🚨 ALERTE INSIDER DÉTECTÉ",
            description=f"**{market.get('question', 'N/A')}**",
            color=self.get_alert_color(score['probability']),
            timestamp=signal['timestamp']
        )
        
        # ACTION À SUIVRE
        try:
            side = signal['trades'][0].get('side', 'N/A')
            outcome = signal['trades'][0].get('outcome', 'N/A')
            
            if side == "BUY":
                action = f"✅ ACHETER {outcome}"
            elif side == "SELL":
                action = f"❌ VENDRE {outcome}"
            else:
                action = f"{side} {outcome}"
            
            embed.add_field(
                name="🎯 ACTION À SUIVRE",
                value=f"**{action}**\n*L'insider parie sur cette position*",
                inline=False
            )
        except:
            pass
        
        # Lien marché
        slug = market.get('slug', '')
        url = f"https://polymarket.com/event/{slug}" if slug else "N/A"
        embed.add_field(
            name="📊 Marché",
            value=f"[Voir sur Polymarket]({url})",
            inline=False
        )
        
        # Probabilité
        prob = score['probability']
        gauge = "█" * int(prob / 10) + "░" * (10 - int(prob / 10))
        
        if prob >= 80:
            level = "🔥 TRÈS ÉLEVÉE"
        elif prob >= 65:
            level = "⚠️ ÉLEVÉE"
        elif prob >= 50:
            level = "⚡ MOYENNE"
        else:
            level = "💡 FAIBLE"
        
        embed.add_field(
            name=f"🎲 Probabilité Insider: **{prob}%**",
            value=f"{gauge} {level}",
            inline=False
        )
        
        # Détails
        embed.add_field(
            name="💰 Taille du pari",
            value=f"**${signal['bet_size']:,.0f}**",
            inline=True
        )
        
        try:
            price = float(signal['trades'][0].get('price', 0))
            embed.add_field(
                name="💵 Prix",
                value=f"**${price:.3f}**/share",
                inline=True
            )
        except:
            pass
        
        embed.add_field(
            name="👤 Wallet",
            value=f"`{wallet[:8]}...{wallet[-6:]}`",
            inline=True
        )
        
        is_first = len(signal['wallet_info']['trades']) <= 1
        trade_count = len(signal['wallet_info']['trades'])
        
        embed.add_field(
            name="📝 Premier trade?",
            value="✅ OUI" if is_first else f"❌ Non ({trade_count})",
            inline=True
        )
        
        # Signaux
        reasons_text = "\n".join(f"• {r}" for r in score['reasons'])
        embed.add_field(
            name="🔍 Signaux détectés",
            value=reasons_text,
            inline=False
        )
        
        embed.set_footer(text="Polymarket Insider Detector • Temps réel")
        
        try:
            await channel.send(embed=embed)
            print(f'✅ Alerte envoyée')
        except Exception as e:
            print(f'❌ Erreur Discord: {e}')
    
    def get_alert_color(self, probability: int) -> int:
        """Couleur selon probabilité"""
        if probability >= 80:
            return 0xFF0000  # Rouge
        elif probability >= 65:
            return 0xFF6600  # Orange
        elif probability >= 50:
            return 0xFFCC00  # Jaune
        elif probability >= 20:
            return 0x00BFFF  # Bleu
        else:
            return 0x808080  # Gris


def main():
    """Lance le bot"""
    DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    
    if not DISCORD_TOKEN:
        print("❌ DISCORD_BOT_TOKEN manquant")
        return
    
    bot = PolymarketInsiderBot()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
