import asyncio
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
from datetime import datetime
import json
import hmac
import hashlib
import requests
from urllib.parse import urlencode
import math

class BinanceFuturesAPI:
    def __init__(self, api_key, api_secret, testnet=True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = 'https://testnet.binancefuture.com' if testnet else 'https://fapi.binance.com'
        self.session = requests.Session()
        self.session.headers.update({'X-MBX-APIKEY': api_key})
    
    def _generate_signature(self, params):
        """Генерация подписи для запроса"""
        query_string = urlencode(params)
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _request(self, method, endpoint, params=None, signed=False):
        """Выполнение HTTP запроса"""
        url = f"{self.base_url}{endpoint}"
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._generate_signature(params)
        
        try:
            if method == 'GET':
                response = self.session.get(url, params=params)
            elif method == 'POST':
                response = self.session.post(url, params=params)
            elif method == 'DELETE':
                response = self.session.delete(url, params=params)
            
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_msg = f"Binance API Error {error_data.get('code', 'Unknown')}: {error_data.get('msg', 'Unknown error')}"
                    raise Exception(error_msg)
                except json.JSONDecodeError:
                    response.raise_for_status()
            
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"API запрос не удался: {e}")
    
    def get_exchange_info(self):
        """Получение информации о бирже"""
        return self._request('GET', '/fapi/v1/exchangeInfo')
    
    def get_symbol_price(self, symbol):
        """Получение текущей цены символа"""
        return self._request('GET', '/fapi/v1/ticker/price', {'symbol': symbol})
    
    def get_account_info(self):
        """Получение информации об аккаунте"""
        return self._request('GET', '/fapi/v2/account', signed=True)
    
    def get_position_info(self, symbol=None):
        """Получение информации о позициях"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/fapi/v2/positionRisk', params, signed=True)
    
    def change_leverage(self, symbol, leverage):
        """Изменение кредитного плеча"""
        params = {
            'symbol': symbol,
            'leverage': leverage
        }
        return self._request('POST', '/fapi/v1/leverage', params, signed=True)
    
    def change_position_mode(self, dualSidePosition):
        """Изменение режима позиций"""
        params = {
            'dualSidePosition': 'true' if dualSidePosition else 'false'
        }
        return self._request('POST', '/fapi/v1/positionSide/dual', params, signed=True)
    
    def place_order(self, symbol, side, order_type, quantity, price=None, stop_price=None, position_side='BOTH'):
        """Размещение ордера"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': str(quantity),
            'positionSide': position_side
        }
        
        if order_type in ['LIMIT', 'STOP', 'TAKE_PROFIT']:
            params['timeInForce'] = 'GTC'
        
        if price:
            params['price'] = str(price)
        if stop_price:
            params['stopPrice'] = str(stop_price)
        
        return self._request('POST', '/fapi/v1/order', params, signed=True)
    
    def get_open_orders(self, symbol=None):
        """Получение открытых ордеров"""
        params = {}
        if symbol:
            params['symbol'] = symbol
        return self._request('GET', '/fapi/v1/openOrders', params, signed=True)
    
    def get_order(self, symbol, order_id):
        """Получение информации об ордере"""
        params = {
            'symbol': symbol,
            'orderId': order_id
        }
        return self._request('GET', '/fapi/v1/order', params, signed=True)
    
    def cancel_order(self, symbol, order_id):
        """Отмена ордера"""
        params = {
            'symbol': symbol,
            'orderId': order_id
        }
        return self._request('DELETE', '/fapi/v1/order', params, signed=True)
    
    def cancel_all_orders(self, symbol):
        """Отмена всех ордеров по символу"""
        params = {
            'symbol': symbol
        }
        return self._request('DELETE', '/fapi/v1/allOpenOrders', params, signed=True)


class InvertedGridBot:
    def __init__(self):
        self.api = None
        self.is_running = False
        self.grid_levels = []
        self.active_orders = {}  # order_id -> order_info
        self.grid_orders = {}    # price_level -> order_id
        self.positions = {}      # price_level -> position_info
        self.symbol = ''
        self.leverage = 1
        self.total_capital = 0
        self.tick_size = 0.01
        self.min_qty = 0.001
        self.mark_price = 0
        self.monitoring_thread = None
        self.log_callback = None
        
        # API ключи будут установлены через GUI
        self.API_KEY = ""
        self.API_SECRET = ""
    
    def set_log_callback(self, callback):
        """Установка callback для логирования"""
        self.log_callback = callback
    
    def log(self, message):
        """Логирование сообщений"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message)
        if self.log_callback:
            self.log_callback(log_message)
    
    def initialize_api(self, api_key, api_secret, testnet=True):
        """Инициализация API"""
        try:
            self.API_KEY = api_key
            self.API_SECRET = api_secret
            self.api = BinanceFuturesAPI(self.API_KEY, self.API_SECRET, testnet)
            # Проверяем подключение
            account_info = self.api.get_account_info()
            self.log("✅ API успешно подключен")
            
            # Устанавливаем режим хеджирования
            try:
                self.api.change_position_mode(True)
                self.log("✅ Режим позиций установлен на хеджирование")
            except Exception as e:
                if "No need to change position side" in str(e):
                    self.log("ℹ️ Режим позиций уже установлен на хеджирование")
                else:
                    self.log(f"⚠️ Предупреждение при установке режима позиций: {e}")
            
            return True
        except Exception as e:
            self.log(f"❌ Ошибка подключения к API: {e}")
            return False
    
    def get_symbol_info(self, symbol):
        """Получение информации о символе"""
        try:
            exchange_info = self.api.get_exchange_info()
            symbol_info = None
            
            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    symbol_info = s
                    break
            
            if not symbol_info:
                raise Exception(f"Символ {symbol} не найден")
            
            # Получаем фильтры
            for filter_info in symbol_info['filters']:
                if filter_info['filterType'] == 'PRICE_FILTER':
                    self.tick_size = float(filter_info['tickSize'])
                elif filter_info['filterType'] == 'LOT_SIZE':
                    self.min_qty = float(filter_info['minQty'])
            
            # Получаем текущую цену
            price_info = self.api.get_symbol_price(symbol)
            self.mark_price = float(price_info['price'])
            
            self.log(f"📊 Информация о {symbol}: цена={self.mark_price}, tick_size={self.tick_size}, min_qty={self.min_qty}")
            return True
            
        except Exception as e:
            self.log(f"❌ Ошибка получения информации о символе: {e}")
            return False
    
    def round_to_tick_size(self, price):
        """Округление цены до tick_size"""
        # Определяем количество десятичных знаков в tick_size
        tick_str = f"{self.tick_size:.10f}".rstrip('0')
        if '.' in tick_str:
            decimals = len(tick_str.split('.')[1])
        else:
            decimals = 0
        
        # Округляем цену
        rounded = round(price / self.tick_size) * self.tick_size
        
        # Форматируем с нужным количеством знаков
        return round(rounded, decimals)
    
    def round_to_min_qty(self, qty):
        """Округление количества до min_qty"""
        # Получаем количество десятичных знаков для min_qty
        decimals = 0
        temp = self.min_qty
        while temp < 1:
            temp *= 10
            decimals += 1
        
        # Округляем вниз до нужного количества знаков
        factor = 10 ** decimals
        return math.floor(qty * factor) / factor
    
    def calculate_grid_levels(self, lower_bound, upper_bound, grid_count, total_capital):
        """Расчет уровней сетки"""
        step = (upper_bound - lower_bound) / grid_count
        levels = []
        capital_per_level = total_capital / (grid_count + 1)
        
        self.log(f"📈 Расчет сетки:")
        self.log(f"  - Общий капитал: ${total_capital}")
        self.log(f"  - Количество уровней: {grid_count + 1}")
        self.log(f"  - Капитал на уровень: ${capital_per_level:.2f}")
        self.log(f"  - Кредитное плечо: {self.leverage}x")
        self.log(f"  - Шаг сетки: ${step:.5f}")
        
        for i in range(grid_count + 1):
            price = upper_bound - (i * step)  # От верхней границы вниз
            price = self.round_to_tick_size(price)
            
            # Рассчитываем количество для SHORT позиции
            quantity = (capital_per_level * self.leverage) / price
            quantity = self.round_to_min_qty(quantity)
            
            if quantity >= self.min_qty:
                # Стоп-лосс на 20% от шага выше точки входа
                stop_loss = self.round_to_tick_size(price + (step * 0.2))
                levels.append({
                    'price': price,
                    'quantity': quantity,
                    'capital': capital_per_level,
                    'stop_loss': stop_loss,
                    'step_size': step
                })
        
        self.log(f"✅ Создано {len(levels)} уровней сетки")
        return levels
    
    async def place_limit_order(self, side, quantity, price, position_side='SHORT'):
        """Размещение LIMIT ордера"""
        try:
            # Форматируем цену правильно
            formatted_price = f"{price:.5f}".rstrip('0').rstrip('.')
            
            order = self.api.place_order(
                symbol=self.symbol,
                side=side,
                order_type='LIMIT',
                quantity=str(quantity),
                price=formatted_price,
                position_side=position_side
            )
            
            order_id = order['orderId']
            self.active_orders[order_id] = {
                'orderId': order_id,
                'symbol': self.symbol,
                'side': side,
                'type': 'LIMIT',
                'quantity': quantity,
                'price': price,
                'positionSide': position_side,
                'status': 'NEW',
                'time': time.time()
            }
            
            # Сохраняем связь между уровнем цены и ордером
            if side == 'SELL' and position_side == 'SHORT':
                self.grid_orders[price] = order_id
            
            self.log(f"📝 Размещен {side} LIMIT ордер: ID={order_id}, объем={quantity}, цена={formatted_price}")
            return order
            
        except Exception as e:
            self.log(f"❌ Ошибка размещения ордера: {e}")
            return None
    
    async def place_stop_market_order(self, side, quantity, stop_price, position_side='SHORT'):
        """Размещение STOP_MARKET ордера"""
        try:
            formatted_price = f"{stop_price:.5f}".rstrip('0').rstrip('.')
            
            order = self.api.place_order(
                symbol=self.symbol,
                side=side,
                order_type='STOP_MARKET',
                quantity=str(quantity),
                stop_price=formatted_price,
                position_side=position_side
            )
            
            order_id = order['orderId']
            self.active_orders[order_id] = {
                'orderId': order_id,
                'symbol': self.symbol,
                'side': side,
                'type': 'STOP_MARKET',
                'quantity': quantity,
                'stopPrice': stop_price,
                'positionSide': position_side,
                'status': 'NEW',
                'time': time.time()
            }
            
            self.log(f"🛡️ Размещен STOP-LOSS: ID={order_id}, объем={quantity}, стоп-цена={formatted_price}")
            return order
            
        except Exception as e:
            self.log(f"❌ Ошибка размещения стоп-ордера: {e}")
            return None
    
    async def check_and_restore_grid(self):
        """Проверка и восстановление сетки"""
        try:
            # Получаем текущую цену
            price_info = self.api.get_symbol_price(self.symbol)
            current_price = float(price_info['price'])
            
            # Получаем информацию о позициях
            positions_info = self.api.get_position_info(self.symbol)
            
            # Получаем все открытые ордера
            open_orders = self.api.get_open_orders(self.symbol)
            open_order_ids = {order['orderId'] for order in open_orders}
            
            # Проверяем исполненные ордера
            for order_id, order_info in list(self.active_orders.items()):
                if order_id not in open_order_ids:
                    # Ордер исполнен или отменен
                    try:
                        order_status = self.api.get_order(self.symbol, order_id)
                        
                        if order_status['status'] == 'FILLED':
                            # Ордер исполнен
                            if order_info['type'] == 'LIMIT' and order_info['side'] == 'SELL':
                                # Входной ордер исполнен - открыта SHORT позиция
                                entry_price = order_info['price']
                                quantity = order_info['quantity']
                                
                                # Находим соответствующий уровень сетки
                                level = next((l for l in self.grid_levels if abs(l['price'] - entry_price) < self.tick_size), None)
                                if level:
                                    # НЕ ставим стоп-лосс сразу - ждем когда цена поднимется
                                    self.log(f"🎯 Открыт SHORT на {entry_price}, стоп-лосс будет установлен при достижении цены")
                                    
                                    # Сохраняем информацию о позиции
                                    self.positions[entry_price] = {
                                        'entry_price': entry_price,
                                        'quantity': quantity,
                                        'stop_loss': level['stop_loss'],
                                        'stop_loss_placed': False,
                                        'time': time.time()
                                    }
                                    
                                    # Удаляем из grid_orders
                                    if entry_price in self.grid_orders:
                                        del self.grid_orders[entry_price]
                            
                            elif order_info['type'] == 'STOP_MARKET' and order_info['side'] == 'BUY':
                                # Стоп-лосс исполнен - позиция закрыта
                                # Находим, какая позиция была закрыта
                                closed_position = None
                                for price, pos in self.positions.items():
                                    if 'actual_stop_loss' in pos and abs(pos['actual_stop_loss'] - order_info['stopPrice']) < self.tick_size:
                                        closed_position = price
                                        break
                                
                                if closed_position:
                                    self.log(f"💥 Сработал стоп-лосс на {order_info['stopPrice']}, позиция закрыта")
                                    
                                    # Восстанавливаем ордер на этом уровне
                                    if closed_position not in self.grid_orders:
                                        level = next((l for l in self.grid_levels if abs(l['price'] - closed_position) < self.tick_size), None)
                                        if level and level['price'] < current_price:
                                            await self.place_limit_order('SELL', level['quantity'], level['price'], 'SHORT')
                                            self.log(f"♻️ Восстановлен уровень сетки на {level['price']}")
                                    
                                    # Удаляем из позиций
                                    del self.positions[closed_position]
                    
                    except Exception as e:
                        self.log(f"⚠️ Ошибка при проверке ордера {order_id}: {e}")
                    
                    # Удаляем из активных ордеров
                    del self.active_orders[order_id]
            
            # Проверяем позиции и устанавливаем стоп-лоссы когда цена достигает нужного уровня
            for entry_price, pos_info in list(self.positions.items()):
                if not pos_info.get('stop_loss_placed', False):
                    # Проверяем, достигла ли цена уровня для установки стоп-лосса
                    # Для SHORT позиции ждем, когда цена поднимется близко к стоп-лоссу
                    if current_price >= entry_price:
                        # Цена поднялась выше точки входа - можно ставить стоп-лосс
                        stop_loss_price = pos_info['stop_loss']
                        if current_price < stop_loss_price - self.tick_size * 10:  # Оставляем запас
                            await self.place_stop_market_order('BUY', pos_info['quantity'], stop_loss_price, 'SHORT')
                            self.log(f"🛡️ Установлен отложенный SL для SHORT {entry_price} на уровне {stop_loss_price}")
                            pos_info['stop_loss_placed'] = True
                            pos_info['actual_stop_loss'] = stop_loss_price
            
            # Проверяем, все ли уровни сетки покрыты ордерами
            for level in self.grid_levels:
                if level['price'] < current_price and level['price'] not in self.grid_orders and level['price'] not in self.positions:
                    # Уровень не покрыт ордером и нет открытой позиции
                    await self.place_limit_order('SELL', level['quantity'], level['price'], 'SHORT')
                    self.log(f"🔄 Добавлен недостающий уровень на {level['price']}")
                        
        except Exception as e:
            self.log(f"❌ Ошибка проверки и восстановления сетки: {e}")
    
    def monitoring_loop(self):
        """Основной цикл мониторинга"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while self.is_running:
            try:
                loop.run_until_complete(self.check_and_restore_grid())
                time.sleep(3)  # Проверяем каждые 3 секунды
            except Exception as e:
                self.log(f"❌ Ошибка в цикле мониторинга: {e}")
                time.sleep(5)
        
        loop.close()
    
    async def start(self, config):
        """Запуск бота"""
        try:
            self.symbol = config['symbol']
            self.leverage = config['leverage']
            self.total_capital = config['total_capital']
            
            # Инициализируем API с переданными ключами
            if not self.initialize_api(config['api_key'], config['api_secret'], config['testnet']):
                raise Exception("Не удалось инициализировать API")
            
            # Получаем информацию о символе
            if not self.get_symbol_info(self.symbol):
                raise Exception("Не удалось получить информацию о символе")
            
            # Устанавливаем кредитное плечо
            try:
                self.api.change_leverage(self.symbol, self.leverage)
                self.log(f"⚡ Установлено кредитное плечо: {self.leverage}x")
            except Exception as e:
                self.log(f"⚠️ Предупреждение при установке плеча: {e}")
            
            # Рассчитываем уровни сетки
            self.grid_levels = self.calculate_grid_levels(
                config['lower_bound'],
                config['upper_bound'],
                config['grid_count'],
                config['total_capital']
            )
            
            if not self.grid_levels:
                raise Exception("Не удалось создать уровни сетки. Проверьте параметры.")
            
            self.log(f"📊 Создано {len(self.grid_levels)} уровней сетки")
            
            # Размещаем LIMIT ордера на продажу для уровней ниже текущей цены
            placed_count = 0
            for level in self.grid_levels:
                if level['price'] < self.mark_price:
                    # Размещаем LIMIT SELL ордер для открытия SHORT позиции при падении цены
                    await self.place_limit_order('SELL', level['quantity'], level['price'], 'SHORT')
                    placed_count += 1
                else:
                    self.log(f"  ⏭️ Пропускаем уровень {level['price']} (выше текущей цены {self.mark_price})")
            
            if placed_count == 0:
                raise Exception("Не удалось разместить ни одного ордера. Все уровни выше текущей цены.")
            
            self.log(f"✅ Размещено {placed_count} входных ордеров")
            
            self.is_running = True
            
            # Запускаем поток мониторинга
            self.monitoring_thread = threading.Thread(target=self.monitoring_loop)
            self.monitoring_thread.daemon = True
            self.monitoring_thread.start()
            
            self.log("🚀 Бот успешно запущен!")
            self.log("ℹ️ Бот будет открывать SHORT позиции при падении цены до уровней сетки")
            return True
            
        except Exception as e:
            self.log(f"❌ Ошибка запуска бота: {e}")
            return False
    
    async def stop(self):
        """Остановка бота"""
        self.is_running = False
        
        # Отменяем все активные ордера
        try:
            self.api.cancel_all_orders(self.symbol)
            self.log("🚫 Отменены все ордера")
        except Exception as e:
            self.log(f"⚠️ Ошибка при отмене ордеров: {e}")
        
        # Ждем завершения потока мониторинга
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=5)
        
        self.log("🛑 Бот остановлен")
        self.log(f"📊 Открытых позиций: {len(self.positions)}")


class GridBotGUI:
    def __init__(self):
        self.bot = InvertedGridBot()
        self.bot.set_log_callback(self.add_log)
        
        self.root = tk.Tk()
        self.root.title("Inverted Long Grid Bot - SHORT на падении")
        self.root.geometry("800x900")
        self.root.configure(bg='#2b2b2b')
        
        self.create_widgets()
        
    def create_widgets(self):
        """Создание виджетов интерфейса"""
        # Заголовок
        title_label = tk.Label(
            self.root,
            text="Inverted Long Grid Bot - SHORT",
            font=('Arial', 18, 'bold'),
            bg='#2b2b2b',
            fg='#ff6b6b'
        )
        title_label.pack(pady=10)
        
        info_label = tk.Label(
            self.root,
            text="Бот открывает SHORT позиции при падении цены",
            font=('Arial', 10),
            bg='#2b2b2b',
            fg='#ffffff'
        )
        info_label.pack()
        
        # Основной фрейм
        main_frame = tk.Frame(self.root, bg='#2b2b2b')
        main_frame.pack(fill='both', expand=True, padx=20, pady=10)
        
        # API настройки
        api_frame = tk.LabelFrame(main_frame, text="API Настройки", bg='#3b3b3b', fg='#ffffff', font=('Arial', 10, 'bold'))
        api_frame.pack(fill='x', pady=5)
        
        tk.Label(api_frame, text="API Key:", bg='#3b3b3b', fg='#ffffff').grid(row=0, column=0, sticky='w', padx=5, pady=5)
        self.api_key_var = tk.StringVar()
        api_key_entry = tk.Entry(api_frame, textvariable=self.api_key_var, bg='#4b4b4b', fg='#ffffff', width=50)
        api_key_entry.grid(row=0, column=1, columnspan=3, sticky='ew', padx=5, pady=5)
        
        tk.Label(api_frame, text="API Secret:", bg='#3b3b3b', fg='#ffffff').grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.api_secret_var = tk.StringVar()
        api_secret_entry = tk.Entry(api_frame, textvariable=self.api_secret_var, bg='#4b4b4b', fg='#ffffff', width=50, show='*')
        api_secret_entry.grid(row=1, column=1, columnspan=3, sticky='ew', padx=5, pady=5)
        
        tk.Label(api_frame, text="Режим:", bg='#3b3b3b', fg='#ffffff').grid(row=2, column=0, sticky='w', padx=5, pady=5)
        self.testnet_var = tk.BooleanVar(value=False)
        mainnet_radio = tk.Radiobutton(api_frame, text="Mainnet", variable=self.testnet_var, value=False, bg='#3b3b3b', fg='#ffffff', selectcolor='#2b2b2b')
        mainnet_radio.grid(row=2, column=1, sticky='w', padx=5, pady=5)
        testnet_radio = tk.Radiobutton(api_frame, text="Testnet", variable=self.testnet_var, value=True, bg='#3b3b3b', fg='#ffffff', selectcolor='#2b2b2b')
        testnet_radio.grid(row=2, column=2, sticky='w', padx=5, pady=5)
        
        api_frame.columnconfigure(1, weight=1)
        
        # Параметры торговли
        trading_frame = tk.LabelFrame(main_frame, text="Параметры торговли", bg='#3b3b3b', fg='#ffffff', font=('Arial', 10, 'bold'))
        trading_frame.pack(fill='x', pady=5)
        
        tk.Label(trading_frame, text="Символ:", bg='#3b3b3b', fg='#ffffff').grid(row=0, column=0, sticky='w', padx=5, pady=5)
        self.symbol_var = tk.StringVar(value="DOGEUSDT")
        symbol_entry = tk.Entry(trading_frame, textvariable=self.symbol_var, bg='#4b4b4b', fg='#ffffff')
        symbol_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        
        tk.Label(trading_frame, text="Кредитное плечо:", bg='#3b3b3b', fg='#ffffff').grid(row=0, column=2, sticky='w', padx=5, pady=5)
        self.leverage_var = tk.IntVar(value=10)
        leverage_entry = tk.Entry(trading_frame, textvariable=self.leverage_var, bg='#4b4b4b', fg='#ffffff')
        leverage_entry.grid(row=0, column=3, sticky='ew', padx=5, pady=5)
        
        tk.Label(trading_frame, text="Общий капитал (USDT):", bg='#3b3b3b', fg='#ffffff').grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.capital_var = tk.DoubleVar(value=100)
        capital_entry = tk.Entry(trading_frame, textvariable=self.capital_var, bg='#4b4b4b', fg='#ffffff')
        capital_entry.grid(row=1, column=1, sticky='ew', padx=5, pady=5)
        
        trading_frame.columnconfigure(1, weight=1)
        trading_frame.columnconfigure(3, weight=1)
        
        # Параметры сетки
        grid_frame = tk.LabelFrame(main_frame, text="Параметры сетки", bg='#3b3b3b', fg='#ffffff', font=('Arial', 10, 'bold'))
        grid_frame.pack(fill='x', pady=5)
        
        tk.Label(grid_frame, text="Нижняя граница:", bg='#3b3b3b', fg='#ffffff').grid(row=0, column=0, sticky='w', padx=5, pady=5)
        self.lower_bound_var = tk.DoubleVar(value=0.20)
        lower_entry = tk.Entry(grid_frame, textvariable=self.lower_bound_var, bg='#4b4b4b', fg='#ffffff')
        lower_entry.grid(row=0, column=1, sticky='ew', padx=5, pady=5)
        
        tk.Label(grid_frame, text="Верхняя граница:", bg='#3b3b3b', fg='#ffffff').grid(row=0, column=2, sticky='w', padx=5, pady=5)
        self.upper_bound_var = tk.DoubleVar(value=0.25)
        upper_entry = tk.Entry(grid_frame, textvariable=self.upper_bound_var, bg='#4b4b4b', fg='#ffffff')
        upper_entry.grid(row=0, column=3, sticky='ew', padx=5, pady=5)
        
        tk.Label(grid_frame, text="Количество сеток:", bg='#3b3b3b', fg='#ffffff').grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.grid_count_var = tk.IntVar(value=10)
        grid_count_entry = tk.Entry(grid_frame, textvariable=self.grid_count_var, bg='#4b4b4b', fg='#ffffff')
        grid_count_entry.grid(row=1, column=1, sticky='ew', padx=5, pady=5)
        
        grid_frame.columnconfigure(1, weight=1)
        grid_frame.columnconfigure(3, weight=1)
        
        # Кнопки управления
        control_frame = tk.Frame(main_frame, bg='#2b2b2b')
        control_frame.pack(fill='x', pady=10)
        
        self.calculate_btn = tk.Button(
            control_frame, 
            text="Рассчитать сетку", 
            command=self.calculate_grid,
            bg='#00d4ff', 
            fg='#000000', 
            font=('Arial', 10, 'bold')
        )
        self.calculate_btn.pack(side='left', padx=5)
        
        self.start_btn = tk.Button(
            control_frame, 
            text="Запустить бота", 
            command=self.start_bot,
            bg='#4caf50', 
            fg='#ffffff', 
            font=('Arial', 10, 'bold'),
            state='disabled'
        )
        self.start_btn.pack(side='left', padx=5)
        
        self.stop_btn = tk.Button(
            control_frame, 
            text="Остановить бота", 
            command=self.stop_bot,
            bg='#f44336', 
            fg='#ffffff', 
            font=('Arial', 10, 'bold'),
            state='disabled'
        )
        self.stop_btn.pack(side='left', padx=5)
        
        # Информация о сетке
        self.grid_info_frame = tk.LabelFrame(main_frame, text="Уровни сетки", bg='#3b3b3b', fg='#ffffff', font=('Arial', 10, 'bold'))
        self.grid_info_frame.pack(fill='both', expand=True, pady=5)
        
        self.grid_text = scrolledtext.ScrolledText(
            self.grid_info_frame, 
            height=8, 
            bg='#4b4b4b', 
            fg='#ffffff',
            font=('Courier', 9)
        )
        self.grid_text.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Лог
        log_frame = tk.LabelFrame(main_frame, text="Лог", bg='#3b3b3b', fg='#ffffff', font=('Arial', 10, 'bold'))
        log_frame.pack(fill='both', expand=True, pady=5)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            height=10, 
            bg='#1a1a1a', 
            fg='#00ff00',
            font=('Courier', 9)
        )
        self.log_text.pack(fill='both', expand=True, padx=5, pady=5)
        
    def add_log(self, message):
        """Добавление сообщения в лог"""
        self.log_text.insert(tk.END, message + '\n')
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def calculate_grid(self):
        """Расчет сетки"""
        try:
            lower_bound = self.lower_bound_var.get()
            upper_bound = self.upper_bound_var.get()
            grid_count = self.grid_count_var.get()
            total_capital = self.capital_var.get()
            leverage = self.leverage_var.get()
            
            if lower_bound >= upper_bound:
                messagebox.showerror("Ошибка", "Нижняя граница должна быть меньше верхней")
                return
            
            if grid_count < 2:
                messagebox.showerror("Ошибка", "Количество сеток должно быть не менее 2")
                return
            
            # Проверка минимального капитала
            avg_price = (lower_bound + upper_bound) / 2
            min_capital_per_level = (0.001 * avg_price) / leverage  # минимальный объем * средняя цена / плечо
            min_total_capital = min_capital_per_level * (grid_count + 1)
            
            if total_capital < min_total_capital:
                messagebox.showwarning(
                    "Предупреждение", 
                    f"Капитал ${total_capital} может быть недостаточным.\n"
                    f"Рекомендуемый минимум: ${min_total_capital:.2f}\n"
                    f"для {grid_count + 1} уровней при плече {leverage}x"
                )
            
            # Симуляция расчета (без API)
            step = (upper_bound - lower_bound) / grid_count
            capital_per_level = total_capital / (grid_count + 1)
            
            self.grid_text.delete(1.0, tk.END)
            self.grid_text.insert(tk.END, f"{'№':<3} {'Цена входа':<12} {'Объем':<12} {'Стоп-лосс':<12} {'Капитал':<10}\n")
            self.grid_text.insert(tk.END, "-" * 60 + "\n")
            
            valid_levels = 0
            for i in range(grid_count + 1):
                price = upper_bound - (i * step)  # От верхней границы вниз
                quantity = (capital_per_level * leverage) / price
                stop_loss = price + (step * 0.2)  # 20% от шага
                
                # Проверяем минимальный объем
                if quantity >= 0.001:
                    valid_levels += 1
                    status = "✓"
                else:
                    status = "✗"
                
                self.grid_text.insert(
                    tk.END, 
                    f"{status} {i+1:<2} {price:<12.5f} {quantity:<12.6f} {stop_loss:<12.5f} {capital_per_level:<10.2f}\n"
                )
            
            self.grid_text.insert(tk.END, "\n" + "="*60 + "\n")
            self.grid_text.insert(tk.END, "ℹ️ Логика работы бота:\n")
            self.grid_text.insert(tk.END, "1. При падении цены до уровня открывается SHORT позиция\n")
            self.grid_text.insert(tk.END, "2. Сразу устанавливается стоп-лосс выше точки входа\n")
            self.grid_text.insert(tk.END, "3. При срабатывании стоп-лосса уровень восстанавливается\n")
            self.grid_text.insert(tk.END, "4. Бот работает бесконечно, поддерживая сетку\n")
            
            if valid_levels == 0:
                messagebox.showerror(
                    "Ошибка", 
                    "Невозможно создать ни одного валидного уровня с текущими параметрами.\n\n"
                    "Попробуйте:\n"
                    "• Увеличить капитал\n"
                    "• Увеличить кредитное плечо\n"
                    "• Уменьшить количество сеток\n"
                    "• Сузить диапазон цен"
                )
                self.start_btn.config(state='disabled')
            else:
                self.start_btn.config(state='normal')
                self.add_log(f"✅ Сетка рассчитана: {valid_levels} валидных уровней из {grid_count + 1}")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка расчета сетки: {e}")
    
    def start_bot(self):
        """Запуск бота"""
        # Проверяем, что введены API ключи
        api_key = self.api_key_var.get().strip()
        api_secret = self.api_secret_var.get().strip()
        
        if not api_key or not api_secret:
            messagebox.showerror("Ошибка", "Пожалуйста, введите API ключи")
            return
        
        config = {
            'api_key': api_key,
            'api_secret': api_secret,
            'testnet': self.testnet_var.get(),
            'symbol': self.symbol_var.get(),
            'leverage': self.leverage_var.get(),
            'total_capital': self.capital_var.get(),
            'lower_bound': self.lower_bound_var.get(),
            'upper_bound': self.upper_bound_var.get(),
            'grid_count': self.grid_count_var.get()
        }
        
        def run_start():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(self.bot.start(config))
            loop.close()
            
            if success:
                self.root.after(0, lambda: [
                    self.start_btn.config(state='disabled'),
                    self.stop_btn.config(state='normal'),
                    self.calculate_btn.config(state='disabled')
                ])
            
        thread = threading.Thread(target=run_start)
        thread.daemon = True
        thread.start()
    
    def stop_bot(self):
        """Остановка бота"""
        def run_stop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.bot.stop())
            loop.close()
            
            self.root.after(0, lambda: [
                self.start_btn.config(state='normal'),
                self.stop_btn.config(state='disabled'),
                self.calculate_btn.config(state='normal')
            ])
        
        thread = threading.Thread(target=run_stop)
        thread.daemon = True
        thread.start()
    
    def run(self):
        """Запуск GUI"""
        self.root.mainloop()


if __name__ == "__main__":
    # Проверяем наличие необходимых библиотек
    try:
        import requests
    except ImportError:
        print("Установите библиотеку requests: pip install requests")
        exit(1)
    
    app = GridBotGUI()
    app.run()