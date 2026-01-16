"""
Modbus клиент для работы с XeUS driver
Поддерживает Modbus RTU over TCP/IP
"""
from pymodbus.client import ModbusTcpClient
from typing import Optional
import logging
import socket
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ModbusClient:
    """Класс для работы с Modbus RTU over TCP/IP клиентом"""
    
    def __init__(self, host: str = "192.168.4.1", port: int = 503, unit_id: int = 1, framer: str = "rtu"):
        """
        Инициализация Modbus клиента
        
        Args:
            host: IP адрес устройства (по умолчанию 192.168.4.1)
            port: Порт Modbus (по умолчанию 503)
            unit_id: ID устройства Modbus (по умолчанию 1)
            framer: Тип фрейминга - "rtu" для RTU over TCP/IP, "tcp" для стандартного TCP (по умолчанию "rtu")
        """
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.framer = framer
        self.client: Optional[ModbusTcpClient] = None
        self._connected = False
    
    def connect(self) -> bool:
        """
        Подключение к Modbus устройству
        
        Returns:
            True если подключение успешно, False в противном случае
        """
        try:
            # Закрываем существующее подключение, если есть
            if self.client is not None:
                try:
                    self.client.close()
                except:
                    pass
                self.client = None
            
            # Создаем новый клиент
            # Для RTU over TCP может использоваться "socket" фреймер
            # Если это не работает, можно попробовать стандартный "tcp"
            logger.info(f"Попытка подключения к {self.host}:{self.port} с фреймером '{self.framer}'")
            
            # Определяем какой фреймер использовать
            if self.framer == "rtu":
                # RTU over TCP использует socket фреймер в pymodbus
                framers_to_try = ["socket", "tcp"]  # Сначала пробуем socket, потом стандартный TCP
            elif self.framer == "tcp":
                framers_to_try = ["tcp"]
            else:
                framers_to_try = [self.framer]
            
            last_error = None
            for actual_framer in framers_to_try:
                try:
                    logger.info(f"Попытка подключения с фреймером '{actual_framer}'")
                    # Настраиваем таймауты для избежания блокировки UI
                    # Уменьшаем количество повторных попыток, но оставляем достаточный таймаут для записи
                    
                    # Функция для трассировки пакетов
                    def trace_packet(is_tx, packet):
                        direction = "Tx" if is_tx else "Rx"
                        hex_str = " ".join(f"{b:02X}" for b in packet)
                        logger.info(f"Modbus {direction}: {hex_str}")
                        return packet
                    
                    # Устанавливаем таймаут как в рабочей версии (ноябрь 2024)
                    self.client = ModbusTcpClient(
                        host=self.host, 
                        port=self.port, 
                        framer=actual_framer,
                        timeout=2.0,  # 2 секунды - компромисс между стабильностью и отзывчивостью
                        retries=1,    # 1 повтор для надежности
                        trace_packet=trace_packet  # Трассировка пакетов для отладки
                    )
                    
                    # Настраиваем TCP keep-alive на уровне сокета после подключения
                    # Это нужно сделать после connect(), когда сокет уже создан
                    
                    # Пытаемся подключиться
                    connection_result = self.client.connect()
                    logger.info(f"Результат connect() с фреймером '{actual_framer}': {connection_result}")
                    
                    if connection_result:
                        # Проверяем, что сокет действительно открыт
                        if self.client.is_socket_open():
                            # Настраиваем TCP keep-alive на уровне сокета
                            try:
                                import socket
                                sock = None
                                
                                # Пробуем разные способы доступа к сокету в pymodbus
                                if hasattr(self.client, 'socket') and self.client.socket:
                                    sock = self.client.socket
                                elif hasattr(self.client, 'transport'):
                                    # Пробуем разные атрибуты транспорта
                                    transport = self.client.transport
                                    if hasattr(transport, 'socket') and transport.socket:
                                        sock = transport.socket
                                    elif hasattr(transport, '_socket') and transport._socket:
                                        sock = transport._socket
                                    elif hasattr(transport, 'sock') and transport.sock:
                                        sock = transport.sock
                                    elif hasattr(transport, '_sock') and transport._sock:
                                        sock = transport._sock
                                    # Пробуем получить сокет через get_socket или подобный метод
                                    elif hasattr(transport, 'get_socket'):
                                        try:
                                            sock = transport.get_socket()
                                        except:
                                            pass
                                
                                if sock:
                                    # Включаем TCP keep-alive
                                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                                    # Проверяем, что keep-alive включен
                                    keepalive_enabled = sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
                                    logger.info(f"TCP SO_KEEPALIVE установлен: {keepalive_enabled}")
                                    
                                    # Настраиваем параметры keep-alive (Linux/Mac)
                                    try:
                                        # Для Linux используем TCP_KEEPIDLE, TCP_KEEPINTVL, TCP_KEEPCNT
                                        if hasattr(socket, 'TCP_KEEPIDLE'):
                                            # TCP_KEEPIDLE - время до первого keep-alive пакета (2 секунды)
                                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 2)
                                            # TCP_KEEPINTVL - интервал между keep-alive пакетами (2 секунды)
                                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
                                            # TCP_KEEPCNT - количество попыток перед закрытием (3)
                                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                                            logger.info("TCP keep-alive настроен (Linux): пинг каждые 2 секунды")
                                        elif hasattr(socket, 'TCP_KEEPALIVE'):
                                            # Для macOS используем TCP_KEEPALIVE (если доступен)
                                            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 2)
                                            logger.info("TCP keep-alive настроен (macOS): используем TCP_KEEPALIVE")
                                        else:
                                            # На macOS без специальных опций keep-alive управляется системой
                                            # Интервал по умолчанию обычно около 75 секунд, но мы будем использовать
                                            # периодические Modbus запросы для поддержания соединения
                                            logger.info("TCP keep-alive включен (macOS): интервал управляется системой, используем Modbus keep-alive")
                                    except (AttributeError, OSError) as e:
                                        # На Mac может не быть TCP_KEEPIDLE, используем только SO_KEEPALIVE
                                        logger.info(f"Расширенные опции keep-alive не поддерживаются: {e}, используем только SO_KEEPALIVE + Modbus keep-alive")
                                else:
                                    logger.warning("Не удалось найти сокет для настройки keep-alive. Доступные атрибуты клиента: " + 
                                                  str([attr for attr in dir(self.client) if not attr.startswith('_')]))
                                    # Пробуем получить сокет через другой способ
                                    if hasattr(self.client, 'transport'):
                                        logger.debug(f"Атрибуты transport: {[attr for attr in dir(self.client.transport) if not attr.startswith('__')]}")
                            except Exception as e:
                                logger.warning(f"Не удалось настроить TCP keep-alive: {e}", exc_info=True)
                            
                            self._connected = True
                            logger.info(f"Успешно подключено к Modbus устройству {self.host}:{self.port} с фреймером '{actual_framer}'")
                            # Добавляем небольшую задержку после подключения, чтобы устройство успело инициализироваться
                            # Первый пакет может теряться, если отправить его сразу после подключения
                            import time
                            time.sleep(0.2)  # 200ms задержка после подключения
                            logger.debug("Задержка после подключения завершена, готовы к работе")
                            return True
                        else:
                            logger.warning(f"Сокет не открыт после подключения с фреймером '{actual_framer}'")
                            try:
                                self.client.close()
                            except:
                                pass
                            self.client = None
                    else:
                        logger.warning(f"connect() вернул False с фреймером '{actual_framer}'")
                        try:
                            self.client.close()
                        except:
                            pass
                        self.client = None
                except Exception as e:
                    last_error = e
                    logger.warning(f"Ошибка при подключении с фреймером '{actual_framer}': {e}")
                    if self.client is not None:
                        try:
                            self.client.close()
                        except:
                            pass
                        self.client = None
                    continue
            
            # Если все попытки не удались
            logger.error(f"Не удалось подключиться к {self.host}:{self.port} ни с одним из фреймеров: {framers_to_try}")
            if last_error:
                logger.error(f"Последняя ошибка: {last_error}")
            self._connected = False
            return False
        except Exception as e:
            logger.error(f"Исключение при подключении к {self.host}:{self.port}: {e}", exc_info=True)
            self._connected = False
            if self.client is not None:
                try:
                    self.client.close()
                except:
                    pass
                self.client = None
            return False
    
    def disconnect(self):
        """Отключение от Modbus устройства"""
        try:
            if self.client is not None:
                logger.info("Закрытие соединения с Modbus устройством")
                self.client.close()
                self._connected = False
                logger.info("Отключено от Modbus устройства")
        except Exception as e:
            logger.error(f"Ошибка при отключении: {e}", exc_info=True)
        finally:
            self.client = None
            self._connected = False
    
    def is_connected(self) -> bool:
        """Проверка состояния подключения БЕЗ синхронных операций (для мгновенной проверки)"""
        # ВСЕГДА возвращаем только кэшированное значение БЕЗ вызова is_socket_open()
        # Вызов is_socket_open() может блокировать UI на несколько секунд
        # Реальное состояние подключения проверяется асинхронно через таймер в ModbusManager
        return self._connected
    
    def read_holding_register(self, address: int) -> Optional[int]:
        """
        Чтение holding register
        
        Args:
            address: Адрес регистра (например, 1010 для параметра 101)
            
        Returns:
            Значение регистра или None в случае ошибки
        """
        # Проверяем соединение, но не блокируем чтение если сокет открыт
        if self.client is None:
            logger.warning("Клиент не инициализирован")
            return None
        if not self.client.is_socket_open():
            logger.debug(f"Сокет закрыт при чтении регистра {address}")
            self._connected = False
            return None
        
        try:
            # Таймаут устанавливается при создании клиента, не передается в read_holding_registers
            result = self.client.read_holding_registers(
                address, 
                count=1, 
                device_id=self.unit_id
            )
            if result.isError():
                # Не логируем как ошибку, если это просто таймаут - это нормально при проблемах с устройством
                error_str = str(result)
                if "No response" in error_str or "timeout" in error_str.lower():
                    logger.debug(f"Таймаут при чтении регистра {address}")
                else:
                    logger.error(f"Ошибка чтения регистра {address}: {result}")
                return None
            return result.registers[0] if result.registers else None
        except Exception as e:
            # Не логируем таймауты как критические ошибки
            error_str = str(e)
            # При ошибке "CLOSING CONNECTION" pymodbus сам закрывает соединение
            # Мы только обновляем флаг, но НЕ закрываем соединение повторно
            if "CLOSING CONNECTION" in error_str:
                logger.debug(f"pymodbus закрыл соединение из-за отсутствия ответа при чтении регистра {address}")
                # Проверяем реальное состояние сокета и обновляем флаг
                try:
                    if self.client is not None and not self.client.is_socket_open():
                        self._connected = False
                        # НЕ закрываем соединение - pymodbus уже закрыл его
                except:
                    self._connected = False
            # Не помечаем как отключенное при обычных таймаутах - сокет может быть еще открыт
            elif "No response" in error_str or "timeout" in error_str.lower():
                logger.debug(f"Таймаут при чтении регистра {address} (соединение может быть еще открыто)")
                # При таймауте НЕ закрываем соединение - оно может быть еще активным
            else:
                logger.debug(f"Исключение при чтении регистра {address}: {e}")
            return None
    
    def write_register(self, address: int, value: int) -> bool:
        """
        Запись значения в регистр
        
        Args:
            address: Адрес регистра
            value: Значение для записи
            
        Returns:
            True если запись успешна, False в противном случае
        """
        # Проверяем соединение, но не блокируем запись если сокет открыт
        if self.client is None:
            logger.warning("Клиент не инициализирован")
            return False
        if not self.client.is_socket_open():
            logger.warning(f"Сокет закрыт при записи в регистр {address}")
            self._connected = False
            return False
        
        try:
            logger.info(f"Запись в регистр {address} значение {value}, unit_id={self.unit_id}, framer={self.framer}")
            # Проверяем, что сокет открыт перед записью
            if not self.client.is_socket_open():
                logger.error(f"Сокет закрыт перед записью в регистр {address}, требуется переподключение")
                self._connected = False
                return False
            
            # Для socket framer (Modbus RTU over TCP) unit_id должен быть указан
            # В документации указан Slave ID = 1, поэтому используем unit_id=1
            # Функция 06 (Write Single Register) используется по умолчанию в write_register
            logger.debug(f"Попытка записи: address={address} (0x{address:04X}), value={value} (0x{value:04X}), device_id={self.unit_id}")
            logger.info(f"Используется функция 06 (Write Single Register) для записи в регистр {address}")
            result = self.client.write_register(
                address, 
                value, 
                device_id=self.unit_id
            )
            if hasattr(result, 'isError') and result.isError():
                error_str = str(result)
                error_code = getattr(result, 'exception_code', 'N/A')
                error_message = getattr(result, 'message', 'N/A')
                logger.error(f"Ошибка записи в регистр {address} значение {value}: {error_str}")
                logger.error(f"  Код ошибки: {error_code}, Сообщение: {error_message}")
                if "No response" in error_str or "timeout" in error_str.lower():
                    logger.warning(f"Таймаут при записи в регистр {address} значение {value}")
                return False
            
            # Проверяем, что запись действительно успешна
            if hasattr(result, 'function_code'):
                logger.info(f"Успешно записано в регистр {address} значение {value}, function_code={result.function_code}")
            else:
                logger.info(f"Успешно записано в регистр {address} значение {value}")
            return True
        except Exception as e:
            error_str = str(e)
            logger.error(f"Исключение при записи в регистр {address} значение {value}: {e}")
            # При ошибке "CLOSING CONNECTION" pymodbus сам закрывает соединение
            # Мы только обновляем флаг, но НЕ закрываем соединение повторно
            if "CLOSING CONNECTION" in error_str:
                logger.warning(f"pymodbus закрыл соединение из-за отсутствия ответа при записи в регистр {address}")
                self._connected = False
                # НЕ закрываем соединение - pymodbus уже закрыл его
                # Проверяем реальное состояние сокета
                try:
                    if self.client is not None and not self.client.is_socket_open():
                        self.client = None
                except:
                    pass
            # Не помечаем как отключенное при обычных таймаутах - соединение может быть еще открыто
            elif "No response" in error_str or "timeout" in error_str.lower():
                logger.warning(f"Таймаут при записи в регистр {address} (соединение может быть еще открыто)")
                # При таймауте НЕ закрываем соединение - оно может быть еще активным
            return False
    
    def read_input_register(self, address: int) -> Optional[int]:
        """
        Чтение input register (для параметров типа '+')
        
        Args:
            address: Адрес регистра
            
        Returns:
            Значение регистра или None в случае ошибки
        """
        # Проверяем соединение, но не блокируем чтение если сокет открыт
        if self.client is None:
            logger.warning("Клиент не инициализирован")
            return None
        if not self.client.is_socket_open():
            logger.debug(f"Сокет закрыт при чтении input регистра {address}")
            self._connected = False
            return None
        
        try:
            logger.debug(f"Чтение input регистра {address} (0x{address:04X}), unit_id={self.unit_id}")
            # Таймаут устанавливается при создании клиента, не передается в read_input_registers
            result = self.client.read_input_registers(
                address, 
                count=1, 
                device_id=self.unit_id
            )
            if result.isError():
                error_str = str(result)
                if "No response" in error_str or "timeout" in error_str.lower():
                    logger.debug(f"Таймаут при чтении input регистра {address}")
                else:
                    logger.error(f"Ошибка чтения input регистра {address}: {result}")
                return None
            value = result.registers[0] if result.registers else None
            logger.info(f"Прочитано из input регистра {address} (0x{address:04X}): значение = {value}")
            return value
        except Exception as e:
            error_str = str(e)
            # При ошибке "CLOSING CONNECTION" pymodbus сам закрывает соединение
            # Мы только обновляем флаг, но НЕ закрываем соединение повторно
            if "CLOSING CONNECTION" in error_str:
                logger.debug(f"pymodbus закрыл соединение из-за отсутствия ответа при чтении input регистра {address}")
                try:
                    if self.client is not None and not self.client.is_socket_open():
                        self._connected = False
                except:
                    self._connected = False
            elif "No response" in error_str or "timeout" in error_str.lower():
                logger.debug(f"Таймаут при чтении input регистра {address} (соединение может быть еще открыто)")
                # При таймауте НЕ закрываем соединение - оно может быть еще активным
            else:
                logger.error(f"Исключение при чтении input регистра {address}: {e}")
            return None
    
    def _crc16_modbus(self, data: bytes) -> int:
        """Расчет CRC16 для Modbus RTU"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return crc
    
    def _build_read_frame_1021(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1021 (функция 04)"""
        address = 1021
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _build_write_frame_1021(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1021 (функция 06)"""
        address = 1021
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        frame = bytes([self.unit_id, 6, addr_high, addr_low, value_high, value_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1021(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1021"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.warning(f"CRC не совпадает для регистра 1021: получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            return None  # Не возвращаем некорректные данные
    
    def read_register_1021_direct(self) -> Optional[int]:
        """Чтение регистра 1021 через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1021")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1021()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1021(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1021 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1021 через прямой сокет: {e}")
            return None
    
    def write_register_1021_direct(self, value: int) -> bool:
        """Запись в регистр 1021 через прямой сокет (функция 06)
        
        Args:
            value: Полное значение для записи в регистр
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1021")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1021(value)
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи
                    resp = sock.recv(256)
                    if resp and len(resp) >= 8:
                        # Проверяем, что ответ соответствует запросу
                        if resp[0] == self.unit_id and resp[1] == 6:
                            success = True
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1021 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1021 через прямой сокет: {e}")
            return False
    
    def set_relay_1021(self, relay_num: int, state: bool) -> bool:
        """Установка состояния реле в регистре 1021
        
        Args:
            relay_num: Номер реле (1-8)
            state: True - включить, False - выключить
        
        Returns:
            True если успешно, False в противном случае
        """
        if relay_num < 1 or relay_num > 8:
            logger.error(f"Номер реле должен быть от 1 до 8, получен {relay_num}")
            return False
        
        # Читаем текущее состояние
        current_value = self.read_register_1021_direct()
        if current_value is None:
            logger.error("Не удалось прочитать текущее состояние регистра 1021")
            return False
        
        current_low_byte = current_value & 0xFF
        bit_position = relay_num - 1  # Реле 1 -> бит 0
        
        if state:
            # Включаем реле - устанавливаем бит
            new_low_byte = current_low_byte | (1 << bit_position)
        else:
            # Выключаем реле - сбрасываем бит
            new_low_byte = current_low_byte & ~(1 << bit_position)
        
        # Формируем новое значение (старший байт оставляем как есть)
        new_value = (current_value & 0xFF00) | new_low_byte
        
        # Записываем новое значение
        return self.write_register_1021_direct(new_value)
    
    def _build_read_frame_1111(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1111 (функция 04)"""
        address = 1111
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _build_write_frame_1111(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1111 (функция 06)"""
        address = 1111
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        frame = bytes([self.unit_id, 6, addr_high, addr_low, value_high, value_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1111(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1111"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.warning(f"CRC не совпадает для регистра 1111: получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            return None  # Не возвращаем некорректные данные
    
    def read_register_1111_direct(self) -> Optional[int]:
        """Чтение регистра 1111 через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1111")
                return None
            
            # Устанавливаем таймаут на сокет для чтения
            try:
                sock.settimeout(2.0)  # 2 секунды таймаут
            except Exception:
                pass
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1111()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.05)  # Задержка для стабильности (как в рабочей версии)
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1111(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError, socket.timeout) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1111 не удалась (это нормально): {e}")
                    else:
                        logger.warning(f"Вторая попытка чтения регистра 1111 не удалась: {e}")
                if i < 1:
                    time.sleep(0.1)  # Задержка между попытками
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1111 через прямой сокет: {e}")
            return None
    
    def write_register_1111_direct(self, value: int) -> bool:
        """Запись в регистр 1111 через прямой сокет (функция 06)
        
        Args:
            value: Полное значение для записи в регистр
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1111")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1111(value)
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp and len(resp) >= 8:
                        # Проверяем, что ответ соответствует запросу
                        if resp[0] == self.unit_id and resp[1] == 6:
                            success = True
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1111 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1111 через прямой сокет: {e}")
            return False
    
    def set_valve_1111(self, valve_bit: int, state: bool) -> bool:
        """Установка состояния клапана в регистре 1111
        
        Args:
            valve_bit: Бит клапана (5-11 для X6-X12, нумерация с 0)
            state: True - включить, False - выключить
        
        Returns:
            True если успешно, False в противном случае
        """
        if valve_bit < 5 or valve_bit > 11:
            logger.error(f"Бит клапана должен быть от 5 до 11, получен {valve_bit}")
            return False
        
        # Читаем текущее состояние
        current_value = self.read_register_1111_direct()
        if current_value is None:
            logger.error("Не удалось прочитать текущее состояние регистра 1111")
            return False
        
        if state:
            # Включаем клапан - устанавливаем бит
            new_value = current_value | (1 << valve_bit)
        else:
            # Выключаем клапан - сбрасываем бит
            new_value = current_value & ~(1 << valve_bit)
        
        # Записываем новое значение
        return self.write_register_1111_direct(new_value)
    
    def _build_read_frame_1511(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1511 (функция 04)"""
        address = 1511
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1511(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1511"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.warning(f"CRC не совпадает для регистра 1511: получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            return None  # Не возвращаем некорректные данные
    
    def read_register_1511_direct(self) -> Optional[int]:
        """Чтение регистра 1511 (температура Water Chiller) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1511")
                return None
            
            # Устанавливаем таймаут на сокет для чтения
            try:
                sock.settimeout(2.0)  # 2 секунды таймаут
            except Exception:
                pass
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1511()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.05)  # Задержка для стабильности (как в рабочей версии)
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1511(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError, socket.timeout) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1511 не удалась (это нормально): {e}")
                    else:
                        logger.warning(f"Вторая попытка чтения регистра 1511 не удалась: {e}")
                if i < 1:
                    time.sleep(0.1)  # Задержка между попытками
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1511 через прямой сокет: {e}")
            return None
    
    def _build_write_frame_1531(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1531 (функция 06)"""
        address = 1531
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        frame = bytes([self.unit_id, 6, addr_high, addr_low, value_high, value_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def write_register_1531_direct(self, value: int) -> bool:
        """Запись в регистр 1531 (установка температуры Water Chiller) через прямой сокет (функция 06)
        
        Args:
            value: Значение для записи (температура * 100, например 2300 для 23.00°C)
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1531")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1531(value)
            logger.debug(f"Запись в регистр 1531: отправляем фрейм {write_frame.hex().upper()}")
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        logger.debug(f"Ответ на запись в регистр 1531 (попытка {i+1}): {resp.hex().upper()}")
                        if len(resp) >= 8:
                            # Проверяем, что ответ соответствует запросу
                            if resp[0] == self.unit_id and resp[1] == 6:
                                # Проверяем, что адрес и значение совпадают
                                resp_addr = (resp[2] << 8) | resp[3]
                                resp_value = (resp[4] << 8) | resp[5]
                                if resp_addr == 1531 and resp_value == value:
                                    logger.debug(f"✅ Запись в регистр 1531 подтверждена: адрес={resp_addr}, значение={resp_value}")
                                    success = True
                                    break
                                else:
                                    logger.warning(f"Ответ не соответствует запросу: адрес={resp_addr} (ожидался 1531), значение={resp_value} (ожидалось {value})")
                            else:
                                logger.warning(f"Неожиданный ответ: unit_id={resp[0]}, функция={resp[1]}")
                        else:
                            logger.warning(f"Ответ слишком короткий: {len(resp)} байт")
                    else:
                        logger.warning(f"Пустой ответ на запись в регистр 1531 (попытка {i+1})")
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1531 не удалась (это нормально): {e}")
                    else:
                        logger.error(f"Ошибка при записи в регистр 1531: {e}")
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            if not success:
                logger.error(f"❌ Не удалось записать в регистр 1531 после 2 попыток")
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1531 через прямой сокет: {e}")
            return False
    
    def _build_write_frame_1331(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1331 (функция 06)"""
        address = 1331
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        frame = bytes([self.unit_id, 6, addr_high, addr_low, value_high, value_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def write_register_1331_direct(self, value: int) -> bool:
        """Запись в регистр 1331 (установка температуры Magnet PSU) через прямой сокет (функция 06)
        
        Args:
            value: Значение для записи (температура * 100, например 2300 для 23.00°C)
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1331")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1331(value)
            logger.debug(f"Запись в регистр 1331: отправляем фрейм {write_frame.hex().upper()}")
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        logger.debug(f"Ответ на запись в регистр 1331 (попытка {i+1}): {resp.hex().upper()}")
                        if len(resp) >= 8:
                            # Проверяем, что ответ соответствует запросу
                            if resp[0] == self.unit_id and resp[1] == 6:
                                # Проверяем, что адрес и значение совпадают
                                resp_addr = (resp[2] << 8) | resp[3]
                                resp_value = (resp[4] << 8) | resp[5]
                                if resp_addr == 1331 and resp_value == value:
                                    logger.debug(f"✅ Запись в регистр 1331 подтверждена: адрес={resp_addr}, значение={resp_value}")
                                    success = True
                                    break
                                else:
                                    logger.warning(f"Ответ не соответствует запросу: адрес={resp_addr} (ожидался 1331), значение={resp_value} (ожидалось {value})")
                            else:
                                logger.warning(f"Неожиданный ответ: unit_id={resp[0]}, функция={resp[1]}")
                        else:
                            logger.warning(f"Ответ слишком короткий: {len(resp)} байт")
                    else:
                        logger.warning(f"Пустой ответ на запись в регистр 1331 (попытка {i+1})")
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1331 не удалась (это нормально): {e}")
                    else:
                        logger.error(f"Ошибка при записи в регистр 1331: {e}")
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            if not success:
                logger.error(f"❌ Не удалось записать в регистр 1331 после 2 попыток")
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1331 через прямой сокет: {e}")
            return False
    
    def _build_write_frame_1241(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1241 (функция 06)"""
        address = 1241
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        frame = bytes([self.unit_id, 6, addr_high, addr_low, value_high, value_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def write_register_1241_direct(self, value: int) -> bool:
        """Запись в регистр 1241 (установка температуры Laser PSU) через прямой сокет (функция 06)
        
        Args:
            value: Значение для записи (температура * 100, например 2300 для 23.00°C)
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1241")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1241(value)
            logger.debug(f"Запись в регистр 1241: отправляем фрейм {write_frame.hex().upper()}")
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        logger.debug(f"Ответ на запись в регистр 1241 (попытка {i+1}): {resp.hex().upper()}")
                        if len(resp) >= 8:
                            # Проверяем, что ответ соответствует запросу
                            if resp[0] == self.unit_id and resp[1] == 6:
                                # Проверяем, что адрес и значение совпадают
                                resp_addr = (resp[2] << 8) | resp[3]
                                resp_value = (resp[4] << 8) | resp[5]
                                if resp_addr == 1241 and resp_value == value:
                                    logger.debug(f"✅ Запись в регистр 1241 подтверждена: адрес={resp_addr}, значение={resp_value}")
                                    success = True
                                    break
                                else:
                                    logger.warning(f"Ответ не соответствует запросу: адрес={resp_addr} (ожидался 1241), значение={resp_value} (ожидалось {value})")
                            else:
                                logger.warning(f"Неожиданный ответ: unit_id={resp[0]}, функция={resp[1]}")
                        else:
                            logger.warning(f"Ответ слишком короткий: {len(resp)} байт")
                    else:
                        logger.warning(f"Пустой ответ на запись в регистр 1241 (попытка {i+1})")
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1241 не удалась (это нормально): {e}")
                    else:
                        logger.error(f"Ошибка при записи в регистр 1241: {e}")
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            if not success:
                logger.error(f"❌ Не удалось записать в регистр 1241 после 2 попыток")
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1241 через прямой сокет: {e}")
            return False
    
    def _build_write_frame_1421(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1421 (функция 06)"""
        address = 1421
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        # Формируем фрейм: Unit ID, Function Code, Address High, Address Low, Value High, Value Low
        frame = bytes([self.unit_id, 0x06, addr_high, addr_low, value_high, value_low])
        
        # Вычисляем CRC16
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        
        return frame + bytes([crc_low, crc_high])
    
    def write_register_1421_direct(self, value: int) -> bool:
        """Запись в регистр 1421 (установка температуры SEOP Cell) через прямой сокет (функция 06)
        
        Args:
            value: Значение для записи (температура * 100, например 2300 для 23.00°C)
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            sock = self.client.socket
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1421")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1421(value)
            logger.debug(f"Запись в регистр 1421: отправляем фрейм {write_frame.hex().upper()}")
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.05)
                    resp = sock.recv(256)
                    if resp:
                        logger.debug(f"Ответ на запись в регистр 1421 (попытка {i+1}): {resp.hex().upper()}")
                        if len(resp) >= 8:
                            # Проверяем, что ответ соответствует запросу
                            if resp[0] == self.unit_id and resp[1] == 6:
                                # Проверяем, что адрес и значение совпадают
                                resp_addr = (resp[2] << 8) | resp[3]
                                resp_value = (resp[4] << 8) | resp[5]
                                if resp_addr == 1421 and resp_value == value:
                                    logger.debug(f"✅ Запись в регистр 1421 подтверждена: адрес={resp_addr}, значение={resp_value}")
                                    success = True
                                    break
                                else:
                                    logger.warning(f"Ответ не соответствует запросу: адрес={resp_addr} (ожидался 1421), значение={resp_value} (ожидалось {value})")
                            else:
                                logger.warning(f"Неожиданный ответ: unit_id={resp[0]}, функция={resp[1]}")
                        else:
                            logger.warning(f"Ответ слишком короткий: {len(resp)} байт")
                    else:
                        logger.warning(f"Пустой ответ на запись в регистр 1421 (попытка {i+1})")
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1421 не удалась (это нормально): {e}")
                    else:
                        logger.error(f"Ошибка при записи в регистр 1421: {e}")
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            if not success:
                logger.error(f"❌ Не удалось записать в регистр 1421 после 2 попыток")
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1421 через прямой сокет: {e}")
            return False
    
    def _build_read_frame_1411(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1411 (функция 04)"""
        address = 1411
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _build_read_frame_1421(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1421 (функция 04)"""
        address = 1421
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1421(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1421"""
        if len(resp) < 7:
            logger.debug(f"Регистр 1421: ответ слишком короткий: {len(resp)} байт")
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.warning(f"CRC не совпадает для регистра 1421: получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            return None  # Не возвращаем некорректные данные
    
    def _parse_read_response_1411(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1411"""
        if len(resp) < 7:
            logger.debug(f"Регистр 1411: ответ слишком короткий: {len(resp)} байт")
            return None
        
        # Логируем полный ответ для отладки
        hex_resp = ' '.join(f'{b:02X}' for b in resp)
        logger.debug(f"Регистр 1411: полный ответ: {hex_resp}, длина: {len(resp)}")
        
        if resp[0] != self.unit_id:
            logger.warning(f"Регистр 1411: неправильный unit_id: получен {resp[0]}, ожидался {self.unit_id}")
            return None
        
        if resp[1] != 4:
            logger.warning(f"Регистр 1411: неправильная функция: получена {resp[1]}, ожидалась 4")
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        logger.debug(f"Регистр 1411: значение={value} (0x{value:04X}), получен CRC={received_crc:04X}, ожидался={calculated_crc:04X}")
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.warning(f"Регистр 1411: CRC не совпадает - получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            logger.warning(f"  Полный ответ: {hex_resp}, данные для CRC: {' '.join(f'{b:02X}' for b in data_for_crc)}")
            # НЕ возвращаем значение при несовпадении CRC - это может быть неправильный ответ
            return None
    
    def read_register_1411_direct(self) -> Optional[int]:
        """Чтение регистра 1411 (температура SEOP Cell) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1411")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1411()
            hex_frame = ' '.join(f'{b:02X}' for b in read_frame)
            logger.debug(f"Регистр 1411: отправляем запрос: {hex_frame}")
            parsed = None
            
            for i in range(2):
                try:
                    # Очищаем буфер сокета перед отправкой, чтобы избежать чтения старых данных
                    sock.settimeout(0.1)
                    try:
                        while True:
                            sock.recv(256)  # Очищаем буфер
                    except socket.timeout:
                        pass  # Буфер пуст
                    except BlockingIOError:
                        pass  # Нет данных
                    sock.settimeout(2.0)  # Возвращаем нормальный таймаут
                    
                    sock.sendall(read_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи
                    resp = sock.recv(256)
                    if resp:
                        hex_resp = ' '.join(f'{b:02X}' for b in resp)
                        logger.debug(f"Регистр 1411: получен ответ (попытка {i+1}): {hex_resp}, длина: {len(resp)}")
                        parsed = self._parse_read_response_1411(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1411 не удалась (это нормально): {e}")
                    else:
                        raise
                except socket.timeout:
                    logger.debug(f"Таймаут при чтении регистра 1411 (попытка {i+1})")
                    if i == 1:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1411 через прямой сокет: {e}")
            return None
    
    def read_register_1421_direct(self) -> Optional[int]:
        """Чтение регистра 1421 (setpoint SEOP Cell) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1421")
                return None
            
            # Устанавливаем таймаут на сокет для чтения
            try:
                sock.settimeout(2.0)  # 2 секунды таймаут
            except Exception:
                pass
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1421()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.05)  # Задержка для стабильности
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1421(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError, socket.timeout) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1421 не удалась (это нормально): {e}")
                    else:
                        logger.warning(f"Вторая попытка чтения регистра 1421 не удалась: {e}")
                if i < 1:
                    time.sleep(0.1)  # Задержка между попытками
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1421 через прямой сокет: {e}")
            return None
    
    def _build_read_frame_1341(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1341 (функция 04)"""
        address = 1341
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1341(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1341"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.warning(f"CRC не совпадает для регистра 1341: получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            return None  # Не возвращаем некорректные данные
    
    def read_register_1341_direct(self) -> Optional[int]:
        """Чтение регистра 1341 (ток Magnet PSU) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1341")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1341()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1341(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1341 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1341 через прямой сокет: {e}")
            return None
    
    def _build_read_frame_1251(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1251 (функция 04)"""
        address = 1251
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1251(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1251"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.warning(f"CRC не совпадает для регистра 1251: получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            return None  # Не возвращаем некорректные данные
    
    def read_register_1251_direct(self) -> Optional[int]:
        """Чтение регистра 1251 (ток Laser PSU) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1251")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1251()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1251(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1251 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1251 через прямой сокет: {e}")
            return None
    
    def _build_read_frame_1611(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1611 (функция 04)"""
        address = 1611
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1611(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1611"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            # Логируем полный ответ для отладки только на уровне debug
            hex_resp = ' '.join(f'{b:02X}' for b in resp)
            hex_data = ' '.join(f'{b:02X}' for b in data_for_crc)
            logger.debug(f"Регистр 1611: CRC не совпадает - получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            logger.debug(f"  Полный ответ: {hex_resp}, длина: {len(resp)}, данные для CRC: {hex_data}")
            # Не возвращаем некорректные данные при ошибке CRC
            return None
    
    def read_register_1611_direct(self) -> Optional[int]:
        """Чтение регистра 1611 (давление Xenon) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1611")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1611()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        # Логируем полный ответ для отладки
                        hex_resp = ' '.join(f'{b:02X}' for b in resp)
                        logger.debug(f"Регистр 1611: получен ответ (попытка {i+1}): {hex_resp}, длина: {len(resp)}")
                        parsed = self._parse_read_response_1611(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1611 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1611 через прямой сокет: {e}")
            return None
    
    def _build_write_frame_1621(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1621 (функция 06)"""
        address = 1621
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        # Формируем фрейм: Unit ID, Function Code, Address High, Address Low, Value High, Value Low
        frame = bytes([self.unit_id, 0x06, addr_high, addr_low, value_high, value_low])
        
        # Вычисляем CRC16
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        
        return frame + bytes([crc_low, crc_high])
    
    def write_register_1621_direct(self, value: int) -> bool:
        """Запись в регистр 1621 (установка давления Xenon) через прямой сокет (функция 06)
        
        Args:
            value: Значение для записи (давление * 100, например 2300 для 23.00 Torr)
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            sock = self.client.socket
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1621")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1621(value)
            logger.debug(f"Запись в регистр 1621: отправляем фрейм {write_frame.hex().upper()}")
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.05)
                    resp = sock.recv(256)
                    if resp:
                        logger.debug(f"Ответ на запись в регистр 1621 (попытка {i+1}): {resp.hex().upper()}")
                        if len(resp) >= 8:
                            # Проверяем, что ответ соответствует запросу
                            if resp[0] == self.unit_id and resp[1] == 6:
                                # Проверяем, что адрес и значение совпадают
                                resp_addr = (resp[2] << 8) | resp[3]
                                resp_value = (resp[4] << 8) | resp[5]
                                if resp_addr == 1621 and resp_value == value:
                                    logger.debug(f"✅ Запись в регистр 1621 подтверждена: адрес={resp_addr}, значение={resp_value}")
                                    success = True
                                    break
                                else:
                                    logger.warning(f"Ответ не соответствует запросу: адрес={resp_addr} (ожидался 1621), значение={resp_value} (ожидалось {value})")
                            else:
                                logger.warning(f"Неожиданный ответ: unit_id={resp[0]}, функция={resp[1]}")
                        else:
                            logger.warning(f"Ответ слишком короткий: {len(resp)} байт")
                    else:
                        logger.warning(f"Пустой ответ на запись в регистр 1621 (попытка {i+1})")
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1621 не удалась (это нормально): {e}")
                    else:
                        logger.error(f"Ошибка при записи в регистр 1621: {e}")
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            if not success:
                logger.error(f"❌ Не удалось записать в регистр 1621 после 2 попыток")
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1621 через прямой сокет: {e}")
            return False
    
    def _build_write_frame_1661(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1661 (функция 06)"""
        address = 1661
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        frame = bytes([self.unit_id, 6, addr_high, addr_low, value_high, value_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def write_register_1661_direct(self, value: int) -> bool:
        """Запись в регистр 1661 (установка давления N2) через прямой сокет (функция 06)
        
        Args:
            value: Значение для записи (давление * 100, например 2300 для 23.00 Torr)
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1661")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1661(value)
            logger.debug(f"Запись в регистр 1661: отправляем фрейм {write_frame.hex().upper()}")
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        logger.debug(f"Ответ на запись в регистр 1661 (попытка {i+1}): {resp.hex().upper()}")
                        if len(resp) >= 8:
                            # Проверяем, что ответ соответствует запросу
                            if resp[0] == self.unit_id and resp[1] == 6:
                                # Проверяем, что адрес и значение совпадают
                                resp_addr = (resp[2] << 8) | resp[3]
                                resp_value = (resp[4] << 8) | resp[5]
                                if resp_addr == 1661 and resp_value == value:
                                    logger.debug(f"✅ Запись в регистр 1661 подтверждена: адрес={resp_addr}, значение={resp_value}")
                                    success = True
                                    break
                                else:
                                    logger.warning(f"Ответ не соответствует запросу: адрес={resp_addr} (ожидался 1661), значение={resp_value} (ожидалось {value})")
                            else:
                                logger.warning(f"Неожиданный ответ: unit_id={resp[0]}, функция={resp[1]}")
                        else:
                            logger.warning(f"Ответ слишком короткий: {len(resp)} байт")
                    else:
                        logger.warning(f"Пустой ответ на запись в регистр 1661 (попытка {i+1})")
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1661 не удалась (это нормально): {e}")
                    else:
                        logger.error(f"Ошибка при записи в регистр 1661: {e}")
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            if not success:
                logger.error(f"❌ Не удалось записать в регистр 1661 после 2 попыток")
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1661 через прямой сокет: {e}")
            return False
    
    def _build_read_frame_1651(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1651 (функция 04)"""
        address = 1651
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1651(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1651"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            # Логируем полный ответ для отладки только на уровне debug
            hex_resp = ' '.join(f'{b:02X}' for b in resp)
            hex_data = ' '.join(f'{b:02X}' for b in data_for_crc)
            logger.debug(f"Регистр 1651: CRC не совпадает - получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            logger.debug(f"  Полный ответ: {hex_resp}, длина: {len(resp)}, данные для CRC: {hex_data}")
            # Не возвращаем некорректные данные при ошибке CRC
            return None
    
    def read_register_1651_direct(self) -> Optional[int]:
        """Чтение регистра 1651 (давление N2) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1651")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1651()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        # Логируем полный ответ для отладки
                        hex_resp = ' '.join(f'{b:02X}' for b in resp)
                        logger.debug(f"Регистр 1651: получен ответ (попытка {i+1}): {hex_resp}, длина: {len(resp)}")
                        parsed = self._parse_read_response_1651(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1651 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1651 через прямой сокет: {e}")
            return None
    
    def _build_read_frame_1701(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1701 (функция 04)"""
        address = 1701
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1701(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1701"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            # Логируем полный ответ для отладки только на уровне debug
            hex_resp = ' '.join(f'{b:02X}' for b in resp)
            hex_data = ' '.join(f'{b:02X}' for b in data_for_crc)
            logger.debug(f"Регистр 1701: CRC не совпадает - получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            logger.debug(f"  Полный ответ: {hex_resp}, длина: {len(resp)}, данные для CRC: {hex_data}")
            # Не возвращаем некорректные данные при ошибке CRC
            return None
    
    def read_register_1701_direct(self) -> Optional[int]:
        """Чтение регистра 1701 (давление Vacuum) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1701")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1701()
            parsed = None
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1701(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1701 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1701 через прямой сокет: {e}")
            return None
    
    def _build_read_frame_1131(self) -> bytes:
        """Формирование Modbus RTU фрейма для чтения регистра 1131 (функция 04)"""
        address = 1131
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        
        frame = bytes([self.unit_id, 4, addr_high, addr_low, 0x00, 0x01])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _build_write_frame_1131(self, value: int) -> bytes:
        """Формирование Modbus RTU фрейма для записи в регистр 1131 (функция 06)"""
        address = 1131
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        value_high = (value >> 8) & 0xFF
        value_low = value & 0xFF
        
        frame = bytes([self.unit_id, 6, addr_high, addr_low, value_high, value_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])
    
    def _parse_read_response_1131(self, resp: bytes) -> Optional[int]:
        """Расшифровка ответа на запрос чтения регистра 1131"""
        if len(resp) < 7:
            return None
        
        if resp[0] != self.unit_id or resp[1] != 4:
            return None
        
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC
        received_crc = (resp[-1] << 8) | resp[-2]
        data_for_crc = resp[:-2]
        calculated_crc = self._crc16_modbus(data_for_crc)
        
        if received_crc == calculated_crc:
            return value
        else:
            logger.debug(f"Регистр 1131: CRC не совпадает - получен {received_crc:04X}, ожидался {calculated_crc:04X}")
            return None  # Не возвращаем некорректные данные
    
    def read_register_1131_direct(self) -> Optional[int]:
        """Чтение регистра 1131 (fans) через прямой сокет (функция 04)"""
        if self.client is None or not self.client.is_socket_open():
            return None
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямого чтения регистра 1131")
                return None
            
            # Отправляем запрос дважды (первый может потеряться)
            read_frame = self._build_read_frame_1131()
            parsed = None
            
            # Устанавливаем таймаут на сокет для чтения
            try:
                sock.settimeout(2.0)  # 2 секунды таймаут
            except Exception:
                pass
            
            for i in range(2):
                try:
                    sock.sendall(read_frame)
                    time.sleep(0.05)  # Задержка для стабильности (как в рабочей версии)
                    resp = sock.recv(256)
                    if resp:
                        parsed = self._parse_read_response_1131(resp)
                        if parsed is not None:
                            break
                except (ConnectionError, OSError, socket.timeout) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка чтения регистра 1131 не удалась (это нормально): {e}")
                    else:
                        logger.warning(f"Вторая попытка чтения регистра 1131 не удалась: {e}")
                if i < 1:
                    time.sleep(0.1)  # Задержка между попытками
            
            return parsed
        except Exception as e:
            logger.error(f"Ошибка при чтении регистра 1131 через прямой сокет: {e}")
            return None
    
    def write_register_1131_direct(self, value: int) -> bool:
        """Запись в регистр 1131 через прямой сокет (функция 06)
        
        Args:
            value: Полное значение для записи в регистр
        """
        if self.client is None or not self.client.is_socket_open():
            return False
        
        try:
            # Получаем сокет из pymodbus клиента
            sock = None
            if hasattr(self.client, 'socket') and self.client.socket:
                sock = self.client.socket
            elif hasattr(self.client, 'transport'):
                transport = self.client.transport
                if hasattr(transport, 'socket') and transport.socket:
                    sock = transport.socket
                elif hasattr(transport, '_socket') and transport._socket:
                    sock = transport._socket
                elif hasattr(transport, 'sock') and transport.sock:
                    sock = transport.sock
                elif hasattr(transport, '_sock') and transport._sock:
                    sock = transport._sock
            
            if sock is None:
                logger.warning("Не удалось получить сокет для прямой записи в регистр 1131")
                return False
            
            # Отправляем запрос дважды
            write_frame = self._build_write_frame_1131(value)
            success = False
            
            for i in range(2):
                try:
                    sock.sendall(write_frame)
                    time.sleep(0.01)  # Минимальная задержка для быстрой записи для избежания блокировки UI
                    resp = sock.recv(256)
                    if resp and len(resp) >= 8:
                        # Проверяем, что ответ соответствует запросу
                        if resp[0] == self.unit_id and resp[1] == 6:
                            success = True
                            break
                except (ConnectionError, OSError) as e:
                    if i == 0:
                        logger.debug(f"Первая попытка записи в регистр 1131 не удалась (это нормально): {e}")
                    else:
                        raise
                if i < 1:
                    time.sleep(0.05)  # Минимальная задержка между попытками для быстрой записи
            
            return success
        except Exception as e:
            logger.error(f"Ошибка при записи в регистр 1131 через прямой сокет: {e}")
            return False
    
    def set_fan_1131(self, fan_bit: int, state: bool) -> bool:
        """Установка состояния вентилятора в регистре 1131
        
        Args:
            fan_bit: Бит вентилятора (0-9 для обычных fans, 16-17 для laser fan)
            state: True - включить, False - выключить
        
        Returns:
            True если успешно, False в противном случае
        """
        # Пробуем сначала использовать стандартный метод pymodbus
        current_value = None
        try:
            if self.client is not None and self.client.is_socket_open():
                result = self.client.read_input_registers(1131, count=1, device_id=self.unit_id)
                if not result.isError() and result.registers:
                    current_value = result.registers[0]
                    logger.debug(f"Регистр 1131 прочитан через pymodbus: {current_value}")
        except Exception as e:
            logger.debug(f"Не удалось прочитать регистр 1131 через pymodbus: {e}")
        
        # Если стандартный метод не сработал, пробуем прямой сокет
        if current_value is None:
            current_value = self.read_register_1131_direct()
        
        if current_value is None:
            logger.error("Не удалось прочитать текущее состояние регистра 1131")
            return False
        
        if state:
            # Включаем вентилятор - устанавливаем бит
            new_value = current_value | (1 << fan_bit)
        else:
            # Выключаем вентилятор - сбрасываем бит
            new_value = current_value & ~(1 << fan_bit)
        
        # Записываем новое значение
        return self.write_register_1131_direct(new_value)

    # ===== Generic direct multi-read (IR/NMR) =====
    def _get_underlying_socket(self):
        """
        Возвращает реальный socket из pymodbus клиента (если возможно).
        """
        if self.client is None:
            return None
        if hasattr(self.client, 'socket') and self.client.socket:
            return self.client.socket
        if hasattr(self.client, 'transport'):
            transport = self.client.transport
            for attr in ('socket', '_socket', 'sock', '_sock'):
                if hasattr(transport, attr):
                    s = getattr(transport, attr)
                    if s:
                        return s
            if hasattr(transport, 'get_socket'):
                try:
                    return transport.get_socket()
                except Exception:
                    return None
        return None

    def _build_read_frame_generic(self, function: int, address: int, quantity: int) -> bytes:
        """Формирование Modbus RTU фрейма для чтения (обычно функция 04)"""
        addr_high = (address >> 8) & 0xFF
        addr_low = address & 0xFF
        qty_high = (quantity >> 8) & 0xFF
        qty_low = quantity & 0xFF
        frame = bytes([self.unit_id, function, addr_high, addr_low, qty_high, qty_low])
        crc = self._crc16_modbus(frame)
        crc_low = crc & 0xFF
        crc_high = (crc >> 8) & 0xFF
        return frame + bytes([crc_low, crc_high])

    def _find_frame_start(self, data: bytes, function: int) -> int:
        """
        В ответах иногда может быть мусор в начале; ищем unit_id + function.
        """
        if not data:
            return 0
        for i in range(max(0, len(data) - 4)):
            if data[i] == self.unit_id and (data[i + 1] == function or data[i + 1] == (function | 0x80)):
                return i
        return 0

    def _parse_read_multiple_response(self, resp: bytes, function: int) -> Optional[list]:
        """
        Парсинг ответа Modbus RTU (function 04) на чтение нескольких регистров.
        Возвращает список uint16 значений или None при ошибке.
        """
        if not resp or len(resp) < 5:
            return None

        start_idx = self._find_frame_start(resp, function)
        if start_idx > 0:
            resp = resp[start_idx:]

        if len(resp) < 5:
            return None

        unit_id = resp[0]
        fn = resp[1]
        if unit_id != self.unit_id:
            return None

        # Modbus exception response
        if fn & 0x80:
            exc_code = resp[2] if len(resp) > 2 else None
            logger.warning(f"Modbus exception response: function={fn & 0x7F} code={exc_code}")
            return None

        if fn != function:
            return None

        byte_count = resp[2]
        expected_len = 3 + byte_count + 2
        if len(resp) < expected_len:
            # Обрезанный ответ — лучше считать ошибкой
            return None

        received_crc = (resp[expected_len - 1] << 8) | resp[expected_len - 2]
        calculated_crc = self._crc16_modbus(resp[: expected_len - 2])
        if received_crc != calculated_crc:
            logger.warning(
                f"CRC mismatch: got=0x{received_crc:04X} expected=0x{calculated_crc:04X} (addr multi-read)"
            )
            return None

        registers = []
        data = resp[3 : 3 + byte_count]
        for i in range(0, len(data), 2):
            if i + 1 >= len(data):
                break
            registers.append((data[i] << 8) | data[i + 1])
        return registers

    def read_input_registers_direct(self, address: int, quantity: int, *, max_chunk: int = 10) -> Optional[list]:
        """
        Чтение input registers (function 04) через прямой сокет.

        Важно: устройство может "ронять" сокет при больших запросах, поэтому по умолчанию
        читаем чанками по 10 регистров.
        """
        if quantity <= 0:
            return []
        if self.client is None or not self.client.is_socket_open():
            self._connected = False
            return None

        sock = self._get_underlying_socket()
        if sock is None:
            logger.warning("Не удалось получить сокет для direct multi-read")
            return None

        # Читаем чанками по max_chunk
        out: list[int] = []
        remaining = quantity
        current_addr = address

        # Используем чуть более длинный timeout на время пакетного чтения
        prev_timeout = None
        try:
            try:
                prev_timeout = sock.gettimeout()
            except Exception:
                prev_timeout = None
            try:
                sock.settimeout(0.5)
            except Exception:
                pass

            while remaining > 0:
                chunk = min(max_chunk, remaining)
                frame = self._build_read_frame_generic(4, current_addr, chunk)

                parsed = None
                for attempt in range(2):
                    try:
                        sock.sendall(frame)
                        time.sleep(0.01)  # аккуратная подача команд

                        resp = b""
                        # Собираем ответ до полного фрейма
                        deadline = time.time() + 0.5
                        while time.time() < deadline:
                            try:
                                part = sock.recv(512)
                            except socket.timeout:
                                break
                            if not part:
                                break
                            resp += part
                            # Если есть заголовок — можно понять ожидаемую длину
                            start_idx = self._find_frame_start(resp, 4)
                            frame_start = resp[start_idx:]
                            if len(frame_start) >= 3:
                                bc = frame_start[2]
                                need = 3 + bc + 2
                                if len(frame_start) >= need:
                                    break

                        parsed = self._parse_read_multiple_response(resp, 4)
                        if parsed is not None and len(parsed) >= chunk:
                            parsed = parsed[:chunk]
                            break
                    except (ConnectionError, OSError, socket.timeout) as e:
                        # первая попытка может не удаться — повторяем один раз
                        if attempt == 1:
                            logger.warning(f"Direct multi-read failed at addr={current_addr} qty={chunk}: {e}")
                        time.sleep(0.02)

                if parsed is None:
                    # Если не удалось прочитать — считаем, что соединение нестабильно
                    self._connected = False
                    return None

                out.extend(parsed)
                current_addr += chunk
                remaining -= chunk
                time.sleep(0.01)

            return out
        finally:
            if prev_timeout is not None:
                try:
                    sock.settimeout(prev_timeout)
                except Exception:
                    pass

