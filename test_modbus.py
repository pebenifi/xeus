#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket, time

IP   = "192.168.4.1"
PORT = 503
UNIT_ID = 1

def hex_dump(label, data: bytes):
    print(f"{label}: {' '.join(f'{b:02X}' for b in data)}")

def crc16_modbus(data: bytes) -> int:
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

def build_read_frame(function: int, address: int, unit_id: int = UNIT_ID) -> bytes:
    """Формирование Modbus RTU фрейма для чтения (функция 04)"""
    # Адрес регистра в байтах (старший и младший)
    addr_high = (address >> 8) & 0xFF
    addr_low = address & 0xFF
    
    # Количество регистров для чтения (1 регистр)
    quantity = 1
    qty_high = (quantity >> 8) & 0xFF
    qty_low = quantity & 0xFF
    
    # Формируем фрейм без CRC
    frame = bytes([unit_id, function, addr_high, addr_low, qty_high, qty_low])
    
    # Добавляем CRC16
    crc = crc16_modbus(frame)
    crc_low = crc & 0xFF
    crc_high = (crc >> 8) & 0xFF
    
    return frame + bytes([crc_low, crc_high])

def build_read_multiple_registers_frame(function: int, address: int, quantity: int, unit_id: int = UNIT_ID) -> bytes:
    """Формирование Modbus RTU фрейма для чтения нескольких регистров (функция 04)"""
    # Адрес регистра в байтах (старший и младший)
    addr_high = (address >> 8) & 0xFF
    addr_low = address & 0xFF
    
    # Количество регистров для чтения
    qty_high = (quantity >> 8) & 0xFF
    qty_low = quantity & 0xFF
    
    # Формируем фрейм без CRC
    frame = bytes([unit_id, function, addr_high, addr_low, qty_high, qty_low])
    
    # Добавляем CRC16
    crc = crc16_modbus(frame)
    crc_low = crc & 0xFF
    crc_high = (crc >> 8) & 0xFF
    
    return frame + bytes([crc_low, crc_high])

def build_write_frame(function: int, address: int, value: int, unit_id: int = UNIT_ID) -> bytes:
    """Формирование Modbus RTU фрейма для записи (функция 06)"""
    # Адрес регистра в байтах (старший и младший)
    addr_high = (address >> 8) & 0xFF
    addr_low = address & 0xFF
    
    # Значение для записи (2 байта)
    value_high = (value >> 8) & 0xFF
    value_low = value & 0xFF
    
    # Формируем фрейм без CRC
    frame = bytes([unit_id, function, addr_high, addr_low, value_high, value_low])
    
    # Добавляем CRC16
    crc = crc16_modbus(frame)
    crc_low = crc & 0xFF
    crc_high = (crc >> 8) & 0xFF
    
    return frame + bytes([crc_low, crc_high])

def connect_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    s.connect((IP, PORT))
    return s

def parse_read_response(resp: bytes) -> dict:
    """Расшифровка ответа на запрос чтения (функция 04)"""
    if len(resp) < 5:
        return None
    
    unit_id = resp[0]
    function = resp[1]
    byte_count = resp[2]
    
    if function != 4:
        return None
    
    # Извлекаем значение регистра (2 байта)
    if byte_count >= 2 and len(resp) >= 5:
        value_high = resp[3]
        value_low = resp[4]
        value = (value_high << 8) | value_low
        
        # Проверяем CRC (последние 2 байта)
        if len(resp) >= 7:
            received_crc = (resp[-1] << 8) | resp[-2]  # CRC в little-endian
            data_for_crc = resp[:-2]  # Все кроме CRC
            calculated_crc = crc16_modbus(data_for_crc)
            
            return {
                'unit_id': unit_id,
                'function': function,
                'byte_count': byte_count,
                'value': value,
                'value_hex': f"0x{value:04X}",
                'crc_valid': received_crc == calculated_crc,
                'received_crc': f"0x{received_crc:04X}",
                'calculated_crc': f"0x{calculated_crc:04X}"
            }
    
    return None

def find_modbus_frame_start(data: bytes) -> int:
    """Находит начало Modbus фрейма в данных (может быть мусор в начале)"""
    # Ищем паттерн: unit_id (обычно 01) + функция (04 для чтения, 84 для ошибки)
    for i in range(len(data) - 4):
        if data[i] == UNIT_ID and (data[i+1] == 4 or data[i+1] == 0x84):
            return i
    return 0  # Если не нашли, возвращаем 0

def parse_modbus_error(resp: bytes) -> dict:
    """Парсинг ответа с ошибкой Modbus"""
    if len(resp) < 5:
        return None
    
    unit_id = resp[0]
    function = resp[1]
    
    # Если функция с установленным битом ошибки (0x80)
    if function & 0x80:
        error_code = resp[2]
        error_messages = {
            1: "Illegal Function",
            2: "Illegal Data Address",
            3: "Illegal Data Value",
            4: "Slave Device Failure",
            5: "Acknowledge",
            6: "Slave Device Busy",
            8: "Memory Parity Error"
        }
        error_msg = error_messages.get(error_code, f"Unknown error ({error_code})")
        
        # Проверяем CRC
        if len(resp) >= 5:
            received_crc = (resp[-1] << 8) | resp[-2]
            data_for_crc = resp[:-2]
            calculated_crc = crc16_modbus(data_for_crc)
            
            return {
                'is_error': True,
                'unit_id': unit_id,
                'function': function & 0x7F,  # Убираем бит ошибки
                'error_code': error_code,
                'error_message': error_msg,
                'crc_valid': received_crc == calculated_crc
            }
    
    return None

def parse_multiple_registers_response(resp: bytes) -> dict:
    """Расшифровка ответа на запрос чтения нескольких регистров (функция 04)"""
    if len(resp) < 5:
        return None
    
    # Находим начало фрейма (может быть мусор в начале)
    start_idx = find_modbus_frame_start(resp)
    if start_idx > 0:
        print(f"⚠️  Найден мусор в начале ответа ({start_idx} байт), пропускаем...")
        resp = resp[start_idx:]
    
    if len(resp) < 5:
        return None
    
    # Сначала проверяем на ошибку
    error = parse_modbus_error(resp)
    if error:
        return error
    
    unit_id = resp[0]
    function = resp[1]
    
    if function != 4:
        return None
    
    byte_count = resp[2]
    
    # Проверяем минимальную длину ответа
    # Заголовок: 3 байта (unit_id, function, byte_count)
    # Данные: byte_count байт
    # CRC: 2 байта
    min_length = 3 + byte_count + 2
    if len(resp) < min_length:
        print(f"⚠️  Ответ обрезан: получено {len(resp)} байт, ожидалось минимум {min_length}")
        # Пробуем обработать то, что есть
        available_bytes = len(resp) - 5  # -3 для заголовка, -2 для CRC
        if available_bytes < 0:
            return None
        byte_count = min(byte_count, available_bytes)
    
    # Извлекаем все регистры
    registers = []
    for i in range(0, byte_count, 2):
        data_idx = 3 + i
        if data_idx + 1 < len(resp) - 2:  # Убеждаемся, что есть оба байта и место для CRC
            value_high = resp[data_idx]
            value_low = resp[data_idx + 1]
            value = (value_high << 8) | value_low
            registers.append(value)
    
    # Проверяем CRC (последние 2 байта)
    if len(resp) >= 5:
        received_crc = (resp[-1] << 8) | resp[-2]  # CRC в little-endian
        data_for_crc = resp[:-2]  # Все кроме CRC
        calculated_crc = crc16_modbus(data_for_crc)
        
        return {
            'unit_id': unit_id,
            'function': function,
            'byte_count': byte_count,
            'registers': registers,
            'register_count': len(registers),
            'crc_valid': received_crc == calculated_crc,
            'received_crc': f"0x{received_crc:04X}",
            'calculated_crc': f"0x{calculated_crc:04X}"
        }
    
    return None

def registers_to_float(registers: list, index: int) -> float:
    """Преобразование двух регистров (uint16) в float (IEEE 754)"""
    if index + 1 >= len(registers):
        return 0.0
    
    # Объединяем два регистра в 32-битное значение
    high = registers[index]
    low = registers[index + 1]
    combined = (high << 16) | low
    
    # Преобразуем в float
    import struct
    # Преобразуем uint32 в bytes (big-endian)
    bytes_val = struct.pack('>I', combined)
    # Преобразуем bytes в float
    float_val = struct.unpack('>f', bytes_val)[0]
    
    return float_val

def read_ir_data(sock):
    """Чтение всех IR данных за один раз
    
    Читает регистры:
    - 400: статус/флаг
    - 401-402: x min (float)
    - 403-404: x max (float)
    - 405-406: y min (float)
    - 407-408: y max (float)
    - 409-410: res_freq (float)
    - 411-412: freq (float)
    - 413-414: integral (float)
    - 420-477: data (ushort) - 58 регистров
    
    Всего: от 400 до 477 включительно = 78 регистров
    """
    print(f"\n=== Чтение IR данных ===")
    
    # Разбиваем на несколько запросов, так как 78 регистров может быть слишком много
    # Максимум обычно 125 регистров, но для надежности разобьем на части
    
    # Пробуем разные варианты адресации
    # В Modbus адресация может быть 0-based или 1-based
    # Также возможно, что регистры начинаются не с 400
    
    # Варианты для проверки (если первый не сработает)
    address_variants = [400, 399, 0]  # 400, 399 (0-based), 0 (относительная адресация)
    
    # Читаем регистры частями
    # Согласно описанию:
    # - 400-414: метаданные (15 регистров)
    # - 420-477: данные (58 регистров)
    # Между 414 и 420 есть пропуск!
    read_ranges = [
        (0, 15),      # 0-14 (15 регистров) - метаданные (400-414)
        (20, 58),     # 20-77 (58 регистров) - данные (420-477)
    ]
    
    # Пробуем первый вариант адресации
    address_base = address_variants[0]
    print(f"Попытка чтения с базовым адресом {address_base}...")
    
    # Словарь для хранения прочитанных регистров по их реальным адресам
    registers_dict = {}
    
    for start_offset, quantity in read_ranges:
        start_addr = address_base + start_offset
        print(f"Чтение регистров {start_addr}-{start_addr + quantity - 1} ({quantity} регистров)...")
        
        frame = build_read_multiple_registers_frame(4, start_addr, quantity)
        
        try:
            hex_dump("TX", frame)
            sock.sendall(frame)
            
            time.sleep(0.1)
            
            # Читаем ответ с таймаутом
            resp = b''
            try:
                # Читаем все доступные данные
                sock.settimeout(0.5)
                while True:
                    chunk = sock.recv(512)
                    if not chunk:
                        break
                    resp += chunk
                    # Если получили достаточно данных, проверяем, не закончился ли фрейм
                    if len(resp) >= 5:
                        # Проверяем, есть ли полный фрейм
                        start_idx = find_modbus_frame_start(resp)
                        if start_idx >= 0:
                            frame_start = resp[start_idx:]
                            if len(frame_start) >= 3:
                                byte_count = frame_start[2]
                                expected_length = 3 + byte_count + 2
                                if len(frame_start) >= expected_length:
                                    # Полный фрейм получен
                                    break
            except socket.timeout:
                pass  # Таймаут - возможно, все данные уже получены
            finally:
                sock.settimeout(2.0)  # Возвращаем обычный таймаут
            
            if resp:
                hex_dump("RX", resp)
                
                parsed = parse_multiple_registers_response(resp)
                if not parsed:
                    print("Ошибка: не удалось распарсить ответ")
                    print(f"   Длина ответа: {len(resp)} байт")
                    start_idx = find_modbus_frame_start(resp)
                    if start_idx >= 0 and start_idx < len(resp):
                        print(f"   Начало фрейма на позиции: {start_idx}")
                        if len(resp) > start_idx + 2:
                            print(f"   Unit ID: {resp[start_idx]:02X}, Function: {resp[start_idx+1]:02X}, Byte count: {resp[start_idx+2]}")
                            byte_count = resp[start_idx+2]
                            expected_length = start_idx + 3 + byte_count + 2
                            print(f"   Ожидаемая длина: {expected_length} байт, получено: {len(resp)} байт")
                    return None
                
                # Проверяем на ошибку Modbus
                if parsed.get('is_error'):
                    error_msg = parsed['error_message']
                    error_code = parsed['error_code']
                    print(f"❌ Ошибка Modbus: {error_msg} (код {error_code})")
                    print(f"   Функция: {parsed['function']:02d}")
                    print(f"   Адрес: {start_addr}")
                    
                    # Если это ошибка адреса, пробуем другие варианты
                    if error_code == 2 and address_base == address_variants[0]:
                        print(f"\n⚠️  Пробуем альтернативный адрес...")
                        # Пробуем адрес 399 (0-based адресация)
                        address_base = address_variants[1]
                        print(f"Повторная попытка с базовым адресом {address_base}...")
                        registers_dict = {}  # Сбрасываем накопленные данные
                        # Перезапускаем цикл с новым адресом
                        for retry_offset, retry_quantity in read_ranges:
                            retry_addr = address_base + retry_offset
                            print(f"Чтение регистров {retry_addr}-{retry_addr + retry_quantity - 1} ({retry_quantity} регистров)...")
                            retry_frame = build_read_multiple_registers_frame(4, retry_addr, retry_quantity)
                            hex_dump("TX", retry_frame)
                            sock.sendall(retry_frame)
                            time.sleep(0.1)
                            retry_resp = sock.recv(512)
                            if retry_resp:
                                hex_dump("RX", retry_resp)
                                retry_parsed = parse_multiple_registers_response(retry_resp)
                                if retry_parsed and not retry_parsed.get('is_error'):
                                    retry_registers = retry_parsed.get('registers', [])
                                    # Сохраняем регистры в словарь по их реальным адресам
                                    for j, reg_value in enumerate(retry_registers):
                                        real_addr = retry_addr + j
                                        registers_dict[real_addr] = reg_value
                                    print(f"✓ Прочитано {len(retry_registers)} регистров")
                                else:
                                    print(f"❌ Ошибка при чтении регистров {retry_addr}")
                                    return None
                        break  # Выходим из основного цикла, так как уже прочитали все
                    else:
                        return None
                
                if not parsed.get('crc_valid', True):
                    print(f"⚠️  Предупреждение: CRC не валиден!")
                
                registers = parsed.get('registers', [])
                if len(registers) < quantity:
                    print(f"⚠️  Предупреждение: получено только {len(registers)} регистров вместо {quantity}")
                    return None
                
                # Сохраняем регистры в словарь по их реальным адресам
                for i, reg_value in enumerate(registers):
                    real_addr = start_addr + i
                    registers_dict[real_addr] = reg_value
                
                print(f"✓ Прочитано {len(registers)} регистров")
                
            else:
                print("RX: (empty)")
                return None
        except socket.timeout:
            print("RX: (timeout)")
            return None
        except (ConnectionError, OSError) as e:
            print(f"Ошибка соединения: {e}")
            return None
    
    # Проверяем, что получили все необходимые регистры
    # Нужно: 15 регистров (400-414) + 58 регистров (420-477) = 73 регистра
    expected_count = 15 + 58  # 73 регистра
    if len(registers_dict) < expected_count:
        print(f"❌ Ошибка: получено только {len(registers_dict)} регистров вместо {expected_count}")
        return None
    
    # Создаем полный массив с пропуском между 414 и 420
    # Индексы: 0-14 (400-414), затем пропуск 15-19, затем 20-77 (420-477)
    full_registers = [0] * 78  # 400-477 включительно = 78 регистров
    # Заполняем первые 15 регистров (400-414)
    for i in range(400, 415):
        if i in registers_dict:
            full_registers[i - 400] = registers_dict[i]
    # Заполняем регистры 420-477 (индексы 20-77 в полном массиве)
    for i in range(420, 478):
        if i in registers_dict:
            full_registers[i - 400] = registers_dict[i]
    
    # Используем full_registers
    all_registers = full_registers
    
    try:
            
        # Извлекаем данные
        result = {
            'status': all_registers[0],  # регистр 400
            'x_min': registers_to_float(all_registers, 1),  # регистры 401-402
            'x_max': registers_to_float(all_registers, 3),  # регистры 403-404
            'y_min': registers_to_float(all_registers, 5),  # регистры 405-406
            'y_max': registers_to_float(all_registers, 7),  # регистры 407-408
            'res_freq': registers_to_float(all_registers, 9),  # регистры 409-410
            'freq': registers_to_float(all_registers, 11),  # регистры 411-412
            'integral': registers_to_float(all_registers, 13),  # регистры 413-414
            'data': all_registers[20:78]  # регистры 420-477 (индекс 20-77 в массиве)
        }
            
        # Выводим результаты
        print(f"\n✓ Все данные успешно прочитаны!")
        print(f"\nРезультаты:")
        print(f"  Статус (400): {result['status']} (0x{result['status']:04X})")
        print(f"  X min (401-402): {result['x_min']:.6f}")
        print(f"  X max (403-404): {result['x_max']:.6f}")
        print(f"  Y min (405-406): {result['y_min']:.6f}")
        print(f"  Y max (407-408): {result['y_max']:.6f}")
        print(f"  Res freq (409-410): {result['res_freq']:.6f}")
        print(f"  Freq (411-412): {result['freq']:.6f}")
        print(f"  Integral (413-414): {result['integral']:.6f}")
        print(f"  Data (420-477): {len(result['data'])} значений")
        print(f"    Первые 10 значений: {result['data'][:10]}")
        print(f"    Последние 10 значений: {result['data'][-10:]}")
        
        return result
    except Exception as e:
        print(f"❌ Ошибка при обработке данных: {e}")
        return None

def parse_write_response(resp: bytes) -> dict:
    """Расшифровка ответа на запрос записи (функция 06)"""
    if len(resp) < 8:
        return None
    
    unit_id = resp[0]
    function = resp[1]
    
    if function != 6:
        return None
    
    # Извлекаем адрес и значение
    addr_high = resp[2]
    addr_low = resp[3]
    address = (addr_high << 8) | addr_low
    
    value_high = resp[4]
    value_low = resp[5]
    value = (value_high << 8) | value_low
    
    # Проверяем CRC (последние 2 байта)
    if len(resp) >= 8:
        received_crc = (resp[-1] << 8) | resp[-2]  # CRC в little-endian
        data_for_crc = resp[:-2]  # Все кроме CRC
        calculated_crc = crc16_modbus(data_for_crc)
        
        return {
            'unit_id': unit_id,
            'function': function,
            'address': address,
            'value': value,
            'value_hex': f"0x{value:04X}",
            'crc_valid': received_crc == calculated_crc,
            'received_crc': f"0x{received_crc:04X}",
            'calculated_crc': f"0x{calculated_crc:04X}"
        }
    
    return None

def send_frame(sock, frame: bytes, is_write: bool = False, return_parsed: bool = False):
    """Отправка фрейма и получение ответа
    
    Args:
        sock: Сокет
        frame: Фрейм для отправки
        is_write: True если это запись, False если чтение
        return_parsed: Если True, возвращает распарсенный ответ вместо вывода
    
    Returns:
        dict или None - распарсенный ответ, если return_parsed=True
    """
    try:
        hex_dump("TX", frame)
        sock.sendall(frame)
        
        time.sleep(0.1)
        
        try:
            resp = sock.recv(256)
            if resp:
                hex_dump("RX", resp)
                
                if is_write:
                    # Расшифровываем ответ на запись
                    parsed = parse_write_response(resp)
                    if return_parsed:
                        return parsed
                    if parsed:
                        print(f"\n  Расшифровка ответа:")
                        print(f"    Unit ID: {parsed['unit_id']}")
                        print(f"    Функция: {parsed['function']:02d} (Write Single Register)")
                        print(f"    Адрес регистра: {parsed['address']}")
                        print(f"    Записанное значение: {parsed['value']} (десятичное)")
                        print(f"    Записанное значение: {parsed['value_hex']} (шестнадцатеричное)")
                        
                        # Бинарное представление
                        low_byte = parsed['value'] & 0xFF
                        high_byte = (parsed['value'] >> 8) & 0xFF
                        binary_low = format(low_byte, '08b')
                        binary_high = format(high_byte, '08b')
                        print(f"    Младший байт: {low_byte} (0x{low_byte:02X}) = {binary_low}")
                        print(f"    Старший байт: {high_byte} (0x{high_byte:02X}) = {binary_high}")
                        
                        # Проверка CRC
                        if parsed['crc_valid']:
                            print(f"    CRC: ✓ Валиден ({parsed['received_crc']})")
                        else:
                            print(f"    CRC: ✗ Ошибка! Получен {parsed['received_crc']}, ожидался {parsed['calculated_crc']}")
                    else:
                        print("  Не удалось расшифровать ответ")
                else:
                    # Расшифровываем ответ на чтение
                    parsed = parse_read_response(resp)
                    if return_parsed:
                        return parsed
                    if parsed:
                        print(f"\n  Расшифровка ответа:")
                        print(f"    Unit ID: {parsed['unit_id']}")
                        print(f"    Функция: {parsed['function']:02d} (Read Input Registers)")
                        print(f"    Количество байт данных: {parsed['byte_count']}")
                        print(f"    Значение регистра: {parsed['value']} (десятичное)")
                        print(f"    Значение регистра: {parsed['value_hex']} (шестнадцатеричное)")
                        
                        # Бинарное представление
                        low_byte = parsed['value'] & 0xFF
                        high_byte = (parsed['value'] >> 8) & 0xFF
                        binary_low = format(low_byte, '08b')
                        binary_high = format(high_byte, '08b')
                        print(f"    Младший байт: {low_byte} (0x{low_byte:02X}) = {binary_low}")
                        print(f"    Старший байт: {high_byte} (0x{high_byte:02X}) = {binary_high}")
                        
                        # Проверка CRC
                        if parsed['crc_valid']:
                            print(f"    CRC: ✓ Валиден ({parsed['received_crc']})")
                        else:
                            print(f"    CRC: ✗ Ошибка! Получен {parsed['received_crc']}, ожидался {parsed['calculated_crc']}")
                    else:
                        print("  Не удалось расшифровать ответ")
            else:
                print("RX: (empty)")
                return None
        except socket.timeout:
            print("RX: (timeout)")
            return None
    except (ConnectionError, OSError) as e:
        # Ошибки соединения (Connection reset by peer и т.д.)
        if return_parsed:
            raise  # Пробрасываем исключение, чтобы обработать его на уровне выше
        else:
            print(f"Ошибка соединения: {e}")
            return None

def main():
    print("=== Modbus RTU over TCP ===")
    print(f"Подключение к {IP}:{PORT}...")
    
    sock = None
    try:
        sock = connect_socket()
        print("✓ Подключено успешно!")
        time.sleep(0.2)  # Задержка после подключения
        
        while True:
            try:
                cmd = input("\nmodbus> ").strip()
                if not cmd:
                    continue
                
                if cmd.lower() in ['quit', 'q', 'exit']:
                    break
                
                # Специальная команда для чтения IR данных
                if cmd.lower() in ['ir', 'read_ir']:
                    read_ir_data(sock)
                    continue
                
                # Парсим команду: функция адрес [реле]
                parts = cmd.split()
                if len(parts) < 2:
                    print("Использование:")
                    print("  Чтение: 04 <адрес>")
                    print("  Запись: 06 <адрес> <номер_реле>")
                    print("  IR данные: ir  или  read_ir")
                    print("Примеры:")
                    print("  04 1021  - прочитать регистр 1021")
                    print("  06 1021 2  - включить реле номер 2 в регистре 1021")
                    print("  ir  - прочитать все IR данные (регистры 400-477)")
                    continue
                
                function = int(parts[0])
                address = int(parts[1])
                
                if function == 4:
                    # Чтение регистра
                    frame = build_read_frame(function, address)
                    
                    # Отправляем 2 раза
                    print(f"\nОтправка запроса (функция {function:02d}, адрес {address})...")
                    for i in range(2):
                        print(f"\n--- Попытка {i+1} ---")
                        send_frame(sock, frame, is_write=False)
                        if i < 1:  # Не ждем после последней отправки
                            time.sleep(0.5)
                
                elif function == 6:
                    # Запись регистра
                    if len(parts) < 3:
                        print("Для записи укажите номер реле: 06 <адрес> <номер_реле>")
                        print("Пример: 06 1021 2")
                        continue
                    
                    relay_num = int(parts[2])
                    if relay_num < 1 or relay_num > 8:
                        print("Номер реле должен быть от 1 до 8")
                        continue
                    
                    # Сначала читаем текущее состояние (отправляем 2 раза, так как первый пакет теряется)
                    print(f"\nШаг 1: Чтение текущего состояния регистра {address}...")
                    read_frame = build_read_frame(4, address)
                    parsed = None
                    
                    # Отправляем 2 раза, берем результат из второго запроса
                    # Первая попытка может потерять пакет и разорвать соединение - это нормально
                    for i in range(2):
                        try:
                            print(f"  Попытка чтения {i+1}...")
                            parsed = send_frame(sock, read_frame, is_write=False, return_parsed=True)
                            # Если первая попытка не удалась, это нормально - продолжаем
                            if parsed or i == 1:  # Если получили ответ или это вторая попытка
                                break
                        except Exception as e:
                            # При первой попытке ошибка ожидаема - игнорируем
                            if i == 0:
                                print(f"  Первая попытка не удалась (это нормально): {e}")
                                # Переподключаемся если соединение разорвано
                                try:
                                    if sock:
                                        sock.close()
                                except:
                                    pass
                                sock = connect_socket()
                                time.sleep(0.2)
                            else:
                                # При второй попытке ошибка критична
                                raise
                        
                        if i < 1:  # Не ждем после последней отправки
                            time.sleep(0.5)
                    
                    if not parsed:
                        print("Ошибка: не удалось прочитать текущее состояние после 2 попыток")
                        continue
                    
                    current_value = parsed['value']
                    current_low_byte = current_value & 0xFF
                    
                    print(f"\n  Текущее состояние младшего байта: {current_low_byte} (0x{current_low_byte:02X}) = {format(current_low_byte, '08b')}")
                    
                    # Устанавливаем бит для реле (реле 1 = бит 0, реле 2 = бит 1, и т.д.)
                    bit_position = relay_num - 1  # Реле 1 -> бит 0, реле 2 -> бит 1
                    new_low_byte = current_low_byte | (1 << bit_position)
                    
                    # Формируем новое значение (старший байт оставляем как есть)
                    new_value = (current_value & 0xFF00) | new_low_byte
                    
                    print(f"  Включаем реле {relay_num} (бит {bit_position})")
                    print(f"  Новое значение младшего байта: {new_low_byte} (0x{new_low_byte:02X}) = {format(new_low_byte, '08b')}")
                    print(f"  Новое значение регистра: {new_value} (0x{new_value:04X})")
                    
                    # Записываем новое значение
                    print(f"\nШаг 2: Запись нового значения в регистр {address}...")
                    write_frame = build_write_frame(6, address, new_value)
                    
                    for i in range(2):
                        print(f"\n--- Попытка записи {i+1} ---")
                        send_frame(sock, write_frame, is_write=True)
                        if i < 1:
                            time.sleep(0.5)
                
                else:
                    print(f"Поддерживаются функции: 04 (чтение), 06 (запись)")
                    continue
                
            except ValueError:
                print("Ошибка: неверный формат числа")
            except KeyboardInterrupt:
                print("\nВыход...")
                break
            except Exception as e:
                print(f"Ошибка: {e}")
                # При ошибке переподключаемся
                if sock:
                    sock.close()
                sock = None
                print("Переподключение...")
                time.sleep(1)
                sock = connect_socket()
                time.sleep(0.2)
    
    finally:
        if sock:
            sock.close()
        print("\nОтключено.")

if __name__ == "__main__":
    main()