import discord
from discord.ext import tasks
import aiohttp
import asyncio
from datetime import datetime, timedelta
import os
import json
import logging

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PolymarketInsiderBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        
        # Configuration
        self.channel_id = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
        self.data_api = "https://data-api.polymarket.com"
        self.gamma_api = "https://gamma-api.polymarket.com"
        
        # Seuils de détection d'insiders
        self.MIN_BET_SIZE = 100  # $100 minimum pour tester
        self.MIN_PROBABILITY = 10  # 10% minimum
        self.NEW_WALLET_DAYS = 7  # Nouveau si créé dans les 7 jours
        self.MAX_MARKETS = 50  # Top 50 marchés pour commencer
        
        # Tracking
        self.checked_wallets = set()  # Éviter doublons
        self.last_check = None

    async def on_ready(self):
        print(f'✅ Bot connecté en tant que {self.user}')
        print(f'📊 Surveillance des insiders Polymarket activée')
        
        # Envoyer alerte de démarrage
        await self.send_startup_alert()
        
        # Démarrer la boucle de surveillance
        if not self.check_insider_activity.is_running():
            self.check_insider_activity.start()

    async def send_startup_alert(self):
        """Envoie un message de confirmation au démarrage"""
        channel = self.get_channel(self.channel_id)
        if not channel:
            print(f"❌ Channel {self.channel_id} non trouvé!")
            return
        
        embed = discord.Embed(
            title="🚀 Bot Démarré avec Succès",
            description="Le Guetteur est maintenant opérationnel",
            color=0x00FF00,
            timestamp=datetime.now()
        )
        
        embed.add_field(name="⏰ Fréquence", value="Check toutes les 60 secondes", inline=False)
        embed.add_field(name="💰 Seuil Minimum", value=f"${self.MIN_BET_SIZE}", inline=True)
        embed.add_field(name="📊 Probabilité Min", value=f"{self.MIN_PROBABILITY}%", inline=True)
        embed.add_field(name="🎯 Marchés", value=f"Top {self.MAX_MARKETS} analysés", inline=True)
        
        try:
            await channel.send("🔍 **Recherche des insiders en cours...**", embed=embed)
            print("✅ Alerte de démarrage envoyée")
        except Exception as e:
            print(f"❌ Erreur envoi alerte: {e}")

    @tasks.loop(seconds=60)
    async def check_insider_activity(self):
        """Vérifie les activités d'insiders toutes les 60 secondes"""
        try:
            print(f"\n{'='*60}")
            print(f"🔍 [{datetime.now().strftime('%H:%M:%S')}] DÉBUT DU SCAN POLYMARKET")
            print(f"{'='*60}")
            
            async with aiohttp.ClientSession() as session:
                # Récupérer les marchés actifs
                print("📊 Récupération des marchés...")
                markets = await self.get_active_markets(session)
                
                if not markets:
                    print("❌ Aucun marché récupéré!")
                    print(f"{'='*60}\n")
                    return
                
                print(f"✅ {len(markets)} marchés trouvés")
                
                # Limiter à MAX_MARKETS
                markets_to_check = markets[:self.MAX_MARKETS]
                print(f"📊 Analyse des {len(markets_to_check)} premiers marchés...\n")
                
                total_trades = 0
                alerts_sent = 0
                
                # Analyser chaque marché
                for idx, market in enumerate(markets_to_check, 1):
                    try:
                        condition_id = market.get('conditionId')
                        if not condition_id:
                            continue
                        
                        # Récupérer les trades pour ce marché
                        trades = await self.get_market_trades(session, condition_id)
                        
                        if not trades:
                            continue
                        
                        total_trades += len(trades)
                        
                        # Analyser les trades
                        for trade in trades:
                            is_insider, score = await self.analyze_trade(trade, session)
                            
                            if is_insider and score >= self.MIN_PROBABILITY:
                                alerts_sent += 1
                                await self.send_insider_alert(
                                    trade, market, score, session
                                )
                        
                        # Afficher progression tous les 10 marchés
                        if idx % 10 == 0:
                            print(f"   ⏳ Progression: {idx}/{len(markets_to_check)} | {total_trades} trades | {alerts_sent} alertes")
                    
                    except Exception as e:
                        logger.error(f"Erreur marché {market.get('title', 'Unknown')}: {e}")
                        continue
                
                print(f"\n{'='*60}")
                print(f"✅ SCAN TERMINÉ")
                print(f"   📊 Marchés: {len(markets_to_check)}")
                print(f"   💰 Trades: {total_trades}")
                print(f"   🚨 Alertes: {alerts_sent}")
                print(f"{'='*60}\n")
        
        except Exception as e:
            logger.error(f"Erreur check_insider_activity: {e}")
            print(f"❌ Erreur: {e}")
            print(f"{'='*60}\n")

    async def get_active_markets(self, session):
        """Récupère les marchés actifs de Polymarket"""
        try:
            url = f"{self.gamma_api}/markets"
            params = {
                'limit': 100,
                'closed': 'false'
            }
            
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', []) if isinstance(data, dict) else data
                else:
                    print(f"❌ Erreur API marchés: {resp.status}")
                    return []
        
        except Exception as e:
            logger.error(f"Erreur get_active_markets: {e}")
            return []

    async def get_market_trades(self, session, condition_id):
        """Récupère les trades d'un marché spécifique"""
        try:
            url = f"{self.data_api}/trades"
            params = {
                'market': condition_id,
                'limit': 100,
                'order_by': 'timestamp'
            }
            
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('data', []) if isinstance(data, dict) else data
                else:
                    return []
        
        except Exception as e:
            logger.error(f"Erreur get_market_trades ({condition_id}): {e}")
            return []

    async def analyze_trade(self, trade, session):
        """Analyse un trade pour détecter les caractéristiques d'insider"""
        score = 0
        
        try:
            # Extraire données
            wallet = trade.get('proxyWallet', '')
            size = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            timestamp = trade.get('timestamp')
            
            # Vérifier les critères
            
            # 1. Taille du pari (max 40 pts)
            if size >= self.MIN_BET_SIZE:
                score += min(40, int((size / self.MIN_BET_SIZE) * 20))
            
            # 2. Wallet nouveau (max 30 pts)
            if wallet and wallet not in self.checked_wallets:
                score += 30
                self.checked_wallets.add(wallet)
            
            # 3. Price extrême (très haut ou très bas = suspect)
            if price > 0.8 or price < 0.2:
                score += 20
            
            # 4. Trading à heures bizarres
            if timestamp:
                try:
                    trade_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    hour = trade_time.hour
                    if hour < 6 or hour > 22:  # Entre minuit et 6h ou après 22h
                        score += 10
                except:
                    pass
            
            is_insider = score >= self.MIN_PROBABILITY
            return is_insider, min(100, score)
        
        except Exception as e:
            logger.error(f"Erreur analyze_trade: {e}")
            return False, 0

    async def send_insider_alert(self, trade, market, score, session):
        """Envoie une alerte Discord"""
        channel = self.get_channel(self.channel_id)
        if not channel:
            return
        
        try:
            # Extraire données
            wallet = trade.get('proxyWallet', 'Unknown')[:10]
            side = trade.get('side', 'UNKNOWN')
            size = float(trade.get('size', 0))
            price = float(trade.get('price', 0))
            outcome = trade.get('outcome', 'Unknown')
            market_title = market.get('title', 'Unknown Market')
            condition_id = market.get('conditionId', '')
            
            # Déterminer l'action
            action = "ACHETER" if side == "BUY" else "VENDRE"
            action_emoji = "✅" if side == "BUY" else "❌"
            
            # Couleur selon probabilité
            if score >= 80:
                color = 0xFF0000  # Rouge
                prob_text = "🔥 TRÈS ÉLEVÉE"
            elif score >= 65:
                color = 0xFF6600  # Orange
                prob_text = "📈 ÉLEVÉE"
            elif score >= 50:
                color = 0xFFCC00  # Jaune
                prob_text = "⚠️ MOYENNE"
            else:
                color = 0x0099FF  # Bleu
                prob_text = "💡 FAIBLE"
            
            # Créer l'embed
            embed = discord.Embed(
                title="🚨 ALERTE INSIDER DÉTECTÉ",
                description=market_title,
                color=color,
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="✅ ACTION À SUIVRE",
                value=f"{action_emoji} {action} {outcome}",
                inline=False
            )
            
            embed.add_field(
                name="🎲 Probabilité Insider",
                value=f"{score}%\n{prob_text}",
                inline=False
            )
            
            embed.add_field(
                name="💡 Détails du Trade",
                value=f"Type: {side}\nOutcome: {outcome}",
                inline=False
            )
            
            embed.add_field(
                name="💰 Taille",
                value=f"${size:,.2f}",
                inline=True
            )
            
            embed.add_field(
                name="💵 Prix/Share",
                value=f"${price:.3f}",
                inline=True
            )
            
            embed.add_field(
                name="👤 Wallet",
                value=f"`{wallet}...`",
                inline=True
            )
            
            embed.add_field(
                name="🔗 Lien Marché",
                value=f"https://polymarket.com/market/{market.get('slug', '')}",
                inline=False
            )
            
            await channel.send(embed=embed)
            print(f"🚨 ALERTE ENVOYÉE: {market_title[:50]} (Score: {score}%)")
        
        except Exception as e:
            logger.error(f"Erreur send_insider_alert: {e}")

def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("❌ DISCORD_BOT_TOKEN non défini!")
        return
    
    bot = PolymarketInsiderBot()
    bot.run(token)

if __name__ == "__main__":
    main()
