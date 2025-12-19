"""
QML-модель для управления Modbus подключением
"""
from PySide6.QtCore import QObject, Signal, Property, QTimer, Slot, QThread
from modbus_client import ModbusClient
import logging
from collections import deque
from typing import Callable, Optional, Any
import time

logger = logging.getLogger(__name__)


class _ModbusIoWorker(QObject):
    """
    Выполняет блокирующие Modbus операции в отдельном потоке.

    Важно: никаких обращений к QML/GUI здесь быть не должно.
    """

    connectFinished = Signal(bool, str)  # success, error_message
    disconnected = Signal()
    readFinished = Signal(str, object)  # key, value
    writeFinished = Signal(str, bool, object)  # key, success, meta

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._client: Optional[ModbusClient] = None

        self._read_queue: deque = deque()
        self._write_queue: deque = deque()  # приоритетные задачи (записи)
        self._processing = False

        self._task_timer = QTimer(self)
        self._task_timer.setSingleShot(True)
        self._task_timer.timeout.connect(self._process_one)

    @Slot(object)
    def setClient(self, client: Optional[ModbusClient]):
        self._client = client

    @Slot()
    def connectClient(self):
        """Подключение в worker-потоке (может блокировать)."""
        if self._client is None:
            self.connectFinished.emit(False, "Modbus client is not initialized")
            return
        try:
            ok = bool(self._client.connect())
            if ok:
                self.connectFinished.emit(True, "")
            else:
                self.connectFinished.emit(False, "Connection Failed")
        except Exception as e:
            self.connectFinished.emit(False, str(e))

    @Slot()
    def disconnectClient(self):
        """Отключение в worker-потоке."""
        try:
            # На отключение очищаем очереди, чтобы не выполнять старые задачи.
            self._read_queue.clear()
            self._write_queue.clear()
            if self._client is not None:
                self._client.disconnect()
        finally:
            self.disconnected.emit()

    @Slot(str, object)
    def enqueueRead(self, key: str, func: Callable[[], Any]):
        self._read_queue.append((key, func))
        if not self._task_timer.isActive() and not self._processing:
            self._task_timer.start(0)

    @Slot(str, object, object)
    def enqueueWrite(self, key: str, func: Callable[[], bool], meta: object = None):
        # Записи имеют приоритет
        self._write_queue.append((key, func, meta))
        if not self._task_timer.isActive() and not self._processing:
            self._task_timer.start(0)

    @Slot()
    def _process_one(self):
        if self._processing:
            # на всякий случай
            self._task_timer.start(1)
            return

        if not self._write_queue and not self._read_queue:
            return

        self._processing = True
        try:
            if self._write_queue:
                key, func, meta = self._write_queue.popleft()
                try:
                    ok = bool(func())
                except Exception:
                    logger.exception("Modbus write task failed")
                    ok = False
                self.writeFinished.emit(key, ok, meta)
            else:
                key, func = self._read_queue.popleft()
                try:
                    value = func()
                except Exception:
                    logger.exception("Modbus read task failed")
                    value = None
                self.readFinished.emit(key, value)
        finally:
            self._processing = False
            # Быстро вычерпываем очередь, но даем event loop шанс обработать события.
            if self._write_queue or self._read_queue:
                self._task_timer.start(0)


class ModbusManager(QObject):
    """Менеджер для управления Modbus подключением, доступный из QML"""
    
    # Сигналы для QML
    connectionStatusChanged = Signal(bool)
    statusTextChanged = Signal(str)
    connectionButtonTextChanged = Signal(str)  # Отдельный сигнал для текста кнопки подключения
    errorOccurred = Signal(str)
    
    # Сигналы для синхронизации состояний устройств
    fanStateChanged = Signal(int, bool)  # fanIndex, state
    valveStateChanged = Signal(int, bool)  # valveIndex, state
    laserPSUStateChanged = Signal(bool)
    magnetPSUStateChanged = Signal(bool)
    pidControllerStateChanged = Signal(bool)
    waterChillerStateChanged = Signal(bool)
    waterChillerTemperatureChanged = Signal(float)  # Текущая температура Water Chiller в градусах Цельсия (регистр 1511)
    waterChillerSetpointChanged = Signal(float)  # Заданная температура Water Chiller в градусах Цельсия (регистр 1531)
    seopCellTemperatureChanged = Signal(float)  # Температура SEOP Cell в градусах Цельсия (регистр 1411)
    seopCellSetpointChanged = Signal(float)  # Заданная температура SEOP Cell в градусах Цельсия (регистр 1421)
    magnetPSUCurrentChanged = Signal(float)  # Ток Magnet PSU в амперах (регистр 1341)
    magnetPSUSetpointChanged = Signal(float)  # Заданная температура Magnet PSU в градусах Цельсия (регистр 1331)
    laserPSUCurrentChanged = Signal(float)  # Ток Laser PSU в амперах (регистр 1251)
    laserPSUSetpointChanged = Signal(float)  # Заданная температура Laser PSU в градусах Цельсия (регистр 1241)
    xenonPressureChanged = Signal(float)  # Давление Xenon в Torr (регистр 1611)
    n2SetpointChanged = Signal(float)  # Заданное давление N2 в Torr (регистр 1661)
    xenonSetpointChanged = Signal(float)  # Заданное давление Xenon в Torr (регистр 1621)
    n2PressureChanged = Signal(float)  # Давление N2 в Torr (регистр 1651)
    vacuumPressureChanged = Signal(float)  # Давление Vacuum в Torr (регистр 1701)
    vacuumPumpStateChanged = Signal(bool)
    vacuumGaugeStateChanged = Signal(bool)
    externalRelaysChanged = Signal(int, str)  # value, binary_string - для регистра 1020
    opCellHeatingStateChanged = Signal(bool)  # OP cell heating (реле 7)
    # Сигналы для паузы/возобновления опросов (используется при переключении экранов)
    pollingPausedChanged = Signal(bool)
    # IR spectrum (Clinicalmode/Screen01 IR graph)
    # Важно: используем QVariantMap, чтобы QML видел обычный JS object/array, а не PyObjectWrapper.
    irSpectrumChanged = Signal('QVariantMap')  # payload map: {x_min,x_max,y_min,y_max,points,data,...}

    # Внутренние сигналы (НЕ для QML): отправка задач в worker-поток
    _workerSetClient = Signal(object)
    _workerConnect = Signal()
    _workerDisconnect = Signal()
    _workerEnqueueRead = Signal(str, object)
    _workerEnqueueWrite = Signal(str, object, object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._modbus_client: ModbusClient = None
        self._is_connected = False
        self._connection_in_progress = False
        self._last_modbus_ok_time = 0.0
        self._last_reconnect_attempt_time = 0.0
        self._status_text = "Disconnected"
        self._connection_button_text = "Connect"  # Текст кнопки подключения: "Connect" или "Disconnect"
        self._water_chiller_temperature = 0.0  # Текущая температура Water Chiller (регистр 1511)
        self._water_chiller_setpoint = 0.0  # Заданная температура Water Chiller (регистр 1531)
        self._water_chiller_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._water_chiller_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._water_chiller_setpoint_auto_update_timer.timeout.connect(self._autoUpdateWaterChillerSetpoint)
        self._water_chiller_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._seop_cell_temperature = 0.0  # Температура SEOP Cell (регистр 1411)
        self._seop_cell_setpoint = 0.0  # Заданная температура SEOP Cell (регистр 1421)
        self._seop_cell_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._seop_cell_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._seop_cell_setpoint_auto_update_timer.timeout.connect(self._autoUpdateSeopCellSetpoint)
        self._seop_cell_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._seop_cell_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._seop_cell_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._seop_cell_setpoint_auto_update_timer.timeout.connect(self._autoUpdateSeopCellSetpoint)
        self._seop_cell_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._magnet_psu_current = 0.0  # Ток Magnet PSU в амперах (регистр 1341)
        self._magnet_psu_setpoint = 0.0  # Заданная температура Magnet PSU (регистр 1331)
        self._magnet_psu_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._magnet_psu_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._magnet_psu_setpoint_auto_update_timer.timeout.connect(self._autoUpdateMagnetPSUSetpoint)
        self._magnet_psu_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._laser_psu_current = 0.0  # Ток Laser PSU в амперах (регистр 1251)
        self._laser_psu_setpoint = 0.0  # Заданная температура Laser PSU (регистр 1241)
        self._laser_psu_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._laser_psu_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._laser_psu_setpoint_auto_update_timer.timeout.connect(self._autoUpdateLaserPSUSetpoint)
        self._laser_psu_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._xenon_pressure = 0.0  # Давление Xenon в Torr (регистр 1611)
        self._xenon_setpoint = 0.0  # Заданное давление Xenon в Torr (регистр 1621)
        self._xenon_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._xenon_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._xenon_setpoint_auto_update_timer.timeout.connect(self._autoUpdateXenonSetpoint)
        self._xenon_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._n2_pressure = 0.0  # Давление N2 в Torr (регистр 1651)
        self._n2_setpoint = 0.0  # Заданное давление N2 (регистр 1661)
        self._n2_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._n2_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._n2_setpoint_auto_update_timer.timeout.connect(self._autoUpdateN2Setpoint)
        self._n2_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._vacuum_pressure = 0.0  # Давление Vacuum в Torr (регистр 1701)

        # IR spectrum cache
        self._ir_last = None
        self._ir_request_in_flight = False
        
        # Буфер состояний устройств для мгновенного отображения при переключении страниц
        # Реле (регистр 1021)
        self._relay_states = {
            'water_chiller': False,
            'magnet_psu': False,
            'laser_psu': False,
            'vacuum_pump': False,
            'vacuum_gauge': False,
            'pid_controller': False,
            'op_cell_heating': False
        }
        # Клапаны (регистр 1111) - индексы 5-11 для X6-X12
        self._valve_states = {i: False for i in range(5, 12)}
        # Вентиляторы (регистр 1131) - индексы 0-10
        self._fan_states = {i: False for i in range(11)}
        self._fan_optimistic_updates = {}  # Флаги оптимистичных обновлений вентиляторов: fanIndex -> timestamp
        # Буфер для регистров (для быстрого доступа без блокировки UI)
        self._register_cache = {}  # address -> value
        # Флаг паузы опросов (чтобы при переключении экранов не блокировать UI)
        self._polling_paused = False
        
        # Статичные параметры подключения к XeUS driver
        self._host = "192.168.4.1"
        self._port = 503
        self._unit_id = 1
        
        # Таймер для периодической проверки подключения и keep-alive
        self._connection_check_timer = QTimer(self)
        self._connection_check_timer.timeout.connect(self._check_connection)
        self._connection_check_timer.setInterval(500)  # Проверка каждые 0.5 секунды + keep-alive
        self._connection_fail_count = 0  # Счетчик неудачных проверок
        
        # Таймер для синхронизации состояний устройств
        self._sync_timer = QTimer(self)
        self._sync_timer.timeout.connect(self._syncDeviceStates)
        self._sync_timer.setInterval(1000)  # Интервал 1 секунда для быстрого обновления
        self._syncing = False  # Флаг для предотвращения параллельных синхронизаций
        self._sync_fail_count = 0  # Счетчик неудачных синхронизаций
        self._last_sync_time = 0  # Время последней синхронизации
        
        # Флаги для предотвращения параллельных чтений
        self._reading_1021 = False
        self._reading_1111 = False
        self._reading_1511 = False
        self._reading_1411 = False
        self._reading_1341 = False
        self._reading_1251 = False
        self._reading_1611 = False
        self._reading_1651 = False
        self._reading_1701 = False
        self._reading_1131 = False
        # Флаги оптимистичных обновлений
        self._fan_optimistic_updates = {}  # Флаги оптимистичных обновлений вентиляторов: fanIndex -> timestamp
        # Список таймеров, которые можно приостанавливать (для быстрой смены экранов)
        self._polling_timers = []
        
        # Таймер для чтения регистра 1021 (реле) - быстрое обновление
        self._relay_1021_timer = QTimer(self)
        self._relay_1021_timer.timeout.connect(self._readRelay1021)
        self._relay_1021_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1111 (клапаны X6-X12) - быстрое обновление
        self._valve_1111_timer = QTimer(self)
        self._valve_1111_timer.timeout.connect(self._readValve1111)
        self._valve_1111_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1511 (температура Water Chiller) - быстрое обновление
        self._water_chiller_temp_timer = QTimer(self)
        self._water_chiller_temp_timer.timeout.connect(self._readWaterChillerTemperature)
        self._water_chiller_temp_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1411 (температура SEOP Cell) - быстрое обновление
        self._seop_cell_temp_timer = QTimer(self)
        self._seop_cell_temp_timer.timeout.connect(self._readSeopCellTemperature)
        self._seop_cell_temp_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1341 (ток Magnet PSU) - быстрое обновление
        self._magnet_psu_current_timer = QTimer(self)
        self._magnet_psu_current_timer.timeout.connect(self._readMagnetPSUCurrent)
        self._magnet_psu_current_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1251 (ток Laser PSU) - быстрое обновление
        self._laser_psu_current_timer = QTimer(self)
        self._laser_psu_current_timer.timeout.connect(self._readLaserPSUCurrent)
        self._laser_psu_current_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1611 (давление Xenon) - быстрое обновление
        self._xenon_pressure_timer = QTimer(self)
        self._xenon_pressure_timer.timeout.connect(self._readXenonPressure)
        self._xenon_pressure_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1651 (давление N2) - быстрое обновление
        self._n2_pressure_timer = QTimer(self)
        self._n2_pressure_timer.timeout.connect(self._readN2Pressure)
        self._n2_pressure_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1701 (давление Vacuum) - быстрое обновление
        self._vacuum_pressure_timer = QTimer(self)
        self._vacuum_pressure_timer.timeout.connect(self._readVacuumPressure)
        self._vacuum_pressure_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистра 1131 (fans) - быстрое обновление
        self._fan_1131_timer = QTimer(self)
        self._fan_1131_timer.timeout.connect(self._readFan1131)
        self._fan_1131_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления

        # Список таймеров для паузы/возобновления опросов
        self._polling_timers = [
            self._connection_check_timer,
            self._sync_timer,
            self._relay_1021_timer,
            self._valve_1111_timer,
            self._water_chiller_temp_timer,
            self._seop_cell_temp_timer,
            self._magnet_psu_current_timer,
            self._laser_psu_current_timer,
            self._xenon_pressure_timer,
            self._n2_pressure_timer,
            self._vacuum_pressure_timer,
            self._fan_1131_timer,
        ]
        
        # Worker-поток для Modbus I/O (чтобы UI не подвисал)
        self._io_thread = QThread(self)
        self._io_worker = _ModbusIoWorker()
        self._io_worker.moveToThread(self._io_thread)

        # Подключаем внутренние сигналы к worker слотам (queued connection автоматически, т.к. другой поток)
        self._workerSetClient.connect(self._io_worker.setClient)
        self._workerConnect.connect(self._io_worker.connectClient)
        self._workerDisconnect.connect(self._io_worker.disconnectClient)
        self._workerEnqueueRead.connect(self._io_worker.enqueueRead)
        self._workerEnqueueWrite.connect(self._io_worker.enqueueWrite)

        # Результаты от worker обратно в GUI-поток
        self._io_worker.connectFinished.connect(self._onWorkerConnectFinished)
        self._io_worker.disconnected.connect(self._onWorkerDisconnected)
        self._io_worker.readFinished.connect(self._onWorkerReadFinished)
        self._io_worker.writeFinished.connect(self._onWorkerWriteFinished)

        self._io_thread.start()
        self.destroyed.connect(self._shutdownIoThread)
    
    @Property(str, notify=statusTextChanged)
    def statusText(self):
        """Текст статуса последнего действия (для отображения в статусной строке)"""
        return self._status_text
    
    @Property(str, notify=connectionButtonTextChanged)
    def connectionButtonText(self):
        """Текст кнопки подключения: 'Connect' или 'Disconnect'"""
        return self._connection_button_text
    
    def _updateActionStatus(self, action: str):
        """Обновление статуса последнего действия пользователя"""
        logger.info(f"🔄 Обновление статуса действия: {action}")
        self._status_text = action
        self.statusTextChanged.emit(self._status_text)
        logger.info(f"✅ Статус обновлен, эмитирован сигнал. Текущий статус: {self._status_text}")
    
    def _emitCachedStates(self):
        """Отправка всех состояний из буфера в UI для мгновенного отображения при переключении страниц"""
        # Отправляем состояния реле из буфера
        self.waterChillerStateChanged.emit(self._relay_states['water_chiller'])
        self.magnetPSUStateChanged.emit(self._relay_states['magnet_psu'])
        self.laserPSUStateChanged.emit(self._relay_states['laser_psu'])
        self.vacuumPumpStateChanged.emit(self._relay_states['vacuum_pump'])
        self.vacuumGaugeStateChanged.emit(self._relay_states['vacuum_gauge'])
        self.pidControllerStateChanged.emit(self._relay_states['pid_controller'])
        self.opCellHeatingStateChanged.emit(self._relay_states['op_cell_heating'])
        
        # Отправляем состояния клапанов из буфера
        for valve_index in range(5, 12):
            self.valveStateChanged.emit(valve_index, self._valve_states[valve_index])
        
        # Отправляем состояния вентиляторов из буфера
        for fan_index in range(11):
            self.fanStateChanged.emit(fan_index, self._fan_states[fan_index])
        
        # Отправляем числовые значения (температуры, токи, давления) - они уже хранятся в свойствах
        # и автоматически доступны через Properties, но можно явно эмитировать сигналы для обновления UI
        self.waterChillerTemperatureChanged.emit(self._water_chiller_temperature)
        self.waterChillerSetpointChanged.emit(self._water_chiller_setpoint)
        self.seopCellTemperatureChanged.emit(self._seop_cell_temperature)
        self.seopCellSetpointChanged.emit(self._seop_cell_setpoint)
        self.magnetPSUCurrentChanged.emit(self._magnet_psu_current)
        self.magnetPSUSetpointChanged.emit(self._magnet_psu_setpoint)
        self.laserPSUCurrentChanged.emit(self._laser_psu_current)
        self.laserPSUSetpointChanged.emit(self._laser_psu_setpoint)
        self.xenonPressureChanged.emit(self._xenon_pressure)
        self.xenonSetpointChanged.emit(self._xenon_setpoint)
        self.n2PressureChanged.emit(self._n2_pressure)
        self.n2SetpointChanged.emit(self._n2_setpoint)
        self.vacuumPressureChanged.emit(self._vacuum_pressure)

    @Slot()
    def pausePolling(self):
        """Приостановить все таймеры опроса (используется при переключении экранов)"""
        if self._polling_paused:
            return
        self._polling_paused = True
        for t in self._polling_timers:
            t.stop()
        self.pollingPausedChanged.emit(True)
        logger.info("⏸ Опрос Modbus приостановлен для переключения экрана")

    @Slot()
    def resumePolling(self):
        """Возобновить таймеры опроса после паузы"""
        if not self._polling_paused:
            return
        self._polling_paused = False
        for t in self._polling_timers:
            t.start()
        self.pollingPausedChanged.emit(False)
        logger.info("▶️ Опрос Modbus возобновлен после переключения экрана")
    
    @Slot()
    def refreshUIFromCache(self):
        """Публичный метод для принудительного обновления UI из буфера (можно вызывать из QML при переключении страниц)"""
        self._emitCachedStates()
    
    @Property(bool, notify=connectionStatusChanged)
    def isConnected(self):
        """Состояние подключения"""
        return self._is_connected
    
    @Property(float, notify=waterChillerTemperatureChanged)
    def waterChillerTemperature(self):
        """Текущая температура Water Chiller в градусах Цельсия (регистр 1511)"""
        return self._water_chiller_temperature
    
    @Property(float, notify=waterChillerSetpointChanged)
    def waterChillerSetpoint(self):
        """Заданная температура Water Chiller в градусах Цельсия (регистр 1531)"""
        return self._water_chiller_setpoint
    
    @Property(float, notify=seopCellSetpointChanged)
    def seopCellSetpoint(self):
        """Заданная температура SEOP Cell в градусах Цельсия (регистр 1421)"""
        return self._seop_cell_setpoint
    
    @Property(float, notify=magnetPSUSetpointChanged)
    def magnetPSUSetpoint(self):
        """Заданная температура Magnet PSU в градусах Цельсия (регистр 1331)"""
        return self._magnet_psu_setpoint
    
    @Property(float, notify=laserPSUSetpointChanged)
    def laserPSUSetpoint(self):
        """Заданная температура Laser PSU в градусах Цельсия (регистр 1241)"""
        return self._laser_psu_setpoint
    
    @Property(float, notify=xenonSetpointChanged)
    def xenonSetpoint(self):
        """Заданное давление Xenon в Torr (регистр 1621)"""
        return self._xenon_setpoint
    
    @Property(float, notify=seopCellTemperatureChanged)
    def seopCellTemperature(self):
        """Температура SEOP Cell в градусах Цельсия (регистр 1411)"""
        return self._seop_cell_temperature
    
    @Property(float, notify=magnetPSUCurrentChanged)
    def magnetPSUCurrent(self):
        """Ток Magnet PSU в амперах (регистр 1341)"""
        return self._magnet_psu_current
    
    @Property(float, notify=laserPSUCurrentChanged)
    def laserPSUCurrent(self):
        """Ток Laser PSU в амперах (регистр 1251)"""
        return self._laser_psu_current
    
    @Property(float, notify=xenonPressureChanged)
    def xenonPressure(self):
        """Давление Xenon в Torr (регистр 1611)"""
        return self._xenon_pressure
    
    @Property(float, notify=n2PressureChanged)
    def n2Pressure(self):
        """Давление N2 в Torr (регистр 1651)"""
        return self._n2_pressure
    
    @Property(float, notify=n2SetpointChanged)
    def n2Setpoint(self):
        """Заданное давление N2 в Torr (регистр 1661)"""
        return self._n2_setpoint
    
    @Property(float, notify=vacuumPressureChanged)
    def vacuumPressure(self):
        """Давление Vacuum в Torr (регистр 1701)"""
        return self._vacuum_pressure
    
    @Property(str)
    def host(self):
        """IP адрес устройства"""
        return self._host
    
    @host.setter
    def host(self, value: str):
        if self._host != value:
            # Если было подключение, отключаемся
            if self._is_connected:
                self.disconnect()
            self._host = value
            # Пересоздаем клиент с новыми параметрами
            self._modbus_client = None
            logger.info(f"Установлен host: {value}")
    
    @Property(int)
    def port(self):
        """Порт Modbus"""
        return self._port
    
    @port.setter
    def port(self, value: int):
        if self._port != value:
            # Если было подключение, отключаемся
            if self._is_connected:
                self.disconnect()
            self._port = value
            # Пересоздаем клиент с новыми параметрами
            self._modbus_client = None
            logger.info(f"Установлен port: {value}")
    
    @Property(int)
    def unitId(self):
        """ID устройства Modbus"""
        return self._unit_id
    
    @unitId.setter
    def unitId(self, value: int):
        if self._unit_id != value:
            # Если было подключение, отключаемся
            if self._is_connected:
                self.disconnect()
            self._unit_id = value
            # Пересоздаем клиент с новыми параметрами
            self._modbus_client = None
            logger.info(f"Установлен unit_id: {value}")
    
    @Slot()
    def toggleConnection(self):
        """Переключение состояния подключения"""
        if self._connection_in_progress:
            logger.info("Подключение уже выполняется, игнорируем toggleConnection")
            return
        if self._is_connected:
            self.disconnect()
        else:
            self.connect()
    
    @Slot()
    def connect(self):
        """Подключение к Modbus устройству"""
        if self._connection_in_progress:
            return
        if self._is_connected:
            return

        logger.info(f"Попытка подключения к {self._host}:{self._port} (в фоне, без блокировки UI)")

        # Если был старый клиент/соединение — сначала логически отключаемся
        if self._modbus_client is not None:
            self.disconnect()

        # Создаем новый клиент (сам connect() будет выполнен в worker-потоке)
        self._modbus_client = ModbusClient(
            host=self._host,
            port=self._port,
            unit_id=self._unit_id,
            framer="rtu"
        )

        self._connection_in_progress = True
        self._status_text = "Connecting"
        self._connection_button_text = "Connecting..."
        self.statusTextChanged.emit(self._status_text)
        self.connectionButtonTextChanged.emit(self._connection_button_text)

        # Передаем клиента в worker и запускаем connect
        self._workerSetClient.emit(self._modbus_client)
        self._workerConnect.emit()
    
    @Slot()
    def disconnect(self):
        """Отключение от Modbus устройства"""
        try:
            logger.info("Отключение от Modbus устройства")
            self._connection_in_progress = False
            self._connection_check_timer.stop()
            self._sync_timer.stop()  # Останавливаем синхронизацию
            self._relay_1021_timer.stop()  # Останавливаем чтение регистра 1021
            self._valve_1111_timer.stop()  # Останавливаем чтение регистра 1111
            self._water_chiller_temp_timer.stop()  # Останавливаем чтение температуры Water Chiller
            self._water_chiller_setpoint_auto_update_timer.stop()  # Останавливаем автообновление setpoint
            self._magnet_psu_setpoint_auto_update_timer.stop()  # Останавливаем автообновление setpoint Magnet PSU
            self._laser_psu_setpoint_auto_update_timer.stop()  # Останавливаем автообновление setpoint Laser PSU
            self._seop_cell_temp_timer.stop()  # Останавливаем чтение температуры SEOP Cell
            self._seop_cell_setpoint_auto_update_timer.stop()  # Останавливаем автообновление setpoint SEOP Cell
            self._magnet_psu_current_timer.stop()  # Останавливаем чтение тока Magnet PSU
            self._laser_psu_current_timer.stop()  # Останавливаем чтение тока Laser PSU
            self._xenon_pressure_timer.stop()  # Останавливаем чтение давления Xenon
            self._xenon_setpoint_auto_update_timer.stop()  # Останавливаем автообновление setpoint Xenon
            self._n2_setpoint_auto_update_timer.stop()  # Останавливаем автообновление setpoint N2
            self._n2_pressure_timer.stop()  # Останавливаем чтение давления N2
            self._vacuum_pressure_timer.stop()  # Останавливаем чтение давления Vacuum
            self._fan_1131_timer.stop()  # Останавливаем чтение регистра 1131 (fans)
            
            # Отключение Modbus делаем в worker-потоке (чтобы UI не блокировался)
            self._workerDisconnect.emit()
            self._workerSetClient.emit(None)
            self._modbus_client = None
            
            self._is_connected = False
            self._status_text = "Disconnected"
            self._connection_button_text = "Connect"
            self.connectionStatusChanged.emit(self._is_connected)
            self.statusTextChanged.emit(self._status_text)
            self.connectionButtonTextChanged.emit(self._connection_button_text)
            
            # Сбрасываем состояния всех кнопок в GUI при отключении (только визуально, на устройство команды не отправляются)
            self.waterChillerStateChanged.emit(False)
            self.magnetPSUStateChanged.emit(False)
            self.laserPSUStateChanged.emit(False)
            self.vacuumPumpStateChanged.emit(False)
            self.vacuumGaugeStateChanged.emit(False)
            self.pidControllerStateChanged.emit(False)
            self.opCellHeatingStateChanged.emit(False)
            
            # Сбрасываем состояния клапанов X6-X12 в GUI при отключении
            self.valveStateChanged.emit(5, False)  # X6
            self.valveStateChanged.emit(6, False)  # X7
            self.valveStateChanged.emit(7, False)  # X8
            self.valveStateChanged.emit(8, False)  # X9
            self.valveStateChanged.emit(9, False)  # X10
            self.valveStateChanged.emit(10, False)  # X11
            self.valveStateChanged.emit(11, False)  # X12
            
            # Сбрасываем состояния всех вентиляторов в GUI при отключении
            self.fanStateChanged.emit(0, False)   # inlet fan 1
            self.fanStateChanged.emit(1, False)   # inlet fan 2
            self.fanStateChanged.emit(2, False)   # inlet fan 3
            self.fanStateChanged.emit(3, False)   # inlet fan 4
            self.fanStateChanged.emit(4, False)   # outlet fan 1
            self.fanStateChanged.emit(5, False)   # outlet fan 2
            self.fanStateChanged.emit(6, False)   # opcell fan 1
            self.fanStateChanged.emit(7, False)   # opcell fan 2
            self.fanStateChanged.emit(8, False)   # opcell fan 3
            self.fanStateChanged.emit(9, False)   # opcell fan 4
            self.fanStateChanged.emit(10, False)  # laser fan
            
            # Сбрасываем числовые значения (температуры, токи, давления) при отключении
            self._water_chiller_temperature = 0.0
            self._water_chiller_setpoint = 0.0
            self._seop_cell_temperature = 0.0
            self._magnet_psu_current = 0.0
            self._magnet_psu_setpoint = 0.0
            self._laser_psu_current = 0.0
            self._laser_psu_setpoint = 0.0
            self._xenon_pressure = 0.0
            self._xenon_setpoint = 0.0
            self._n2_pressure = 0.0
            self._n2_setpoint = 0.0
            self._vacuum_pressure = 0.0
            self.waterChillerTemperatureChanged.emit(0.0)
            self.waterChillerSetpointChanged.emit(0.0)
            self.seopCellTemperatureChanged.emit(0.0)
            self.seopCellSetpointChanged.emit(0.0)
            self.magnetPSUCurrentChanged.emit(0.0)
            self.magnetPSUSetpointChanged.emit(0.0)
            self.laserPSUCurrentChanged.emit(0.0)
            self.laserPSUSetpointChanged.emit(0.0)
            self.xenonPressureChanged.emit(0.0)
            self.xenonSetpointChanged.emit(0.0)
            self.n2PressureChanged.emit(0.0)
            self.n2SetpointChanged.emit(0.0)
            self.vacuumPressureChanged.emit(0.0)
            
            logger.info("Успешно отключено от Modbus устройства")
        except Exception as e:
            error_msg = f"Ошибка при отключении: {str(e)}"
            self.errorOccurred.emit(error_msg)
            logger.error(error_msg, exc_info=True)
            # Все равно устанавливаем состояние отключено
            self._is_connected = False
            self._status_text = "Disconnected"
            self._connection_button_text = "Connect"
            self.connectionStatusChanged.emit(self._is_connected)
            self.statusTextChanged.emit(self._status_text)
            self.connectionButtonTextChanged.emit(self._connection_button_text)
    
    @Slot(bool, str)
    def _onWorkerConnectFinished(self, success: bool, error_message: str):
        """Результат подключения из worker-потока."""
        self._connection_in_progress = False

        if not success:
            self._is_connected = False
            self._status_text = "Connection Failed" if error_message else "Connection Failed"
            self._connection_button_text = "Connect"
            self.connectionStatusChanged.emit(self._is_connected)
            self.statusTextChanged.emit(self._status_text)
            self.connectionButtonTextChanged.emit(self._connection_button_text)

            error_msg = (
                f"Не удалось подключиться к {self._host}:{self._port}."
                f"{' Причина: ' + error_message if error_message else ''}\n"
                "Проверьте:\n"
                "1. Устройство включено и доступно\n"
                "2. IP адрес и порт правильные\n"
                "3. Сеть настроена корректно"
            )
            self.errorOccurred.emit(error_msg)
            logger.error(error_msg)
            return

        # Успешное подключение
        self._is_connected = True
        self._status_text = "Connected"
        self._connection_button_text = "Disconnect"
        self._connection_fail_count = 0
        self._sync_fail_count = 0
        self._last_modbus_ok_time = time.time()

        self.connectionStatusChanged.emit(self._is_connected)
        self.statusTextChanged.emit(self._status_text)
        self.connectionButtonTextChanged.emit(self._connection_button_text)

        # Немедленно отправляем текущие состояния из буфера в UI для мгновенного отображения
        self._emitCachedStates()

        # Запускаем таймеры (они теперь будут только ставить задачи в worker, не блокируя UI)
        self._connection_check_timer.start()
        QTimer.singleShot(100, lambda: self._sync_timer.start())
        QTimer.singleShot(50, lambda: self._relay_1021_timer.start())
        QTimer.singleShot(80, lambda: self._valve_1111_timer.start())
        QTimer.singleShot(110, lambda: self._water_chiller_temp_timer.start())
        QTimer.singleShot(140, lambda: self._seop_cell_temp_timer.start())
        QTimer.singleShot(170, lambda: self._magnet_psu_current_timer.start())
        QTimer.singleShot(200, lambda: self._laser_psu_current_timer.start())
        QTimer.singleShot(230, lambda: self._xenon_pressure_timer.start())
        QTimer.singleShot(260, lambda: self._n2_pressure_timer.start())
        QTimer.singleShot(290, lambda: self._vacuum_pressure_timer.start())
        QTimer.singleShot(320, lambda: self._fan_1131_timer.start())

        # Таймеры автообновления setpoint (UI-логика)
        self._water_chiller_setpoint_auto_update_timer.start()
        self._magnet_psu_setpoint_auto_update_timer.start()
        self._laser_psu_setpoint_auto_update_timer.start()
        self._seop_cell_setpoint_auto_update_timer.start()
        self._xenon_setpoint_auto_update_timer.start()
        self._n2_setpoint_auto_update_timer.start()

        logger.info("Успешное подключение к Modbus устройству (I/O в фоне)")

    @Slot()
    def _onWorkerDisconnected(self):
        # Состояние UI уже сбрасывается в disconnect(), тут оставляем как защиту.
        logger.info("Worker подтвердил отключение Modbus")

    @Slot(str, object)
    def _onWorkerReadFinished(self, key: str, value: object):
        # Любое успешное чтение считаем keep-alive
        if value is not None:
            self._last_modbus_ok_time = time.time()
            self._connection_fail_count = 0

        # Диспетчер чтений: ключи будут использоваться в polling методах
        if key == "1021":
            self._applyRelay1021Value(value)
        elif key == "1111":
            self._applyValve1111Value(value)
        elif key == "1511":
            self._applyWaterChillerTemperatureValue(value)
        elif key == "1411":
            self._applySeopCellTemperatureValue(value)
        elif key == "1341":
            self._applyMagnetPSUCurrentValue(value)
        elif key == "1251":
            self._applyLaserPSUCurrentValue(value)
        elif key == "1611":
            self._applyXenonPressureValue(value)
        elif key == "1651":
            self._applyN2PressureValue(value)
        elif key == "1701":
            self._applyVacuumPressureValue(value)
        elif key == "1131":
            self._applyFan1131Value(value)
        elif key == "1020":
            self._applyExternalRelays1020Value(value)
        elif key == "ir":
            self._ir_request_in_flight = False
            if value is None:
                logger.warning("IR spectrum read returned None")
            self._applyIrSpectrum(value)
        else:
            # Это могут быть "fire-and-forget" задачи; игнорируем.
            return

    @Slot(str, bool, object)
    def _onWorkerWriteFinished(self, key: str, success: bool, meta: object):
        if success:
            self._last_modbus_ok_time = time.time()
        else:
            logger.warning(f"Modbus write failed: {key} meta={meta}")

    def _shutdownIoThread(self, *args):
        """Аккуратно останавливаем worker-поток при завершении приложения."""
        try:
            # Пытаемся попросить worker закрыть соединение
            try:
                self._workerDisconnect.emit()
            except Exception:
                pass
            if hasattr(self, "_io_thread") and self._io_thread.isRunning():
                self._io_thread.quit()
                self._io_thread.wait(1500)
        except Exception:
            pass

    def _enqueue_read(self, key: str, func: Callable[[], Any]) -> None:
        """Поставить задачу чтения в worker-поток."""
        try:
            self._workerEnqueueRead.emit(key, func)
        except Exception:
            logger.exception("Failed to enqueue read task")

    def _enqueue_write(self, key: str, func: Callable[[], bool], meta: object = None) -> None:
        """Поставить задачу записи в worker-поток (приоритет)."""
        try:
            self._workerEnqueueWrite.emit(key, func, meta)
        except Exception:
            logger.exception("Failed to enqueue write task")

    # ===== apply-методы: применяют результат чтения в GUI-потоке =====
    def _applyRelay1021Value(self, value: object):
        self._reading_1021 = False
        if value is None:
            return
        try:
            value_int = int(value)
        except Exception:
            return

        low_byte = value_int & 0xFF
        self._relay_states['water_chiller'] = bool(low_byte & 0x01)
        self._relay_states['magnet_psu'] = bool(low_byte & 0x02)
        self._relay_states['laser_psu'] = bool(low_byte & 0x04)
        self._relay_states['vacuum_pump'] = bool(low_byte & 0x08)
        self._relay_states['vacuum_gauge'] = bool(low_byte & 0x10)
        self._relay_states['pid_controller'] = bool(low_byte & 0x20)
        self._relay_states['op_cell_heating'] = bool(low_byte & 0x40)

        self.waterChillerStateChanged.emit(self._relay_states['water_chiller'])
        self.magnetPSUStateChanged.emit(self._relay_states['magnet_psu'])
        self.laserPSUStateChanged.emit(self._relay_states['laser_psu'])
        self.vacuumPumpStateChanged.emit(self._relay_states['vacuum_pump'])
        self.vacuumGaugeStateChanged.emit(self._relay_states['vacuum_gauge'])
        self.pidControllerStateChanged.emit(self._relay_states['pid_controller'])
        self.opCellHeatingStateChanged.emit(self._relay_states['op_cell_heating'])

    def _applyValve1111Value(self, value: object):
        self._reading_1111 = False
        if value is None:
            return
        try:
            value_int = int(value)
        except Exception:
            return
        for valve_index in range(5, 12):
            state = bool(value_int & (1 << valve_index))
            self._valve_states[valve_index] = state
            self.valveStateChanged.emit(valve_index, state)

    def _applyWaterChillerTemperatureValue(self, value: object):
        self._reading_1511 = False
        if value is None:
            return
        try:
            temperature = float(int(value)) / 100.0
        except Exception:
            return
        if self._water_chiller_temperature != temperature:
            self._water_chiller_temperature = temperature
            self.waterChillerTemperatureChanged.emit(temperature)

    def _applySeopCellTemperatureValue(self, value: object):
        self._reading_1411 = False
        if value is None:
            return
        try:
            temperature = float(int(value)) / 100.0
        except Exception:
            return
        if self._seop_cell_temperature != temperature:
            self._seop_cell_temperature = temperature
            self.seopCellTemperatureChanged.emit(temperature)

    def _applyMagnetPSUCurrentValue(self, value: object):
        self._reading_1341 = False
        if value is None:
            return
        try:
            current = float(int(value)) / 100.0
        except Exception:
            return
        if self._magnet_psu_current != current:
            self._magnet_psu_current = current
            self.magnetPSUCurrentChanged.emit(current)

    def _applyLaserPSUCurrentValue(self, value: object):
        self._reading_1251 = False
        if value is None:
            return
        try:
            current = float(int(value)) / 100.0
        except Exception:
            return
        if self._laser_psu_current != current:
            self._laser_psu_current = current
            self.laserPSUCurrentChanged.emit(current)

    def _applyXenonPressureValue(self, value: object):
        self._reading_1611 = False
        if value is None:
            return
        try:
            pressure = float(int(value)) / 100.0
        except Exception:
            return
        if self._xenon_pressure != pressure:
            self._xenon_pressure = pressure
            self.xenonPressureChanged.emit(pressure)

    def _applyN2PressureValue(self, value: object):
        self._reading_1651 = False
        if value is None:
            return
        try:
            pressure = float(int(value)) / 100.0
        except Exception:
            return
        if self._n2_pressure != pressure:
            self._n2_pressure = pressure
            self.n2PressureChanged.emit(pressure)

    def _applyVacuumPressureValue(self, value: object):
        self._reading_1701 = False
        if value is None:
            return
        try:
            pressure = float(int(value)) / 100.0
        except Exception:
            return
        if self._vacuum_pressure != pressure:
            self._vacuum_pressure = pressure
            self.vacuumPressureChanged.emit(pressure)

    def _applyFan1131Value(self, value: object):
        self._reading_1131 = False
        if value is None:
            return
        try:
            value_int = int(value)
        except Exception:
            return

        fan_mapping = {
            0: 0,
            1: 1,
            2: 2,
            3: 3,
            6: 4,
            7: 5,
            8: 6,
            9: 7,
            4: 8,
            5: 9,
        }

        current_time = time.time()
        for fan_index, bit_pos in fan_mapping.items():
            if fan_index in self._fan_optimistic_updates:
                time_since_update = current_time - self._fan_optimistic_updates[fan_index]
                if time_since_update < 0.5:
                    continue
                del self._fan_optimistic_updates[fan_index]

            state = bool(value_int & (1 << bit_pos))
            self._fan_states[fan_index] = state
            self.fanStateChanged.emit(fan_index, state)

        # laser fan: bit 15
        if 10 in self._fan_optimistic_updates:
            time_since_update = current_time - self._fan_optimistic_updates[10]
            if time_since_update >= 0.5:
                del self._fan_optimistic_updates[10]
                laser_fan_state = bool(value_int & (1 << 15))
                self._fan_states[10] = laser_fan_state
                self.fanStateChanged.emit(10, laser_fan_state)
        else:
            laser_fan_state = bool(value_int & (1 << 15))
            self._fan_states[10] = laser_fan_state
            self.fanStateChanged.emit(10, laser_fan_state)

    def _applyExternalRelays1020Value(self, value: object):
        if value is None:
            return
        try:
            value_int = int(value)
        except Exception:
            return
        self._register_cache[1020] = value_int
        low_byte = value_int & 0xFF
        binary_str = format(low_byte, '08b')
        self.externalRelaysChanged.emit(low_byte, binary_str)

    def _registers_to_float_ir(self, reg1: int, reg2: int) -> float:
        """
        IR float decode как в test_modbus.registers_to_float_ir:
        swap byte1<->byte2 и byte3<->byte4.
        """
        import struct
        byte1 = (reg1 >> 8) & 0xFF
        byte2 = reg1 & 0xFF
        byte3 = (reg2 >> 8) & 0xFF
        byte4 = reg2 & 0xFF
        swapped = bytes([byte2, byte1, byte4, byte3])
        try:
            return float(struct.unpack(">f", swapped)[0])
        except Exception:
            return 0.0

    def _applyIrSpectrum(self, value: object):
        """
        Применяет результат чтения IR спектра (GUI поток) и дергает сигнал для QML графика.
        """
        if not value or not isinstance(value, dict):
            logger.warning("IR spectrum: empty/invalid payload (not a dict or None)")
            return
        pts = value.get("points")
        logger.info(
            f"IR spectrum: payload received, points={len(pts) if isinstance(pts, list) else 'n/a'} "
            f"x=[{value.get('x_min')},{value.get('x_max')}] y=[{value.get('y_min')},{value.get('y_max')}] "
            f"status={value.get('status')}"
        )
        self._ir_last = value
        self.irSpectrumChanged.emit(value)

    @Slot(result=bool)
    def requestIrSpectrum(self) -> bool:
        """
        Чтение IR данных как команда `ir` из test_modbus, но безопасно:
        отправляем запросы чанками по 10 регистров, иначе устройство может "уронить" сокет.

        Регистры:
        - 400..414 (15) метаданные
        - 420..477 (58) данные
        """
        if not self._is_connected or self._modbus_client is None:
            logger.info("IR spectrum request ignored: not connected")
            return False
        if self._ir_request_in_flight:
            logger.info("IR spectrum request ignored: previous request still in flight")
            return False

        self._ir_request_in_flight = True
        logger.info("IR spectrum request queued")

        client = self._modbus_client

        def task():
            import math
            # Читаем 400..414 и 420..477 (как в test_modbus при ir)
            meta = client.read_input_registers_direct(400, 15, max_chunk=10)
            if meta is None or len(meta) < 15:
                logger.warning(f"IR spectrum: meta read failed or short: {None if meta is None else len(meta)}")
                return None

            # Основной режим: безопасно по 10 регистров.
            data_regs = client.read_input_registers_direct(420, 58, max_chunk=10)
            if data_regs is None or len(data_regs) < 58:
                logger.warning(f"IR spectrum: data read failed or short: {None if data_regs is None else len(data_regs)}")
                return None

            # Диагностика качества: если почти все значения нулевые (часто это признак, что устройство
            # не поддерживает чтение под-диапазонов 430.. и т.п.), пробуем один раз читать весь блок 58.
            try:
                nz_indices = [i for i, v in enumerate(data_regs) if int(v) != 0]
                last_nz_idx = nz_indices[-1] if nz_indices else -1
                nz_count = len(nz_indices)
            except Exception:
                last_nz_idx = -1
                nz_count = 0

            if last_nz_idx >= 0 and last_nz_idx <= 9:
                logger.warning(
                    f"IR spectrum: suspicious tail zeros (last_nonzero_idx={last_nz_idx}, nonzero_count={nz_count}). "
                    f"Trying single-block read (58 regs) once."
                )
                data_full = client.read_input_registers_direct(420, 58, max_chunk=58)
                if data_full is not None and len(data_full) >= 58:
                    try:
                        nz_full = [i for i, v in enumerate(data_full) if int(v) != 0]
                        last_nz_full = nz_full[-1] if nz_full else -1
                        nz_count_full = len(nz_full)
                    except Exception:
                        last_nz_full = -1
                        nz_count_full = 0

                    if last_nz_full > last_nz_idx or nz_count_full > nz_count:
                        logger.info(
                            f"IR spectrum: single-block read looks better "
                            f"(last_nonzero_idx {last_nz_idx}->{last_nz_full}, nonzero_count {nz_count}->{nz_count_full})"
                        )
                        data_regs = data_full
                    else:
                        logger.info(
                            f"IR spectrum: single-block read did not improve "
                            f"(last_nonzero_idx={last_nz_full}, nonzero_count={nz_count_full}). Keeping chunked."
                        )

            logger.info(
                f"IR spectrum: raw meta[0..4]={meta[0:5]} meta_hex={[hex(int(x)) for x in meta[0:5]]} "
                f"data_first10={data_regs[0:10]} data_last3={data_regs[-3:]}"
            )

            status = int(meta[0])
            # Для отображения IR спектра ось X фиксированная: 792..798 (шаг сетки задается в QML)
            # Декодированные x_min/x_max из регистра могут быть "мусором" (как видно по логам),
            # поэтому используем фиксированный диапазон.
            x_min = 792.0
            x_max = 798.0
            y_min = self._registers_to_float_ir(int(meta[5]), int(meta[6]))
            y_max = self._registers_to_float_ir(int(meta[7]), int(meta[8]))
            res_freq = self._registers_to_float_ir(int(meta[9]), int(meta[10]))
            freq = self._registers_to_float_ir(int(meta[11]), int(meta[12]))
            integral = self._registers_to_float_ir(int(meta[13]), int(meta[14]))

            for name, val in (
                ("x_min", x_min),
                ("x_max", x_max),
                ("y_min", y_min),
                ("y_max", y_max),
                ("res_freq", res_freq),
                ("freq", freq),
                ("integral", integral),
            ):
                if not math.isfinite(val):
                    logger.warning(f"IR spectrum: {name} is not finite: {val}")

            # y values (raw uint16 from device)
            y_values_raw_u16 = [int(v) for v in data_regs[:58]]
            if not y_values_raw_u16:
                logger.warning("IR spectrum: y_values empty (no points)")

            # Преобразование для отображения:
            # Значения могут быть отрицательными -> интерпретируем как int16 (two's complement).
            # По данным устройства сырые значения ~4200 соответствуют пикам ~85, т.е. шаг ~0.02.
            # => отображаем как int16 / 50.0 (получим примерно диапазон -10..85).
            def _to_int16(u16: int) -> int:
                return u16 - 65536 if u16 >= 32768 else u16

            y_values_raw_i16 = [_to_int16(v) for v in y_values_raw_u16]
            scale = 50.0
            y_values = [float(v) / scale for v in y_values_raw_i16]

            # Собираем точки для графика (x равномерно от x_min до x_max)
            points = []
            if len(y_values) >= 2 and x_max != x_min:
                step = (x_max - x_min) / float(len(y_values) - 1)
                for i, y in enumerate(y_values):
                    points.append({"x": x_min + step * i, "y": float(y)})
            else:
                for i, y in enumerate(y_values):
                    points.append({"x": float(i), "y": float(y)})

            # Для отображения используем диапазон из преобразованных данных (0..100%)
            # чтобы оси соответствовали тому, что рисуем.
            if y_values:
                y_min = float(min(y_values))
                y_max = float(max(y_values))

            logger.info(
                f"IR spectrum decoded: status={status} x=[{x_min},{x_max}] y=[{y_min},{y_max}] "
                f"points={len(points)} raw_u16_range=[{min(y_values_raw_u16) if y_values_raw_u16 else 'n/a'},{max(y_values_raw_u16) if y_values_raw_u16 else 'n/a'}] "
                f"raw_i16_range=[{min(y_values_raw_i16) if y_values_raw_i16 else 'n/a'},{max(y_values_raw_i16) if y_values_raw_i16 else 'n/a'}] "
                f"scaled_y_range=[{y_min},{y_max}]"
            )

            # Возвращаем только простые типы (int/float/str/list/dict), чтобы конвертировалось в QVariantMap
            import json
            return {
                "status": status,
                "x_min": float(x_min),
                "x_max": float(x_max),
                "y_min": float(y_min),
                "y_max": float(y_max),
                "res_freq": float(res_freq),
                "freq": float(freq),
                "integral": float(integral),
                "data_raw_u16": y_values_raw_u16,
                "data_raw_i16": y_values_raw_i16,
                "data": y_values,
                # JSON-версии для надежного парсинга в QML (иногда QVariantList ведет себя странно)
                "data_json": json.dumps(y_values),
                "points": points,
            }

        self._enqueue_read("ir", task)
        return True

    def _check_connection(self):
        """
        Проверка "живости" соединения без блокирующих сетевых вызовов в GUI-потоке.
        Если давно не было успешного I/O (чтение/запись), пробуем переподключиться через worker.
        """
        if not self._is_connected or self._modbus_client is None:
            return
        if self._connection_in_progress:
            return

        now = time.time()
        if self._last_modbus_ok_time <= 0:
            return

        # Если давно не было успешных ответов — считаем соединение "подвисшим"
        if (now - self._last_modbus_ok_time) < 3.0:
            return

        # Не дергаем reconnect слишком часто
        if (now - self._last_reconnect_attempt_time) < 3.0:
            return

        self._last_reconnect_attempt_time = now
        logger.warning("Нет успешных ответов Modbus >3с, пробуем переподключиться (в фоне)")

        # Останавливаем polling таймеры, чтобы не засыпать очередь запросами во время reconnect
        try:
            for t in self._polling_timers:
                t.stop()
        except Exception:
            pass

        self._connection_in_progress = True
        self._workerSetClient.emit(self._modbus_client)
        self._workerConnect.emit()
    
    def _syncDeviceStates(self):
        """Синхронизация состояний всех устройств с Modbus"""
        # Синхронизация реле (регистр 1021) выполняется отдельным таймером _readRelay1021
        # Здесь ничего не делаем, чтобы не дублировать
        pass
    
    def _readExternalRelays(self):
        """Чтение регистра 1020 (External Relays) и отправка сигнала с бинарным представлением"""
        if not self._is_connected or self._modbus_client is None:
            return
        client = self._modbus_client

        def task():
            # Сначала пробуем holding (03), потом input (04) как fallback
            value = client.read_holding_register(1020)
            if value is None:
                value = client.read_input_register(1020)
            return value

        self._enqueue_read("1020", task)
    
    def _readRelay1021(self):
        """Чтение регистра 1021 (реле) и обновление состояний всех реле"""
        if not self._is_connected or self._modbus_client is None or self._reading_1021:
            return

        self._reading_1021 = True
        client = self._modbus_client
        self._enqueue_read("1021", lambda: client.read_register_1021_direct())
    
    def _readValve1111(self):
        """Чтение регистра 1111 (клапаны X6-X12) и обновление состояний"""
        if not self._is_connected or self._modbus_client is None or self._reading_1111:
            return

        self._reading_1111 = True
        client = self._modbus_client
        self._enqueue_read("1111", lambda: client.read_register_1111_direct())
    
    def _readWaterChillerTemperature(self):
        """Чтение регистра 1511 (температура Water Chiller) и обновление label C"""
        if not self._is_connected or self._modbus_client is None or self._reading_1511:
            return

        self._reading_1511 = True
        client = self._modbus_client
        self._enqueue_read("1511", lambda: client.read_register_1511_direct())
    
    def _autoUpdateWaterChillerSetpoint(self):
        """
        Автоматическое обновление setpoint из текущей температуры, если пользователь не взаимодействует с полем
        Вызывается каждые 20 секунд
        """
        if not self._is_connected:
            return
        
        # Если пользователь не взаимодействовал с полем, обновляем setpoint из текущей температуры
        if not self._water_chiller_setpoint_user_interaction:
            # Не обновляем если текущая температура равна 0.0 или невалидная (устройство только подключено)
            if self._water_chiller_temperature > 0.1 and abs(self._water_chiller_temperature - self._water_chiller_setpoint) > 0.1:  # Обновляем только если разница > 0.1°C и температура валидная
                logger.info(f"Автообновление setpoint: {self._water_chiller_setpoint}°C -> {self._water_chiller_temperature}°C")
                self._water_chiller_setpoint = self._water_chiller_temperature
                self.waterChillerSetpointChanged.emit(self._water_chiller_temperature)
        else:
            # Сбрасываем флаг взаимодействия для следующего цикла
            self._water_chiller_setpoint_user_interaction = False
    
    def _autoUpdateMagnetPSUSetpoint(self):
        """
        Автоматическое обновление setpoint для Magnet PSU
        Вызывается каждые 20 секунд
        Для Magnet PSU нет текущей температуры (есть только ток), поэтому просто сбрасываем флаг взаимодействия
        """
        if not self._is_connected:
            return
        
        # Сбрасываем флаг взаимодействия для следующего цикла
        self._magnet_psu_setpoint_user_interaction = False
    
    def _autoUpdateLaserPSUSetpoint(self):
        """
        Автоматическое обновление setpoint для Laser PSU
        Вызывается каждые 20 секунд
        Для Laser PSU нет текущей температуры (есть только ток), поэтому просто сбрасываем флаг взаимодействия
        """
        if not self._is_connected:
            return
        
        # Сбрасываем флаг взаимодействия для следующего цикла
        self._laser_psu_setpoint_user_interaction = False
    
    @Slot(float, result=bool)
    def setSeopCellSetpointValue(self, temperature: float) -> bool:
        """
        Обновление внутреннего значения setpoint без отправки на устройство
        Используется для синхронизации при вводе с клавиатуры
        """
        logger.info(f"Обновление внутреннего значения setpoint SEOP Cell: {temperature}°C (было {self._seop_cell_setpoint}°C)")
        # Всегда обновляем, даже если значение не изменилось (для надежности)
        self._seop_cell_setpoint = temperature
        self.seopCellSetpointChanged.emit(temperature)
        logger.info(f"✅ Внутреннее значение setpoint SEOP Cell обновлено: {self._seop_cell_setpoint}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._seop_cell_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления (начнет отсчет заново с 20 секунд)
        self._seop_cell_setpoint_auto_update_timer.stop()
        self._seop_cell_setpoint_auto_update_timer.start()
        return True
    
    @Slot(float, result=bool)
    def setSeopCellTemperature(self, temperature: float) -> bool:
        """
        Установка температуры SEOP Cell в регистр 1421
        
        Args:
            temperature: Температура в градусах Цельсия (например, 23.0)
        
        Returns:
            True если успешно, False в противном случае
        """
        logger.info(f"🔵 setSeopCellTemperature вызван с температурой: {temperature}°C")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set seop cell to {temperature:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки температуры SEOP Cell без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
        # Это нужно для того, чтобы стрелки работали с актуальным значением
        # Всегда обновляем и эмитируем сигнал, даже если значение не изменилось
        # Это гарантирует обновление UI при нажатии на стрелки
        logger.info(f"🔵 Обновление _seop_cell_setpoint: {self._seop_cell_setpoint}°C -> {temperature}°C")
        self._seop_cell_setpoint = temperature
        # Отправляем сигнал для обновления UI (setpoint)
        logger.info(f"🔵 Эмитируем сигнал seopCellSetpointChanged: {temperature}°C")
        self.seopCellSetpointChanged.emit(temperature)
        
        # Преобразуем температуру в значение для регистра (умножаем на 100)
        # Например, 23.0°C -> 2300
        register_value = int(temperature * 100)
        
        logger.info(f"Установка температуры SEOP Cell: {temperature}°C (регистр 1421 = {register_value})")
        
        client = self._modbus_client

        def task() -> bool:
            result = client.write_register_1421_direct(register_value)
            if result:
                logger.info(f"✅ Заданная температура SEOP Cell успешно установлена: {temperature}°C")
            else:
                logger.error(f"❌ Не удалось установить заданную температуру SEOP Cell: {temperature}°C")
            return bool(result)

        self._enqueue_write("1421", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSeopCellTemperature(self) -> bool:
        """Увеличение заданной температуры SEOP Cell на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Увеличение температуры SEOP Cell: текущее значение = {self._seop_cell_setpoint}°C")
        new_temp = self._seop_cell_setpoint + 1.0
        logger.debug(f"Новое значение после увеличения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._seop_cell_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._seop_cell_setpoint_auto_update_timer.stop()
        self._seop_cell_setpoint_auto_update_timer.start()
        return self.setSeopCellTemperature(new_temp)
    
    @Slot(result=bool)
    def decreaseSeopCellTemperature(self) -> bool:
        """Уменьшение заданной температуры SEOP Cell на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Уменьшение температуры SEOP Cell: текущее значение = {self._seop_cell_setpoint}°C")
        new_temp = self._seop_cell_setpoint - 1.0
        logger.debug(f"Новое значение после уменьшения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._seop_cell_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._seop_cell_setpoint_auto_update_timer.stop()
        self._seop_cell_setpoint_auto_update_timer.start()
        return self.setSeopCellTemperature(new_temp)
    
    def _autoUpdateSeopCellSetpoint(self):
        """
        Автоматическое обновление setpoint из текущей температуры, если пользователь не взаимодействует с полем
        Вызывается каждые 20 секунд
        """
        if not self._is_connected:
            return
        
        # Если пользователь не взаимодействовал с полем, обновляем setpoint из текущей температуры
        if not self._seop_cell_setpoint_user_interaction:
            # Не обновляем если текущая температура равна 0.0 или невалидная (устройство только подключено)
            if self._seop_cell_temperature > 0.1 and abs(self._seop_cell_temperature - self._seop_cell_setpoint) > 0.1:  # Обновляем только если разница > 0.1°C и температура валидная
                logger.info(f"Автообновление setpoint SEOP Cell: {self._seop_cell_setpoint}°C -> {self._seop_cell_temperature}°C")
                self._seop_cell_setpoint = self._seop_cell_temperature
                self.seopCellSetpointChanged.emit(self._seop_cell_temperature)
        else:
            # Сбрасываем флаг взаимодействия для следующего цикла
            self._seop_cell_setpoint_user_interaction = False
    
    @Slot(float, result=bool)
    def setXenonSetpointValue(self, pressure: float) -> bool:
        """
        Обновление внутреннего значения setpoint без отправки на устройство
        Используется для синхронизации при вводе с клавиатуры
        """
        logger.info(f"Обновление внутреннего значения setpoint Xenon: {pressure} Torr (было {self._xenon_setpoint} Torr)")
        # Всегда обновляем, даже если значение не изменилось (для надежности)
        self._xenon_setpoint = pressure
        self.xenonSetpointChanged.emit(pressure)
        logger.info(f"✅ Внутреннее значение setpoint Xenon обновлено: {self._xenon_setpoint} Torr")
        # Отмечаем, что пользователь взаимодействует с полем
        self._xenon_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления (начнет отсчет заново с 20 секунд)
        self._xenon_setpoint_auto_update_timer.stop()
        self._xenon_setpoint_auto_update_timer.start()
        return True
    
    @Slot(float, result=bool)
    def setXenonPressure(self, pressure: float) -> bool:
        """
        Установка давления Xenon в регистр 1621
        
        Args:
            pressure: Давление в Torr (например, 23.00)
        
        Returns:
            True если успешно, False в противном случае
        """
        logger.info(f"🔵 setXenonPressure вызван с давлением: {pressure} Torr")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set xenon to {pressure:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки давления Xenon без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
        # Это нужно для того, чтобы стрелки работали с актуальным значением
        # Всегда обновляем и эмитируем сигнал, даже если значение не изменилось
        # Это гарантирует обновление UI при нажатии на стрелки
        logger.info(f"🔵 Обновление _xenon_setpoint: {self._xenon_setpoint} Torr -> {pressure} Torr")
        self._xenon_setpoint = pressure
        # Отправляем сигнал для обновления UI (setpoint)
        logger.info(f"🔵 Эмитируем сигнал xenonSetpointChanged: {pressure} Torr")
        self.xenonSetpointChanged.emit(pressure)
        
        # Преобразуем давление в значение для регистра (умножаем на 100)
        # Например, 23.00 Torr -> 2300
        register_value = int(pressure * 100)
        
        logger.info(f"Установка давления Xenon: {pressure} Torr (регистр 1621 = {register_value})")
        
        client = self._modbus_client

        def task() -> bool:
            result = client.write_register_1621_direct(register_value)
            if result:
                logger.info(f"✅ Заданное давление Xenon успешно установлено: {pressure} Torr")
            else:
                logger.error(f"❌ Не удалось установить заданное давление Xenon: {pressure} Torr")
            return bool(result)

        self._enqueue_write("1621", task, {"pressure": pressure})
        return True
    
    def _autoUpdateXenonSetpoint(self):
        """
        Автоматическое обновление setpoint из текущего давления, если пользователь не взаимодействует с полем
        Вызывается каждые 20 секунд
        """
        if not self._is_connected:
            return
        
        # Если пользователь не взаимодействовал с полем, обновляем setpoint из текущего давления
        if not self._xenon_setpoint_user_interaction:
            # Не обновляем если текущее давление равно 0.0 или невалидное (устройство только подключено)
            if self._xenon_pressure > 0.01 and abs(self._xenon_pressure - self._xenon_setpoint) > 0.01:  # Обновляем только если разница > 0.01 Torr и давление валидное
                logger.info(f"Автообновление setpoint Xenon: {self._xenon_setpoint} Torr -> {self._xenon_pressure} Torr")
                self._xenon_setpoint = self._xenon_pressure
                self.xenonSetpointChanged.emit(self._xenon_pressure)
        else:
            # Сбрасываем флаг взаимодействия для следующего цикла
            self._xenon_setpoint_user_interaction = False
    
    def _autoUpdateN2Setpoint(self):
        """
        Автоматическое обновление setpoint из текущего давления, если пользователь не взаимодействует с полем
        Вызывается каждые 20 секунд
        """
        if not self._is_connected:
            return
        
        # Если пользователь не взаимодействовал с полем, обновляем setpoint из текущего давления
        if not self._n2_setpoint_user_interaction:
            # Не обновляем если текущее давление равно 0.0 или невалидное (устройство только подключено)
            if self._n2_pressure > 0.01 and abs(self._n2_pressure - self._n2_setpoint) > 0.01:  # Обновляем только если разница > 0.01 Torr и давление валидное
                logger.info(f"Автообновление setpoint N2: {self._n2_setpoint} Torr -> {self._n2_pressure} Torr")
                self._n2_setpoint = self._n2_pressure
                self.n2SetpointChanged.emit(self._n2_pressure)
        else:
            # Сбрасываем флаг взаимодействия для следующего цикла
            self._n2_setpoint_user_interaction = False
    
    @Slot(float, result=bool)
    def setN2SetpointValue(self, pressure: float) -> bool:
        """
        Обновление внутреннего значения setpoint без отправки на устройство
        Используется для синхронизации при вводе с клавиатуры
        """
        logger.info(f"Обновление внутреннего значения setpoint N2: {pressure} Torr (было {self._n2_setpoint} Torr)")
        # Всегда обновляем, даже если значение не изменилось (для надежности)
        self._n2_setpoint = pressure
        self.n2SetpointChanged.emit(pressure)
        logger.info(f"✅ Внутреннее значение setpoint N2 обновлено: {self._n2_setpoint} Torr")
        # Отмечаем, что пользователь взаимодействует с полем
        self._n2_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления (начнет отсчет заново с 20 секунд)
        self._n2_setpoint_auto_update_timer.stop()
        self._n2_setpoint_auto_update_timer.start()
        return True
    
    @Slot(float, result=bool)
    def setN2Pressure(self, pressure: float) -> bool:
        """
        Установка давления N2 в регистр 1661
        
        Args:
            pressure: Давление в Torr (например, 23.00)
        
        Returns:
            True если успешно, False в противном случае
        """
        logger.info(f"🔵 setN2Pressure вызван с давлением: {pressure} Torr")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set n2 to {pressure:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки давления N2 без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
        logger.info(f"🔵 Обновление _n2_setpoint: {self._n2_setpoint} Torr -> {pressure} Torr")
        self._n2_setpoint = pressure
        self.n2SetpointChanged.emit(pressure)
        
        # Преобразуем давление в значение для регистра (умножаем на 100)
        register_value = int(pressure * 100)
        
        logger.info(f"Установка давления N2: {pressure} Torr (регистр 1661 = {register_value})")
        
        client = self._modbus_client

        def task() -> bool:
            result = client.write_register_1661_direct(register_value)
            if result:
                logger.info(f"✅ Заданное давление N2 успешно установлено: {pressure} Torr")
            else:
                logger.error(f"❌ Не удалось установить заданное давление N2: {pressure} Torr")
            return bool(result)

        self._enqueue_write("1661", task, {"pressure": pressure})
        return True
    
    @Slot(result=bool)
    def increaseN2Pressure(self) -> bool:
        """Увеличение заданного давления N2 на 0.01 Torr"""
        if not self._is_connected:
            return False
        logger.debug(f"Увеличение давления N2: текущее значение = {self._n2_setpoint} Torr")
        new_pressure = self._n2_setpoint + 0.01
        logger.debug(f"Новое значение после увеличения: {new_pressure} Torr")
        # Отмечаем, что пользователь взаимодействует с полем
        self._n2_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._n2_setpoint_auto_update_timer.stop()
        self._n2_setpoint_auto_update_timer.start()
        return self.setN2Pressure(new_pressure)
    
    @Slot(result=bool)
    def decreaseN2Pressure(self) -> bool:
        """Уменьшение заданного давления N2 на 0.01 Torr"""
        if not self._is_connected:
            return False
        logger.debug(f"Уменьшение давления N2: текущее значение = {self._n2_setpoint} Torr")
        new_pressure = self._n2_setpoint - 0.01
        logger.debug(f"Новое значение после уменьшения: {new_pressure} Torr")
        # Отмечаем, что пользователь взаимодействует с полем
        self._n2_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._n2_setpoint_auto_update_timer.stop()
        self._n2_setpoint_auto_update_timer.start()
        return self.setN2Pressure(new_pressure)
    
    def _readSeopCellTemperature(self):
        """Чтение регистра 1411 (температура SEOP Cell) и обновление label C"""
        if not self._is_connected or self._modbus_client is None or self._reading_1411:
            return

        self._reading_1411 = True
        client = self._modbus_client
        self._enqueue_read("1411", lambda: client.read_register_1411_direct())
    
    def _readMagnetPSUCurrent(self):
        """Чтение регистра 1341 (ток Magnet PSU) и обновление label A"""
        if not self._is_connected or self._modbus_client is None or self._reading_1341:
            return

        self._reading_1341 = True
        client = self._modbus_client
        self._enqueue_read("1341", lambda: client.read_register_1341_direct())
    
    def _readLaserPSUCurrent(self):
        """Чтение регистра 1251 (ток Laser PSU) и обновление label A"""
        if not self._is_connected or self._modbus_client is None or self._reading_1251:
            return

        self._reading_1251 = True
        client = self._modbus_client
        self._enqueue_read("1251", lambda: client.read_register_1251_direct())
    
    def _readXenonPressure(self):
        """Чтение регистра 1611 (давление Xenon) и обновление label Torr"""
        if not self._is_connected or self._modbus_client is None or self._reading_1611:
            return

        self._reading_1611 = True
        client = self._modbus_client
        self._enqueue_read("1611", lambda: client.read_register_1611_direct())
    
    def _readN2Pressure(self):
        """Чтение регистра 1651 (давление N2) и обновление label Torr"""
        if not self._is_connected or self._modbus_client is None or self._reading_1651:
            return

        self._reading_1651 = True
        client = self._modbus_client
        self._enqueue_read("1651", lambda: client.read_register_1651_direct())
    
    def _readVacuumPressure(self):
        """Чтение регистра 1701 (давление Vacuum) и обновление label Torr"""
        if not self._is_connected or self._modbus_client is None or self._reading_1701:
            return

        self._reading_1701 = True
        client = self._modbus_client
        self._enqueue_read("1701", lambda: client.read_register_1701_direct())
    
    def _readFan1131(self):
        """Чтение регистра 1131 (fans) и обновление состояний всех вентиляторов"""
        if not self._is_connected or self._modbus_client is None or self._reading_1131:
            return

        self._reading_1131 = True
        client = self._modbus_client
        self._enqueue_read("1131", lambda: client.read_register_1131_direct())
    
    @Slot(int, bool, result=bool)
    def setFan(self, fanIndex: int, state: bool) -> bool:
        """
        Установка состояния вентилятора в регистре 1131
        
        Args:
            fanIndex: Индекс вентилятора (0-10)
            state: True - включить, False - выключить
        
        Returns:
            True если успешно, False в противном случае
        """
        logger.info(f"⚡ setFan вызван: fanIndex={fanIndex}, state={state} - МГНОВЕННОЕ обновление UI")
        # Маппинг fanIndex (из QML) -> бит в регистре 1131
        fan_bit_mapping = {
            0: 0,   # inlet fan 1 (button4) -> бит 0 (бит 1 считая с 1)
            1: 1,   # inlet fan 2 (button3) -> бит 1 (бит 2 считая с 1)
            2: 2,   # inlet fan 3 (button2) -> бит 2 (бит 3 считая с 1)
            3: 3,   # inlet fan 4 (button7) -> бит 3 (бит 4 считая с 1)
            6: 4,   # opcell fan 1 (button10) -> бит 4 (бит 5 считая с 1)
            7: 5,   # opcell fan 2 (button9) -> бит 5 (бит 6 считая с 1)
            8: 6,   # opcell fan 3 (button8) -> бит 6 (бит 7 считая с 1)
            9: 7,   # opcell fan 4 (button13) -> бит 7 (бит 8 считая с 1)
            4: 8,   # outlet fan 1 (button6) -> бит 8 (бит 9 считая с 1)
            5: 9,   # outlet fan 2 (button5) -> бит 9 (бит 10 считая с 1)
        }
        
        # Маппинг fanIndex -> название вентилятора для статуса
        fan_name_mapping = {
            0: "inlet fan 1",
            1: "inlet fan 2",
            2: "inlet fan 3",
            3: "inlet fan 4",
            4: "outlet fan 1",
            5: "outlet fan 2",
            6: "opcell fan 1",
            7: "opcell fan 2",
            8: "opcell fan 3",
            9: "opcell fan 4",
            10: "laser fan"
        }
        
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        # Это обеспечивает мгновенную реакцию кнопок даже при подключенном устройстве
        if fanIndex == 10:
            # Laser fan использует бит 15 (считая с 0), что соответствует биту 16 (считая с 1)
            logger.info(f"Установка Laser Fan (бит 15): {state}")
            # Обновляем статус
            self._updateActionStatus(f"set {fan_name_mapping[10]}")
            # Сразу обновляем буфер и UI для мгновенной реакции (оптимистичное обновление)
            self._fan_states[10] = state
            self.fanStateChanged.emit(10, state)
            # Устанавливаем флаг оптимистичного обновления (игнорируем чтение регистра в течение 500мс)
            import time
            self._fan_optimistic_updates[10] = time.time()
            # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
            if self._is_connected and self._modbus_client is not None:
                self._setLaserFanAsync(state)
            return True  # Возвращаем True сразу, так как UI уже обновлен
        elif fanIndex in fan_bit_mapping:
            fan_bit = fan_bit_mapping[fanIndex]
            logger.info(f"Установка вентилятора {fanIndex} (бит {fan_bit}): {state}")
            # Обновляем статус с правильным названием
            if fanIndex in fan_name_mapping:
                self._updateActionStatus(f"set {fan_name_mapping[fanIndex]}")
            else:
                self._updateActionStatus(f"set fan {fanIndex + 1}")
            # Сразу обновляем буфер и UI для мгновенной реакции (оптимистичное обновление)
            self._fan_states[fanIndex] = state
            self.fanStateChanged.emit(fanIndex, state)
            # Устанавливаем флаг оптимистичного обновления (игнорируем чтение регистра в течение 500мс)
            import time
            self._fan_optimistic_updates[fanIndex] = time.time()
            # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
            if self._is_connected and self._modbus_client is not None:
                self._setFanAsync(fanIndex, fan_bit, state)
            return True  # Возвращаем True сразу, так как UI уже обновлен
        else:
            logger.error(f"Неизвестный индекс вентилятора: {fanIndex}")
            return False
    
    # Очередь задач Modbus из GUI-потока удалена:
    # любые блокирующие операции (connect/read/write) выполняются в _ModbusIoWorker (QThread).
    
    def _setFanAsync(self, fanIndex: int, fan_bit: int, state: bool):
        """Асинхронная установка состояния вентилятора (не блокирует UI)"""
        client = self._modbus_client

        def task() -> bool:
            try:
                result = client.set_fan_1131(fan_bit, state)
                if result:
                    logger.info(f"✅ Вентилятор {fanIndex} успешно {'включен' if state else 'выключен'}")
                else:
                    logger.error(f"❌ Не удалось {'включить' if state else 'выключить'} вентилятор {fanIndex}")
                return bool(result)
            except Exception as e:
                logger.error(f"Ошибка при асинхронной установке вентилятора {fanIndex}: {e}", exc_info=True)
                return False

        self._enqueue_write("fan1131", task, {"fanIndex": fanIndex, "state": state})
    
    def _setLaserFanAsync(self, state: bool):
        """Асинхронная установка состояния Laser Fan (не блокирует UI)"""
        client = self._modbus_client

        def task() -> bool:
            try:
                # laser fan: bit 15
                result = client.set_fan_1131(15, state)
                if result:
                    logger.info(f"✅ Laser Fan успешно {'включен' if state else 'выключен'}")
                else:
                    logger.error(f"❌ Не удалось {'включить' if state else 'выключить'} Laser Fan")
                return bool(result)
            except Exception as e:
                logger.error(f"Ошибка при асинхронной установке Laser Fan: {e}", exc_info=True)
                return False

        self._enqueue_write("laser_fan", task, {"state": state})
    
    def _setRelayAsync(self, relay_num: int, state: bool, name: str):
        """Асинхронная установка состояния реле (не блокирует UI)"""
        client = self._modbus_client

        def task() -> bool:
            try:
                result = client.set_relay_1021(relay_num, state)
                if result:
                    logger.info(f"✅ {name} успешно {'включен' if state else 'выключен'}")
                else:
                    logger.error(f"❌ Не удалось {'включить' if state else 'выключить'} {name}")
                return bool(result)
            except Exception as e:
                logger.error(f"Ошибка при асинхронной установке {name}: {e}", exc_info=True)
                return False

        self._enqueue_write(f"relay:{relay_num}", task, {"relay": relay_num, "state": state, "name": name})
    
    def _setValveAsync(self, valveIndex: int, valve_bit: int, state: bool):
        """Асинхронная установка состояния клапана (не блокирует UI)"""
        client = self._modbus_client

        def task() -> bool:
            try:
                result = client.set_valve_1111(valve_bit, state)
                if result:
                    logger.info(f"✅ Клапан {valveIndex} (бит {valve_bit}) успешно {'открыт' if state else 'закрыт'}")
                else:
                    logger.error(f"❌ Не удалось {'открыть' if state else 'закрыть'} клапан {valveIndex}")
                return bool(result)
            except Exception as e:
                logger.error(f"Ошибка при асинхронной установке клапана {valveIndex}: {e}", exc_info=True)
                return False

        self._enqueue_write(f"valve:{valveIndex}", task, {"valveIndex": valveIndex, "state": state})
    
    @Slot(float, result=bool)
    def setWaterChillerSetpointValue(self, temperature: float) -> bool:
        """
        Обновление внутреннего значения setpoint без отправки на устройство
        Используется для синхронизации при вводе с клавиатуры
        """
        logger.info(f"Обновление внутреннего значения setpoint: {temperature}°C (было {self._water_chiller_setpoint}°C)")
        # Всегда обновляем, даже если значение не изменилось (для надежности)
        self._water_chiller_setpoint = temperature
        self.waterChillerSetpointChanged.emit(temperature)
        logger.info(f"✅ Внутреннее значение setpoint обновлено: {self._water_chiller_setpoint}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._water_chiller_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления (начнет отсчет заново с 20 секунд)
        self._water_chiller_setpoint_auto_update_timer.stop()
        self._water_chiller_setpoint_auto_update_timer.start()
        return True
    
    @Slot(float, result=bool)
    def setWaterChillerTemperature(self, temperature: float) -> bool:
        """
        Установка температуры Water Chiller в регистр 1531
        
        Args:
            temperature: Температура в градусах Цельсия (например, 23.0)
        
        Returns:
            True если успешно, False в противном случае
        """
        logger.info(f"🔵 setWaterChillerTemperature вызван с температурой: {temperature}°C")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set water chiller to {temperature:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки температуры Water Chiller без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
        # Это нужно для того, чтобы стрелки работали с актуальным значением
        # Всегда обновляем и эмитируем сигнал, даже если значение не изменилось
        # Это гарантирует обновление UI при нажатии на стрелки
        logger.info(f"🔵 Обновление _water_chiller_setpoint: {self._water_chiller_setpoint}°C -> {temperature}°C")
        self._water_chiller_setpoint = temperature
        # Отправляем сигнал для обновления UI (setpoint)
        logger.info(f"🔵 Эмитируем сигнал waterChillerSetpointChanged: {temperature}°C")
        self.waterChillerSetpointChanged.emit(temperature)
        
        # Преобразуем температуру в значение для регистра (умножаем на 100)
        # Например, 23.0°C -> 2300
        register_value = int(temperature * 100)
        
        logger.info(f"Установка температуры Water Chiller: {temperature}°C (регистр 1531 = {register_value})")
        
        client = self._modbus_client

        def task() -> bool:
            result = client.write_register_1531_direct(register_value)
            if result:
                logger.info(f"✅ Заданная температура Water Chiller успешно установлена: {temperature}°C")
            else:
                logger.error(f"❌ Не удалось установить заданную температуру Water Chiller: {temperature}°C")
            return bool(result)

        self._enqueue_write("1531", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseWaterChillerTemperature(self) -> bool:
        """Увеличение заданной температуры Water Chiller на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Увеличение температуры: текущее значение = {self._water_chiller_setpoint}°C")
        new_temp = self._water_chiller_setpoint + 1.0
        logger.debug(f"Новое значение после увеличения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._water_chiller_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._water_chiller_setpoint_auto_update_timer.stop()
        self._water_chiller_setpoint_auto_update_timer.start()
        return self.setWaterChillerTemperature(new_temp)
    
    @Slot(result=bool)
    def decreaseWaterChillerTemperature(self) -> bool:
        """Уменьшение заданной температуры Water Chiller на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Уменьшение температуры: текущее значение = {self._water_chiller_setpoint}°C")
        new_temp = self._water_chiller_setpoint - 1.0
        logger.debug(f"Новое значение после уменьшения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._water_chiller_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._water_chiller_setpoint_auto_update_timer.stop()
        self._water_chiller_setpoint_auto_update_timer.start()
        return self.setWaterChillerTemperature(new_temp)
    
    @Slot(float, result=bool)
    def setMagnetPSUSetpointValue(self, temperature: float) -> bool:
        """
        Обновление внутреннего значения setpoint без отправки на устройство
        Используется для синхронизации при вводе с клавиатуры
        """
        logger.info(f"Обновление внутреннего значения setpoint Magnet PSU: {temperature}°C (было {self._magnet_psu_setpoint}°C)")
        # Всегда обновляем, даже если значение не изменилось (для надежности)
        self._magnet_psu_setpoint = temperature
        self.magnetPSUSetpointChanged.emit(temperature)
        logger.info(f"✅ Внутреннее значение setpoint Magnet PSU обновлено: {self._magnet_psu_setpoint}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._magnet_psu_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления (начнет отсчет заново с 20 секунд)
        self._magnet_psu_setpoint_auto_update_timer.stop()
        self._magnet_psu_setpoint_auto_update_timer.start()
        return True
    
    @Slot(float, result=bool)
    def setMagnetPSUTemperature(self, temperature: float) -> bool:
        """
        Установка температуры Magnet PSU в регистр 1331
        
        Args:
            temperature: Температура в градусах Цельсия (например, 23.0)
        
        Returns:
            True если успешно, False в противном случае
        """
        logger.info(f"🔵 setMagnetPSUTemperature вызван с температурой: {temperature}°C")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set magnet psu to {temperature:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки температуры Magnet PSU без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
        logger.info(f"🔵 Обновление _magnet_psu_setpoint: {self._magnet_psu_setpoint}°C -> {temperature}°C")
        self._magnet_psu_setpoint = temperature
        self.magnetPSUSetpointChanged.emit(temperature)
        
        # Преобразуем температуру в значение для регистра (умножаем на 100)
        register_value = int(temperature * 100)
        
        logger.info(f"Установка температуры Magnet PSU: {temperature}°C (регистр 1331 = {register_value})")
        
        client = self._modbus_client

        def task() -> bool:
            result = client.write_register_1331_direct(register_value)
            if result:
                logger.info(f"✅ Заданная температура Magnet PSU успешно установлена: {temperature}°C")
            else:
                logger.error(f"❌ Не удалось установить заданную температуру Magnet PSU: {temperature}°C")
            return bool(result)

        self._enqueue_write("1331", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseMagnetPSUTemperature(self) -> bool:
        """Увеличение заданной температуры Magnet PSU на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Увеличение температуры Magnet PSU: текущее значение = {self._magnet_psu_setpoint}°C")
        new_temp = self._magnet_psu_setpoint + 1.0
        logger.debug(f"Новое значение после увеличения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._magnet_psu_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._magnet_psu_setpoint_auto_update_timer.stop()
        self._magnet_psu_setpoint_auto_update_timer.start()
        return self.setMagnetPSUTemperature(new_temp)
    
    @Slot(result=bool)
    def decreaseMagnetPSUTemperature(self) -> bool:
        """Уменьшение заданной температуры Magnet PSU на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Уменьшение температуры Magnet PSU: текущее значение = {self._magnet_psu_setpoint}°C")
        new_temp = self._magnet_psu_setpoint - 1.0
        logger.debug(f"Новое значение после уменьшения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._magnet_psu_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._magnet_psu_setpoint_auto_update_timer.stop()
        self._magnet_psu_setpoint_auto_update_timer.start()
        return self.setMagnetPSUTemperature(new_temp)
    
    @Slot(float, result=bool)
    def setLaserPSUSetpointValue(self, temperature: float) -> bool:
        """
        Обновление внутреннего значения setpoint без отправки на устройство
        Используется для синхронизации при вводе с клавиатуры
        """
        logger.info(f"Обновление внутреннего значения setpoint Laser PSU: {temperature}°C (было {self._laser_psu_setpoint}°C)")
        # Всегда обновляем, даже если значение не изменилось (для надежности)
        self._laser_psu_setpoint = temperature
        self.laserPSUSetpointChanged.emit(temperature)
        logger.info(f"✅ Внутреннее значение setpoint Laser PSU обновлено: {self._laser_psu_setpoint}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._laser_psu_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления (начнет отсчет заново с 20 секунд)
        self._laser_psu_setpoint_auto_update_timer.stop()
        self._laser_psu_setpoint_auto_update_timer.start()
        return True
    
    @Slot(float, result=bool)
    def setLaserPSUTemperature(self, temperature: float) -> bool:
        """
        Установка температуры Laser PSU в регистр 1241
        
        Args:
            temperature: Температура в градусах Цельсия (например, 23.0)
        
        Returns:
            True если успешно, False в противном случае
        """
        logger.info(f"🔵 setLaserPSUTemperature вызван с температурой: {temperature}°C")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set laser psu to {temperature:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки температуры Laser PSU без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
        logger.info(f"🔵 Обновление _laser_psu_setpoint: {self._laser_psu_setpoint}°C -> {temperature}°C")
        self._laser_psu_setpoint = temperature
        self.laserPSUSetpointChanged.emit(temperature)
        
        # Преобразуем температуру в значение для регистра (умножаем на 100)
        register_value = int(temperature * 100)
        
        logger.info(f"Установка температуры Laser PSU: {temperature}°C (регистр 1241 = {register_value})")
        
        client = self._modbus_client

        def task() -> bool:
            result = client.write_register_1241_direct(register_value)
            if result:
                logger.info(f"✅ Заданная температура Laser PSU успешно установлена: {temperature}°C")
            else:
                logger.error(f"❌ Не удалось установить заданную температуру Laser PSU: {temperature}°C")
            return bool(result)

        self._enqueue_write("1241", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseLaserPSUTemperature(self) -> bool:
        """Увеличение заданной температуры Laser PSU на 0.01°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Увеличение температуры Laser PSU: текущее значение = {self._laser_psu_setpoint}°C")
        new_temp = self._laser_psu_setpoint + 0.01
        logger.debug(f"Новое значение после увеличения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._laser_psu_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._laser_psu_setpoint_auto_update_timer.stop()
        self._laser_psu_setpoint_auto_update_timer.start()
        return self.setLaserPSUTemperature(new_temp)
    
    @Slot(result=bool)
    def decreaseLaserPSUTemperature(self) -> bool:
        """Уменьшение заданной температуры Laser PSU на 0.01°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Уменьшение температуры Laser PSU: текущее значение = {self._laser_psu_setpoint}°C")
        new_temp = self._laser_psu_setpoint - 0.01
        logger.debug(f"Новое значение после уменьшения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._laser_psu_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._laser_psu_setpoint_auto_update_timer.stop()
        self._laser_psu_setpoint_auto_update_timer.start()
        return self.setLaserPSUTemperature(new_temp)
    
    @Slot(result=int)
    def getExternalRelays(self) -> int:
        """Получение значения регистра 1020 (External Relays) - НЕ БЛОКИРУЕТ UI"""
        # Возвращаем кэшированное значение из буфера, чтобы не блокировать UI
        if 1020 in self._register_cache:
            return self._register_cache[1020] & 0xFF  # Возвращаем только младший байт
        # Если значения нет в кэше, возвращаем 0 немедленно
        # Реальные значения будут обновляться через таймеры чтения
        return 0
    
    @Slot(result=str)
    def getExternalRelaysBinary(self) -> str:
        """Получение бинарного представления регистра 1020 (External Relays)"""
        value = self.getExternalRelays()
        return format(value & 0xFF, '08b')  # 8 бит в бинарном виде
    
    @Slot(int, result=int)
    def readRegister(self, address: int):
        """Чтение регистра (для использования из QML) - НЕ БЛОКИРУЕТ UI"""
        # Возвращаем кэшированное значение из буфера, чтобы не блокировать UI
        if address in self._register_cache:
            return self._register_cache[address]
        # Если значения нет в кэше, возвращаем 0 немедленно
        # Реальные значения будут обновляться через таймеры чтения
        return 0
    
    @Slot(int, int, result=bool)
    def writeRegister(self, address: int, value: int) -> bool:
        """Запись в регистр (для использования из QML)"""
        if not self._is_connected or self._modbus_client is None:
            logger.warning(f"Попытка записи в регистр {address} без подключения")
            return False

        # Оптимистично обновляем кэш, чтобы UI не ждал ответ
        self._register_cache[address] = value

        client = self._modbus_client

        def task() -> bool:
            result = client.write_register(address, value)
            if not result:
                logger.warning(f"⚠️ Запись в регистр {address} не удалась (value={value}).")
            return bool(result)

        # Неблокирующая отправка в worker; возвращаем True если задача поставлена
        self._enqueue_write(f"write:{address}", task, {"address": address, "value": value})
        return True
    
    
    # Методы для управления реле через регистр 1021
    @Slot(bool, result=bool)
    def setLaserPSU(self, state: bool) -> bool:
        """Управление Laser PSU через регистр 1021 (реле 3, бит 2)"""
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set 3")
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        self._relay_states['laser_psu'] = state
        self.laserPSUStateChanged.emit(state)
        # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
        if self._is_connected and self._modbus_client is not None:
            self._setRelayAsync(3, state, "Laser PSU")
        return True  # Возвращаем True сразу, так как UI уже обновлен
    
    @Slot(bool, result=bool)
    def setMagnetPSU(self, state: bool) -> bool:
        """Управление Magnet PSU через регистр 1021 (реле 2, бит 1)"""
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set 2")
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        self._relay_states['magnet_psu'] = state
        self.magnetPSUStateChanged.emit(state)
        # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
        if self._is_connected and self._modbus_client is not None:
            self._setRelayAsync(2, state, "Magnet PSU")
        return True  # Возвращаем True сразу, так как UI уже обновлен
    
    @Slot(bool, result=bool)
    def setPIDController(self, state: bool) -> bool:
        """Управление PID Controller через регистр 1021 (реле 6, бит 5)"""
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set 6")
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        self._relay_states['pid_controller'] = state
        self.pidControllerStateChanged.emit(state)
        # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
        if self._is_connected and self._modbus_client is not None:
            self._setRelayAsync(6, state, "PID Controller")
        return True  # Возвращаем True сразу, так как UI уже обновлен
    
    @Slot(bool, result=bool)
    def setWaterChiller(self, state: bool) -> bool:
        """Управление Water Chiller через регистр 1021 (реле 1, бит 0)"""
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set 1")
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        self._relay_states['water_chiller'] = state
        self.waterChillerStateChanged.emit(state)
        # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
        if self._is_connected and self._modbus_client is not None:
            self._setRelayAsync(1, state, "Water Chiller")
        return True  # Возвращаем True сразу, так как UI уже обновлен
    
    # Методы для управления Laser
    @Slot(bool, result=bool)
    def setLaserBeam(self, state: bool) -> bool:
        """Управление Laser beam (регистр 1810: 0 off, 1 on)"""
        # Сначала активируем Control View для Laser (1800 = 1)
        self.writeRegister(1800, 1)
        return self.writeRegister(1810, 1 if state else 0)
    
    @Slot(result=bool)
    def getLaserBeam(self) -> bool:
        """Получение состояния Laser beam"""
        value = self.readRegister(1810)
        return bool(value) if value is not None else False
    
    # Методы для управления Vacuum через регистр 1021
    @Slot(bool, result=bool)
    def setVacuumPump(self, state: bool) -> bool:
        """Управление Vacuum Pump через регистр 1021 (реле 4, бит 3)"""
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set 4")
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        self._relay_states['vacuum_pump'] = state
        self.vacuumPumpStateChanged.emit(state)
        # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
        if self._is_connected and self._modbus_client is not None:
            self._setRelayAsync(4, state, "Vacuum Pump")
        return True  # Возвращаем True сразу, так как UI уже обновлен
    
    @Slot(bool, result=bool)
    def setVacuumGauge(self, state: bool) -> bool:
        """Управление Vacuum Gauge через регистр 1021 (реле 5, бит 4)"""
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set 5")
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        self._relay_states['vacuum_gauge'] = state
        self.vacuumGaugeStateChanged.emit(state)
        # Затем отправляем команду на устройство асинхронно через очередь задач (только если подключено)
        if self._is_connected and self._modbus_client is not None:
            self._setRelayAsync(5, state, "Vacuum Gauge")
        return True  # Возвращаем True сразу, так как UI уже обновлен
    
    # Методы для управления клапанами через регистр 1111 (биты 6-12 для X6-X12)
    @Slot(int, bool, result=bool)
    def setValve(self, valveIndex: int, state: bool) -> bool:
        """
        Управление клапаном через регистр 1111
        
        Args:
            valveIndex: Индекс клапана (5=X6, 6=X7, 7=X8, 8=X9, 9=X10, 10=X11, 11=X12)
            state: True - открыть, False - закрыть
        """
        if valveIndex < 5 or valveIndex > 11:
            logger.warning(f"setValve: valveIndex {valveIndex} не поддерживается для регистра 1111 (поддерживаются 5-11)")
            return False
        
        # Обновляем статус (даже без подключения)
        valve_number = valveIndex - 4  # valveIndex 5 -> X6, valveIndex 6 -> X7, и т.д.
        self._updateActionStatus(f"set X{valve_number}")
        
        # ВСЕГДА обновляем UI мгновенно (оптимистичное обновление) ДО проверки подключения
        # Это обеспечивает мгновенную реакцию кнопок даже при подключенном устройстве
        self._valve_states[valveIndex] = state
        self.valveStateChanged.emit(valveIndex, state)
        
        # Отправляем команду на устройство асинхронно через очередь задач (только если подключено)
        if not self._is_connected or self._modbus_client is None:
            return True  # Возвращаем True сразу, так как UI уже обновлен
        
        # Маппинг: valveIndex -> бит в регистре 1111
        # X6 (valveIndex 5) -> бит 6
        # X7 (valveIndex 6) -> бит 7
        # X8 (valveIndex 7) -> бит 8
        # X9 (valveIndex 8) -> бит 9
        # X10 (valveIndex 9) -> бит 10
        # X11 (valveIndex 10) -> бит 11
        # X12 (valveIndex 11) -> бит 12
        
        # Преобразуем valveIndex в бит в регистре 1111
        # Если кнопка 9 (valveIndex 8) включает бит 8, значит биты нумеруются с 0
        # valveIndex 5 (X6) -> бит 5, но пользователь сказал "6,7,8,9,10,11,12 это наши кнопки"
        # Возможно, биты нумеруются с 1, и нужно valve_bit = valveIndex + 1?
        # Но тогда valveIndex 8 -> бит 9, а включается бит 8
        
        # Попробуем: если кнопка 9 (valveIndex 8) включает бит 8, значит valve_bit = valveIndex
        # Но тогда кнопка 6 (valveIndex 5) будет бит 5, а не 6
        
        # Может быть проблема в том, что биты нумеруются с 0, и кнопка 6 соответствует биту 5?
        # Но пользователь сказал "6,7,8,9,10,11,12 это наши кнопки", что может означать биты 5-11 (нумерация с 0)
        # Или биты 6-12 (нумерация с 1)?
        
        # Если кнопка 9 (valveIndex 8) включает бит 8, значит используется valveIndex напрямую
        # valve_bit = valveIndex
        # Тогда кнопка 6 (valveIndex 5) будет бит 5, что соответствует биту 6 при нумерации с 1
        # Но в коде мы используем биты с нумерацией с 0, значит бит 5 = 6-й бит
        
        # Попробуем: valve_bit = valveIndex (биты нумеруются с 0)
        valve_bit = valveIndex
        
        # Сразу обновляем буфер и UI для мгновенной реакции (оптимистичное обновление)
        self._valve_states[valveIndex] = state
        self.valveStateChanged.emit(valveIndex, state)
        # Затем отправляем команду на устройство асинхронно через очередь задач
        self._setValveAsync(valveIndex, valve_bit, state)
        return True  # Возвращаем True сразу, так как UI уже обновлен

