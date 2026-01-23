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

def registers_to_float_ir(registers: list, index: int) -> float:
    """Преобразование двух регистров (uint16) в float (IEEE 754) с перестановкой байтов для IR режима
    
    Перестановка: первый байт со вторым, третий с четвертым
    Было: [byte1, byte2, byte3, byte4]
    Стало: [byte2, byte1, byte4, byte3]
    """
    if index + 1 >= len(registers):
        return 0.0
    
    # Получаем два регистра
    reg1 = registers[index]      # Первый регистр (high)
    reg2 = registers[index + 1]  # Второй регистр (low)
    
    # Извлекаем байты из регистров
    # reg1: [high_byte1, low_byte1]
    # reg2: [high_byte2, low_byte2]
    byte1 = (reg1 >> 8) & 0xFF  # Старший байт первого регистра
    byte2 = reg1 & 0xFF         # Младший байт первого регистра
    byte3 = (reg2 >> 8) & 0xFF  # Старший байт второго регистра
    byte4 = reg2 & 0xFF         # Младший байт второго регистра
    
    # Переставляем: первый со вторым, третий с четвертым
    # [byte2, byte1, byte4, byte3]
    swapped_bytes = bytes([byte2, byte1, byte4, byte3])
    
    # Преобразуем в float
    import struct
    float_val = struct.unpack('>f', swapped_bytes)[0]
    
    return float_val

def read_ir_data(sock):
    """
    Чтение IR данных с правильным декодированием float (алгоритм из основной программы):
    - автоматически определяем формат float по x_min/x_max
    - правильно декодируем все метаданные
    - преобразуем y_values из uint16 в int16 и делим на 100.0
    
    Регистры:
    - 400: статус/флаг
    - 401-402: x min (float)
    - 403-404: x max (float)
    - 405-406: y min (float)
    - 407-408: y max (float)
    - 409-410: res_freq (float)
    - 411-412: freq (float)
    - 413-414: integral (float)
    - 420-477: data (ushort) - 58 регистров
    """
    import math
    import struct
    
    print(f"\n=== Чтение IR данных ===")
    
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
    
    meta = all_registers[0:15]  # Метаданные (400-414)
    data_regs = all_registers[20:78]  # Данные (420-477)
    
    print(f"Метаданные [0..4]: {meta[0:5]} (hex: {[hex(int(x)) for x in meta[0:5]]})")
    print(f"Данные первые 10: {data_regs[0:10]}, последние 3: {data_regs[-3:]}")
    
    status = int(meta[0])
    
    # Функция для декодирования float из двух uint16 во всех вариантах порядка байтов
    def _float_variants_from_regs(reg1: int, reg2: int) -> dict:
        """Декодируем float из двух uint16 во всех популярных Modbus byte/word order.
        A,B = bytes of reg1 (hi,lo); C,D = bytes of reg2 (hi,lo)
        Variants: ABCD, BADC (swap bytes in words), CDAB (swap words), DCBA (full reverse)
        """
        A = (reg1 >> 8) & 0xFF
        B = reg1 & 0xFF
        C = (reg2 >> 8) & 0xFF
        D = reg2 & 0xFF
        orders = {
            "ABCD": bytes([A, B, C, D]),
            "BADC": bytes([B, A, D, C]),
            "CDAB": bytes([C, D, A, B]),
            "DCBA": bytes([D, C, B, A]),
        }
        out: dict[str, float] = {}
        for k, bb in orders.items():
            try:
                v = float(struct.unpack(">f", bb)[0])
            except Exception:
                continue
            if math.isfinite(v):
                out[k] = v
        return out
    
    def _float_from_regs_with_key(reg1: int, reg2: int, key: str) -> float:
        vmap = _float_variants_from_regs(reg1, reg2)
        return float(vmap.get(key, float("nan")))
    
    # Определяем формат метаданных по x_min/x_max (401-404)
    xmin_r1, xmin_r2 = int(meta[1]), int(meta[2])
    xmax_r1, xmax_r2 = int(meta[3]), int(meta[4])
    x_min_variants = _float_variants_from_regs(xmin_r1, xmin_r2)
    x_max_variants = _float_variants_from_regs(xmax_r1, xmax_r2)
    common_keys = sorted(set(x_min_variants.keys()) & set(x_max_variants.keys()))
    
    meta_float_key = None
    x_min = float("nan")
    x_max = float("nan")
    candidates = []
    for k in common_keys:
        xv0 = float(x_min_variants[k])
        xv1 = float(x_max_variants[k])
        if not (math.isfinite(xv0) and math.isfinite(xv1)):
            continue
        if xv1 <= xv0:
            continue
        if abs(xv0) > 1e6 or abs(xv1) > 1e6:
            continue
        rng = xv1 - xv0
        if rng <= 0 or rng > 1e6:
            continue
        # IR обычно 792..798 (range ~6). Если несколько кандидатов — выбираем ближе к этому.
        score = abs(rng - 6.0) + 0.1 * abs(xv0 - 792.0) + 0.1 * abs(xv1 - 798.0)
        candidates.append((score, k, xv0, xv1))
    
    if candidates:
        candidates.sort(key=lambda t: t[0])
        _, meta_float_key, x_min, x_max = candidates[0]
        print(f"✓ Определен формат float: {meta_float_key}, x_min={x_min:.6f}, x_max={x_max:.6f}")
    else:
        # fallback (старое поведение)
        x_min = 792.0
        x_max = 798.0
        print(f"⚠️  Не удалось определить формат, используем fallback: x_min={x_min}, x_max={x_max}")
    
    # Декодируем остальные float-метаданные в том же формате
    y_min_meta = float("nan")
    y_max_meta = float("nan")
    res_freq = float("nan")
    freq = float("nan")
    integral = float("nan")
    
    y_min_r1, y_min_r2 = int(meta[5]), int(meta[6])
    y_max_r1, y_max_r2 = int(meta[7]), int(meta[8])
    res_r1, res_r2 = int(meta[9]), int(meta[10])
    freq_r1, freq_r2 = int(meta[11]), int(meta[12])
    int_r1, int_r2 = int(meta[13]), int(meta[14])
    
    if meta_float_key:
        y_min_meta = _float_from_regs_with_key(y_min_r1, y_min_r2, meta_float_key)
        y_max_meta = _float_from_regs_with_key(y_max_r1, y_max_r2, meta_float_key)
        res_freq = _float_from_regs_with_key(res_r1, res_r2, meta_float_key)
        freq = _float_from_regs_with_key(freq_r1, freq_r2, meta_float_key)
        integral = _float_from_regs_with_key(int_r1, int_r2, meta_float_key)
        
        # Иногда отдельные поля могут приехать "битые". Тогда добираем res_freq/freq из вариантов
        def _pick_any_in_range(reg1: int, reg2: int, lo: float, hi: float) -> float:
            vmap = _float_variants_from_regs(reg1, reg2)
            in_range = [v for v in vmap.values() if lo <= v <= hi]
            if not in_range:
                return float("nan")
            mid = (lo + hi) / 2.0
            in_range.sort(key=lambda v: abs(v - mid))
            return float(in_range[0])
        
        if not (math.isfinite(res_freq) and x_min <= res_freq <= x_max):
            rf2 = _pick_any_in_range(res_r1, res_r2, x_min, x_max)
            if math.isfinite(rf2):
                res_freq = rf2
        if not (math.isfinite(freq) and x_min <= freq <= x_max):
            f2 = _pick_any_in_range(freq_r1, freq_r2, x_min, x_max)
            if math.isfinite(f2):
                freq = f2
    else:
        # Fallback: старый IR байтсвап
        y_min_meta = registers_to_float_ir(meta, 5)
        y_max_meta = registers_to_float_ir(meta, 7)
        
        def _pick_variant_in_range(variants: dict, lo: float, hi: float) -> float:
            if not variants:
                return float("nan")
            in_range = [(k, v) for k, v in variants.items() if lo <= v <= hi]
            if not in_range:
                return float("nan")
            mid = (lo + hi) / 2.0
            in_range.sort(key=lambda kv: abs(kv[1] - mid))
            return float(in_range[0][1])
        
        res_variants = _float_variants_from_regs(res_r1, res_r2)
        freq_variants = _float_variants_from_regs(freq_r1, freq_r2)
        res_freq = _pick_variant_in_range(res_variants, x_min, x_max)
        freq = _pick_variant_in_range(freq_variants, x_min, x_max)
        if not math.isfinite(res_freq):
            res_freq = registers_to_float_ir(meta, 9)
        if not math.isfinite(freq):
            freq = registers_to_float_ir(meta, 11)
        integral = registers_to_float_ir(meta, 13)
    
    # Для отображения: y_min/y_max по умолчанию берем из метаданных
    y_min = float(y_min_meta) if math.isfinite(y_min_meta) else 0.0
    y_max = float(y_max_meta) if math.isfinite(y_max_meta) else 1.0
    
    # y values (raw uint16 from device)
    y_values_raw_u16 = [int(v) for v in data_regs[:58]]
    if not y_values_raw_u16:
        print("⚠️  Предупреждение: y_values пустые")
    
    # Преобразование для отображения:
    # Значения могут быть отрицательными -> интерпретируем как int16 (two's complement).
    # По данным устройства сырые значения ~4200 соответствуют пикам ~85, т.е. шаг ~0.02.
    # => отображаем как int16 / 50.0 (получим примерно диапазон -10..85).
    def _to_int16(u16: int) -> int:
        return u16 - 65536 if u16 >= 32768 else u16
    
    y_values_raw_i16 = [_to_int16(v) for v in y_values_raw_u16]
    scale = 100.0
    y_values = [float(v) / scale for v in y_values_raw_i16]
    
    # Для отображения используем диапазон из преобразованных данных
    if y_values:
        y_min = float(min(y_values))
        y_max = float(max(y_values))
    
    # Собираем точки для графика (x равномерно от x_min до x_max)
    points = []
    if len(y_values) >= 2 and x_max != x_min:
        step = (x_max - x_min) / float(len(y_values) - 1)
        for i, y in enumerate(y_values):
            points.append({"x": x_min + step * i, "y": float(y)})
    else:
        for i, y in enumerate(y_values):
            points.append({"x": float(i), "y": float(y)})
    
    print(f"\n✓ IR спектр декодирован:")
    print(f"  Статус: {status}")
    print(f"  X диапазон: [{x_min:.6f}, {x_max:.6f}]")
    print(f"  Y диапазон: [{y_min:.6f}, {y_max:.6f}]")
    print(f"  Res freq: {res_freq:.6f}")
    print(f"  Freq: {freq:.6f}")
    print(f"  Integral: {integral:.6f}")
    print(f"  Точек: {len(points)}")
    print(f"  Raw u16 диапазон: [{min(y_values_raw_u16) if y_values_raw_u16 else 'n/a'}, {max(y_values_raw_u16) if y_values_raw_u16 else 'n/a'}]")
    print(f"  Raw i16 диапазон: [{min(y_values_raw_i16) if y_values_raw_i16 else 'n/a'}, {max(y_values_raw_i16) if y_values_raw_i16 else 'n/a'}]")
    print(f"  Scaled y диапазон: [{y_min:.6f}, {y_max:.6f}]")
    print(f"  Первые 10 значений данных: {y_values[:10]}")
    print(f"  Последние 10 значений данных: {y_values[-10:]}")
    print(f"\n  Все 58 значений Y (после деления на 100.0):")
    for i, y_val in enumerate(y_values):
        print(f"    [{i:2d}] = {y_val:.6f}")
    print()
        
    return {
        "status": status,
        "x_min": float(x_min),
        "x_max": float(x_max),
        "y_min": float(y_min),
        "y_max": float(y_max),
        "res_freq": float(res_freq),
        "freq": float(freq),
        "integral": float(integral),
        "meta_float_key": meta_float_key,
        "data_raw_u16": y_values_raw_u16,
        "data_raw_i16": y_values_raw_i16,
        "data": y_values,
        "points": points,
    }

def read_nmr_data(sock):
    """Чтение всех NMR данных за один раз
    
    Читает регистры:
    - 100: samples
    - 101-102: x_min (float)
    - 103-104: x_max (float)
    - 105-106: y_min (float)
    - 107-108: y_max (float)
    - 109-110: freq (float)
    - 111-112: ampl (float)
    - 113-114: int (float)
    - 115-116: t2 (float)
    - 120-375: data (ushort) - 256 регистров
    
    Всего: 100-116 (17 регистров) + 120-375 (256 регистров) = 273 регистра
    """
    print(f"\n=== Чтение NMR данных ===")
    
    # Варианты для проверки (если первый не сработает)
    address_variants = [100, 99, 0]  # 100, 99 (0-based), 0 (относительная адресация)
    
    # Читаем регистры частями
    # Согласно описанию:
    # - 100-116: метаданные (17 регистров)
    # - 120-375: данные (256 регистров)
    # Между 116 и 120 есть пропуск (регистры 117-119 не существуют)!
    # Разбиваем на части по 30 регистров для надежности (максимум обычно 125, но устройство может ограничивать)
    read_ranges = [
        (0, 17),      # 0-16 (17 регистров) - метаданные (100-116)
        (20, 30),     # 20-49 (30 регистров) - первая часть данных (120-149)
        (50, 30),     # 50-79 (30 регистров) - вторая часть данных (150-179)
        (80, 30),     # 80-109 (30 регистров) - третья часть данных (180-209)
        (110, 30),    # 110-139 (30 регистров) - четвертая часть данных (210-239)
        (140, 30),    # 140-169 (30 регистров) - пятая часть данных (240-269)
        (170, 30),    # 170-199 (30 регистров) - шестая часть данных (270-299)
        (200, 30),    # 200-229 (30 регистров) - седьмая часть данных (300-329)
        (230, 30),    # 230-259 (30 регистров) - восьмая часть данных (330-359)
        (260, 16),    # 260-275 (16 регистров) - последняя часть данных (360-375)
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
            
            # Читаем ответ с таймаутом, собирая все данные
            resp = b''
            try:
                sock.settimeout(0.5)
                while True:
                    chunk = sock.recv(512)
                    if not chunk:
                        break
                    resp += chunk
                    # Если получили достаточно данных, проверяем, не закончился ли фрейм
                    if len(resp) >= 5:
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
                    
                    # Если это ошибка для регистров данных (120+), пропускаем их
                    if start_addr >= 120 and (error_code == 2 or error_code == 3):
                        print(f"⚠️  Регистры {start_addr}-{start_addr + quantity - 1} недоступны, пропускаем...")
                        # Продолжаем чтение следующих диапазонов
                        continue
                    
                    # Если это ошибка адреса для метаданных, пробуем другие варианты
                    if error_code == 2 and address_base == address_variants[0] and start_addr < 120:
                        print(f"\n⚠️  Пробуем альтернативный адрес...")
                        # Пробуем адрес 99 (0-based адресация)
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
                                    # Если это регистры данных (120+), пропускаем
                                    if retry_addr >= 120:
                                        print(f"⚠️  Регистры {retry_addr} недоступны, пропускаем...")
                                        continue
                                    print(f"❌ Ошибка при чтении регистров {retry_addr}")
                                    return None
                        break  # Выходим из основного цикла, так как уже прочитали все
                    elif start_addr < 120:
                        # Ошибка для метаданных - критично
                        return None
                    else:
                        # Для регистров данных просто пропускаем
                        continue
                
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
    
    # Проверяем, что получили метаданные (обязательно)
    if len([k for k in registers_dict.keys() if 100 <= k <= 116]) < 17:
        print(f"❌ Ошибка: не удалось прочитать метаданные (регистры 100-116)")
        return None
    
    # Проверяем данные (могут быть недоступны)
    data_registers = [k for k in registers_dict.keys() if 120 <= k <= 375]
    if len(data_registers) == 0:
        print(f"⚠️  Предупреждение: регистры данных (120-375) недоступны")
        print(f"   Будут возвращены только метаданные")
    else:
        print(f"✓ Прочитано {len(data_registers)} регистров данных из 256")
    
    # Создаем полный массив с пропуском между 116 и 120
    # Индексы: 0-16 (100-116), затем пропуск 17-19, затем 20-275 (120-375)
    full_registers = [0] * 276  # 100-375 включительно = 276 регистров
    # Заполняем первые 17 регистров (100-116) - обязательно должны быть
    for i in range(100, 117):
        if i in registers_dict:
            full_registers[i - 100] = registers_dict[i]
        else:
            print(f"⚠️  Предупреждение: регистр {i} не прочитан")
    # Заполняем регистры 120-375 (индексы 20-275 в полном массиве) - могут отсутствовать
    for i in range(120, 376):
        if i in registers_dict:
            full_registers[i - 100] = registers_dict[i]
    
    # Используем full_registers
    all_registers = full_registers
    
    try:
        # Извлекаем данные
        result = {
            'samples': all_registers[0],  # регистр 100
            'x_min': registers_to_float(all_registers, 1),  # регистры 101-102
            'x_max': registers_to_float(all_registers, 3),  # регистры 103-104
            'y_min': registers_to_float(all_registers, 5),  # регистры 105-106
            'y_max': registers_to_float(all_registers, 7),  # регистры 107-108
            'freq': registers_to_float(all_registers, 9),  # регистры 109-110
            'ampl': registers_to_float(all_registers, 11),  # регистры 111-112
            'int': registers_to_float(all_registers, 13),  # регистры 113-114
            't2': registers_to_float(all_registers, 15),  # регистры 115-116
            'data': all_registers[20:276]  # регистры 120-375 (индекс 20-275 в массиве)
        }
        
        # Выводим результаты
        print(f"\n✓ Все данные успешно прочитаны!")
        print(f"\nРезультаты:")
        print(f"  Samples (100): {result['samples']} (0x{result['samples']:04X})")
        print(f"  X min (101-102): {result['x_min']:.6f}")
        print(f"  X max (103-104): {result['x_max']:.6f}")
        print(f"  Y min (105-106): {result['y_min']:.6f}")
        print(f"  Y max (107-108): {result['y_max']:.6f}")
        print(f"  Freq (109-110): {result['freq']:.6f}")
        print(f"  Ampl (111-112): {result['ampl']:.6f}")
        print(f"  Int (113-114): {result['int']:.6f}")
        print(f"  T2 (115-116): {result['t2']:.6f}")
        print(f"  Data (120-375): {len(result['data'])} значений")
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

def read_float_value(sock, address: int):
    """Чтение float значения из двух регистров (address и address+1)"""
    print(f"\n=== Чтение float значения ===")
    print(f"Чтение регистров {address} и {address+1}...")
    
    # Читаем два регистра
    frame = build_read_multiple_registers_frame(4, address, 2)
    
    try:
        hex_dump("TX", frame)
        sock.sendall(frame)
        
        time.sleep(0.1)
        
        # Читаем ответ
        resp = b''
        try:
            sock.settimeout(0.5)
            while True:
                chunk = sock.recv(512)
                if not chunk:
                    break
                resp += chunk
                if len(resp) >= 5:
                    start_idx = find_modbus_frame_start(resp)
                    if start_idx >= 0:
                        frame_start = resp[start_idx:]
                        if len(frame_start) >= 3:
                            byte_count = frame_start[2]
                            expected_length = 3 + byte_count + 2
                            if len(frame_start) >= expected_length:
                                break
        except socket.timeout:
            pass
        finally:
            sock.settimeout(2.0)
        
        if resp:
            hex_dump("RX", resp)
            
            parsed = parse_multiple_registers_response(resp)
            if not parsed:
                print("Ошибка: не удалось распарсить ответ")
                return None
            
            # Проверяем на ошибку Modbus
            if parsed.get('is_error'):
                error_msg = parsed['error_message']
                error_code = parsed['error_code']
                print(f"❌ Ошибка Modbus: {error_msg} (код {error_code})")
                return None
            
            registers = parsed.get('registers', [])
            if len(registers) < 2:
                print(f"❌ Ошибка: получено только {len(registers)} регистров вместо 2")
                return None
            
            # Меняем местами регистры: первый становится вторым, второй становится первым
            # FF DF 44 45 -> 44 45 FF DF
            swapped_registers = [registers[1], registers[0]]
            
            print(f"  Исходные регистры: {registers[0]:04X} {registers[1]:04X}")
            print(f"  После перестановки регистров: {swapped_registers[0]:04X} {swapped_registers[1]:04X}")
            
            # Преобразуем в float
            float_val = registers_to_float(swapped_registers, 0)
            
            print(f"\n✓ Данные успешно прочитаны!")
            print(f"\nРезультаты:")
            print(f"  Регистр {address}: {registers[0]} (0x{registers[0]:04X})")
            print(f"  Регистр {address+1}: {registers[1]} (0x{registers[1]:04X})")
            print(f"  Float значение: {float_val:.6f}")
            print(f"  Float значение (научная нотация): {float_val:.6e}")
            
            return float_val
        else:
            print("RX: (empty)")
            return None
    except socket.timeout:
        print("RX: (timeout)")
        return None
    except (ConnectionError, OSError) as e:
        print(f"Ошибка соединения: {e}")
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
                
                # Специальная команда для чтения NMR данных
                if cmd.lower() in ['nmr', 'read_nmr']:
                    read_nmr_data(sock)
                    continue
                
                # Команда для чтения float значения
                parts = cmd.split()
                if len(parts) >= 2 and parts[0].lower() == 'float':
                    try:
                        address = int(parts[1])
                        read_float_value(sock, address)
                    except ValueError:
                        print("Ошибка: неверный адрес. Использование: float <адрес>")
                    continue
                
                # Парсим команду: функция адрес [реле]
                if len(parts) < 2:
                    print("Использование:")
                    print("  Чтение: 04 <адрес>")
                    print("  Запись: 06 <адрес> <номер_реле>")
                    print("  Float: float <адрес>  - прочитать float из двух регистров")
                    print("  IR данные: ir  или  read_ir")
                    print("  NMR данные: nmr  или  read_nmr")
                    print("Примеры:")
                    print("  04 1021  - прочитать регистр 1021")
                    print("  06 1021 2  - включить реле номер 2 в регистре 1021")
                    print("  float 401  - прочитать float из регистров 401-402")
                    print("  ir  - прочитать все IR данные (регистры 400-414, 420-477)")
                    print("  nmr  - прочитать все NMR данные (регистры 100-116, 120-375)")
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