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
    pidControllerStateChanged = Signal(bool)  # Состояние PID Controller (вкл/выкл, регистр 1431)
    pidControllerTemperatureChanged = Signal(float)  # Температура PID Controller в градусах Цельсия (регистр 1411)
    pidControllerSetpointChanged = Signal(float)  # Заданная температура PID Controller в градусах Цельсия (регистр 1421)
    waterChillerStateChanged = Signal(bool)  # Состояние Water Chiller (вкл/выкл, регистр 1541)
    waterChillerInletTemperatureChanged = Signal(float)  # Температура на входе Water Chiller в градусах Цельсия (регистр 1511)
    waterChillerOutletTemperatureChanged = Signal(float)  # Температура на выходе Water Chiller в градусах Цельсия (регистр 1521)
    waterChillerSetpointChanged = Signal(float)  # Заданная температура Water Chiller в градусах Цельсия (регистр 1531)
    # Старый сигнал для обратной совместимости (использует inlet temp)
    waterChillerTemperatureChanged = Signal(float)  # Текущая температура Water Chiller в градусах Цельсия (регистр 1511)
    seopCellTemperatureChanged = Signal(float)  # Температура SEOP Cell в градусах Цельсия (регистр 1411)
    seopCellSetpointChanged = Signal(float)  # Заданная температура SEOP Cell в градусах Цельсия (регистр 1421)
    magnetPSUCurrentChanged = Signal(float)  # Ток Magnet PSU в амперах (регистр 1321)
    magnetPSUSetpointChanged = Signal(float)  # Заданный ток Magnet PSU в амперах (регистр 1331)
    magnetPSUVoltageChanged = Signal(float)  # Напряжение Magnet PSU в вольтах (регистр 1301)
    magnetPSUVoltageSetpointChanged = Signal(float)  # Заданное напряжение Magnet PSU в вольтах (регистр 1311)
    magnetPSUStateChanged = Signal(bool)  # Состояние Magnet PSU (вкл/выкл, регистр 1341)
    laserPSUCurrentChanged = Signal(float)  # Ток Laser PSU в амперах (регистр 1231)
    laserPSUSetpointChanged = Signal(float)  # Заданный ток Laser PSU в амперах (регистр 1241)
    laserPSUVoltageChanged = Signal(float)  # Напряжение Laser PSU в вольтах (регистр 1211)
    laserPSUVoltageSetpointChanged = Signal(float)  # Заданное напряжение Laser PSU в вольтах (регистр 1221)
    laserPSUStateChanged = Signal(bool)  # Состояние Laser PSU (вкл/выкл, регистр 1251)
    xenonPressureChanged = Signal(float)  # Давление Xenon в Torr (регистр 1611)
    n2SetpointChanged = Signal(float)  # Заданное давление N2 в Torr (регистр 1661)
    xenonSetpointChanged = Signal(float)  # Заданное давление Xenon в Torr (регистр 1621)
    n2PressureChanged = Signal(float)  # Давление N2 в Torr (регистр 1651)
    vacuumPressureChanged = Signal(float)  # Давление Vacuum в Torr (регистр 1701)
    vacuumControllerPressureChanged = Signal(float)  # Давление Vacuum Controller в mTorr (регистр 1701)
    vacuumPumpStateChanged = Signal(bool)
    vacuumGaugeStateChanged = Signal(bool)
    laserBeamStateChanged = Signal(bool)  # Состояние Beam Laser (вкл/выкл, регистр 1811)
    laserMPDChanged = Signal(float)  # MPD Laser в uA (регистр 1821)
    laserOutputPowerChanged = Signal(float)  # Output Power Laser (регистр 1831)
    laserTempChanged = Signal(float)  # Temp Laser (регистр 1841)
    # SEOP Parameters signals
    seopLaserMaxTempChanged = Signal(float)  # Laser Max Temp (регистр 3011)
    seopLaserMinTempChanged = Signal(float)  # Laser Min Temp (регистр 3021)
    seopCellMaxTempChanged = Signal(float)  # SEOP Cell Max Temp (регистр 3031)
    seopCellMinTempChanged = Signal(float)  # SEOP Cell Min Temp (регистр 3041)
    seopRampTempChanged = Signal(float)  # Seop ramp Temp (регистр 3051)
    seopTempChanged = Signal(float)  # SEOP Temp (регистр 3061)
    seopCellRefillTempChanged = Signal(float)  # Cell Refill Temp (регистр 3071)
    seopLoopTimeChanged = Signal(float)  # SEOP loop time в секундах (регистр 3081)
    seopProcessDurationChanged = Signal(float)  # SEOP process duration в минутах (регистр 3091)
    seopLaserMaxOutputPowerChanged = Signal(float)  # Laser Max Output Power в W (регистр 3101)
    seopLaserPSUMaxCurrentChanged = Signal(float)  # Laser PSU MAX Current в A (регистр 3111)
    seopWaterChillerMaxTempChanged = Signal(float)  # Water Chiller Max Temp в C (регистр 3121)
    seopWaterChillerMinTempChanged = Signal(float)  # Water Chiller Min Temp в C (регистр 3131)
    seopXeConcentrationChanged = Signal(float)  # 129Xe concentration of gas mixture в mMol (регистр 3141)
    seopWaterProtonConcentrationChanged = Signal(float)  # Water proton concentration в Mol (регистр 3151)
    seopCellNumberChanged = Signal(int)  # Cell number (регистр 3171)
    seopRefillCycleChanged = Signal(int)  # Refill cycle (регистр 3181)
    # Calculated Parameters signals
    calculatedElectronPolarizationChanged = Signal(float)  # Electron Polarization (PRb %) (регистр 4011)
    calculatedXePolarizationChanged = Signal(float)  # 129Xe Polarization (PXe %) (регистр 4021)
    calculatedBuildupRateChanged = Signal(float)  # The buildup rate (g-SEOP 1/min) (регистр 4031)
    calculatedElectronPolarizationErrorChanged = Signal(float)  # Error bar for Electron Polarization (PRb-err %) (регистр 4041)
    calculatedXePolarizationErrorChanged = Signal(float)  # Error bar for 129Xe Polarization (PXe err %) (регистр 4051)
    calculatedBuildupRateErrorChanged = Signal(float)  # Error bar for the buildup rate (g-SEOP err 1/min) (регистр 4061)
    calculatedFittedXePolarizationMaxChanged = Signal(float)  # Fitted 129Xe Polarization maximum (PXe max %) (регистр 4071)
    calculatedFittedXePolarizationMaxErrorChanged = Signal(float)  # Fitted 129Xe Polarization max error bar (PXe max err %) (регистр 4081)
    calculatedHPXeT1Changed = Signal(float)  # HP 129Xe T1 (T1 min) (регистр 4091)
    calculatedHPXeT1ErrorChanged = Signal(float)  # Error bar for 129Xe T1 (T1 err min) (регистр 4101)
    # Measured Parameters signals
    measuredCurrentIRSignalChanged = Signal(float)  # Current IR Signal (регистр 5011) - только чтение
    measuredColdCellIRSignalChanged = Signal(float)  # Cold Cell IR Signal (регистр 5021) - чтение и запись
    measuredHotCellIRSignalChanged = Signal(float)  # Hot Cell IR Signal (регистр 5031) - чтение и запись
    measuredWater1HNMRReferenceSignalChanged = Signal(float)  # Water 1H NMR Reference Signal (регистр 5041) - чтение и запись
    measuredWaterT2Changed = Signal(float)  # Water T2 в ms (регистр 5051) - чтение и запись
    measuredHP129XeNMRSignalChanged = Signal(float)  # HP 129Xe NMR Signal (регистр 5061) - только чтение
    measuredHP129XeT2Changed = Signal(float)  # HP 129Xe T2 в ms (регистр 5071) - чтение и запись
    measuredT2CorrectionFactorChanged = Signal(float)  # T2* correction factor (регистр 5081) - только чтение
    # Additional Parameters signals
    additionalMagnetPSUCurrentProtonNMRChanged = Signal(float)  # Magnet PSU current for proton NMR в A (регистр 6011) - чтение и запись
    additionalMagnetPSUCurrent129XeNMRChanged = Signal(float)  # Magnet PSU current for 129Xe NMR в A (регистр 6021) - чтение и запись
    additionalOperationalLaserPSUCurrentChanged = Signal(float)  # Operational Laser PSU current в A (регистр 6031) - чтение и запись
    additionalRFPulseDurationChanged = Signal(float)  # RF pulse duration (регистр 6041) - чтение и запись
    additionalResonanceFrequencyChanged = Signal(float)  # Resonance frequency в kHz (регистр 6051) - чтение и запись
    additionalProtonRFPulsePowerChanged = Signal(float)  # Proton RF pulse power в % (регистр 6061) - чтение и запись
    additionalHP129XeRFPulsePowerChanged = Signal(float)  # HP 129Xe RF pulse power в % (регистр 6071) - чтение и запись
    additionalStepSizeB0SweepHP129XeChanged = Signal(float)  # Step size during B0 field sweep for HP 129Xe в A (регистр 6081) - чтение и запись
    additionalStepSizeB0SweepProtonsChanged = Signal(float)  # Step size during B0 field sweep for protons в A (регистр 6091) - чтение и запись
    additionalXeAlicatsPressureChanged = Signal(float)  # Xe ALICATS pressure в Torr (регистр 6101) - чтение и запись
    additionalNitrogenAlicatsPressureChanged = Signal(float)  # Nitrogen ALICATS pressure в Torr (регистр 6111) - чтение и запись
    additionalChillerTempSetpointChanged = Signal(float)  # Chiller Temp setpoint (регистр 6121) - чтение и запись
    additionalSEOPResonanceFrequencyChanged = Signal(float)  # SEOP Resonance Frequency в nm (регистр 6131) - чтение и запись
    additionalSEOPResonanceFrequencyToleranceChanged = Signal(float)  # SEOP Resonance Frequency Tolerance (регистр 6141) - чтение и запись
    additionalIRSpectrometerNumberOfScansChanged = Signal(float)  # IR spectrometer number of scans (регистр 6151) - чтение и запись
    additionalIRSpectrometerExposureDurationChanged = Signal(float)  # IR spectrometer exposure duration в ms (регистр 6161) - чтение и запись
    additional1HReferenceNScansChanged = Signal(float)  # 1H Reference N Scans (регистр 6171) - чтение и запись
    additional1HCurrentSweepNScansChanged = Signal(float)  # 1H Current Sweep N Scans (регистр 6181) - чтение и запись
    additionalBaselineCorrectionMinFrequencyChanged = Signal(float)  # Baseline correction min frequency в kHz (регистр 6191) - чтение и запись
    additionalBaselineCorrectionMaxFrequencyChanged = Signal(float)  # Baseline correction max frequency в kHz (регистр 6201) - чтение и запись
    # Manual mode settings signals
    manualModeRFPulseFrequencyChanged = Signal(float)  # RF pulse frequency в kHz (регистр 6301) - чтение и запись
    manualModeRFPulsePowerChanged = Signal(float)  # RF pulse power в % (регистр 6311) - чтение и запись
    manualModeRFPulseDurationChanged = Signal(float)  # RF pulse duration в T/2 (регистр 6321) - чтение и запись
    manualModePreAcquisitionChanged = Signal(float)  # Pre acquisition в ms (регистр 6331) - чтение и запись
    manualModeNMRGainChanged = Signal(float)  # NMR gain в dB (регистр 6341) - чтение и запись
    manualModeNMRNumberOfScansChanged = Signal(float)  # NMR number of scans (регистр 6351) - чтение и запись
    manualModeNMRRecoveryChanged = Signal(float)  # NMR recovery в ms (регистр 6361) - чтение и запись
    manualModeCenterFrequencyChanged = Signal(float)  # Center frequency в kHz (регистр 6371) - чтение и запись
    manualModeFrequencySpanChanged = Signal(float)  # Frequency span в kHz (регистр 6381) - чтение и запись
    externalRelaysChanged = Signal(int, str)  # value, binary_string - для регистра 1020
    opCellHeatingStateChanged = Signal(bool)  # OP cell heating (реле 7)
    # Сигналы для паузы/возобновления опросов (используется при переключении экранов)
    pollingPausedChanged = Signal(bool)
    # IR spectrum (Clinicalmode/Screen01 IR graph)
    # Важно: используем QVariantMap, чтобы QML видел обычный JS object/array, а не PyObjectWrapper.
    irSpectrumChanged = Signal('QVariantMap')  # payload map: {x_min,x_max,y_min,y_max,points,data,...}
    # Logging signal for Clinicalmode screen
    logMessageChanged = Signal(str)  # log message to display in logs TextArea

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
        self._water_chiller_inlet_temperature = 0.0  # Температура на входе Water Chiller (регистр 1511)
        self._water_chiller_outlet_temperature = 0.0  # Температура на выходе Water Chiller (регистр 1521)
        self._water_chiller_setpoint = 0.0  # Заданная температура Water Chiller (регистр 1531)
        self._water_chiller_state = False  # Состояние Water Chiller (вкл/выкл, регистр 1541)
        # Старая переменная для обратной совместимости
        self._water_chiller_temperature = 0.0  # Текущая температура Water Chiller (регистр 1511) - использует inlet temp
        self._water_chiller_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._water_chiller_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._water_chiller_setpoint_auto_update_timer.timeout.connect(self._autoUpdateWaterChillerSetpoint)
        self._water_chiller_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._seop_cell_temperature = 0.0  # Температура SEOP Cell (регистр 1411)
        self._seop_cell_setpoint = 0.0  # Заданная температура SEOP Cell (регистр 1421)
        self._pid_controller_temperature = 0.0  # Температура PID Controller (регистр 1411)
        self._pid_controller_setpoint = 0.0  # Заданная температура PID Controller (регистр 1421)
        self._pid_controller_state = False  # Состояние PID Controller (вкл/выкл, регистр 1431)
        self._pid_controller_setpoint_user_interaction = False  # Флаг: пользователь взаимодействует с полем ввода
        self._pid_controller_setpoint_auto_update_timer = QTimer(self)  # Таймер для автообновления setpoint
        self._pid_controller_setpoint_auto_update_timer.timeout.connect(self._autoUpdatePIDControllerSetpoint)
        self._pid_controller_setpoint_auto_update_timer.setInterval(20000)  # 20 секунд
        self._reading_water_chiller = False  # Флаг для предотвращения параллельного чтения Water Chiller
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
        self._vacuum_controller_pressure = 0.0  # Давление Vacuum Controller в mTorr (регистр 1701)
        self._laser_beam_state = False  # Состояние Beam Laser (вкл/выкл, регистр 1811)
        self._laser_mpd = 0.0  # MPD Laser в uA (регистр 1821)
        self._laser_output_power = 0.0  # Output Power Laser (регистр 1831)
        self._laser_temp = 0.0  # Temp Laser (регистр 1841)
        # SEOP Parameters state variables
        self._seop_laser_max_temp = 0.0  # Laser Max Temp (регистр 3011)
        self._seop_laser_min_temp = 0.0  # Laser Min Temp (регистр 3021)
        self._seop_cell_max_temp = 0.0  # SEOP Cell Max Temp (регистр 3031)
        self._seop_cell_min_temp = 0.0  # SEOP Cell Min Temp (регистр 3041)
        self._seop_ramp_temp = 0.0  # Seop ramp Temp (регистр 3051)
        self._seop_temp = 0.0  # SEOP Temp (регистр 3061)
        self._seop_cell_refill_temp = 0.0  # Cell Refill Temp (регистр 3071)
        self._seop_loop_time = 0.0  # SEOP loop time в секундах (регистр 3081)
        self._seop_process_duration = 0.0  # SEOP process duration в минутах (регистр 3091)
        self._seop_laser_max_output_power = 0.0  # Laser Max Output Power в W (регистр 3101)
        self._seop_laser_psu_max_current = 0.0  # Laser PSU MAX Current в A (регистр 3111)
        self._seop_water_chiller_max_temp = 0.0  # Water Chiller Max Temp в C (регистр 3121)
        self._seop_water_chiller_min_temp = 0.0  # Water Chiller Min Temp в C (регистр 3131)
        self._seop_xe_concentration = 0.0  # 129Xe concentration of gas mixture в mMol (регистр 3141)
        self._seop_water_proton_concentration = 0.0  # Water proton concentration в Mol (регистр 3151)
        self._seop_cell_number = 0  # Cell number (регистр 3171)
        self._seop_refill_cycle = 0  # Refill cycle (регистр 3181)
        # Calculated Parameters state variables
        self._calculated_electron_polarization = 0.0  # Electron Polarization (PRb %) (регистр 4011)
        self._calculated_xe_polarization = 0.0  # 129Xe Polarization (PXe %) (регистр 4021)
        self._calculated_buildup_rate = 0.0  # The buildup rate (g-SEOP 1/min) (регистр 4031)
        self._calculated_electron_polarization_error = 0.0  # Error bar for Electron Polarization (PRb-err %) (регистр 4041)
        self._calculated_xe_polarization_error = 0.0  # Error bar for 129Xe Polarization (PXe err %) (регистр 4051)
        self._calculated_buildup_rate_error = 0.0  # Error bar for the buildup rate (g-SEOP err 1/min) (регистр 4061)
        self._calculated_fitted_xe_polarization_max = 0.0  # Fitted 129Xe Polarization maximum (PXe max %) (регистр 4071)
        self._calculated_fitted_xe_polarization_max_error = 0.0  # Fitted 129Xe Polarization max error bar (PXe max err %) (регистр 4081)
        self._calculated_hp_xe_t1 = 0.0  # HP 129Xe T1 (T1 min) (регистр 4091)
        self._calculated_hp_xe_t1_error = 0.0  # Error bar for 129Xe T1 (T1 err min) (регистр 4101)
        # Measured Parameters state variables
        self._measured_current_ir_signal = 0.0  # Current IR Signal (регистр 5011) - только чтение
        self._measured_cold_cell_ir_signal = 0.0  # Cold Cell IR Signal (регистр 5021) - чтение и запись
        self._measured_hot_cell_ir_signal = 0.0  # Hot Cell IR Signal (регистр 5031) - чтение и запись
        self._measured_water_1h_nmr_reference_signal = 0.0  # Water 1H NMR Reference Signal (регистр 5041) - чтение и запись
        self._measured_water_t2 = 0.0  # Water T2 в ms (регистр 5051) - чтение и запись
        self._measured_hp_129xe_nmr_signal = 0.0  # HP 129Xe NMR Signal (регистр 5061) - только чтение
        self._measured_hp_129xe_t2 = 0.0  # HP 129Xe T2 в ms (регистр 5071) - чтение и запись
        self._measured_t2_correction_factor = 0.0  # T2* correction factor (регистр 5081) - только чтение
        # Additional Parameters state variables
        self._additional_magnet_psu_current_proton_nmr = 0.0  # Magnet PSU current for proton NMR в A (регистр 6011) - чтение и запись
        self._additional_magnet_psu_current_129xe_nmr = 0.0  # Magnet PSU current for 129Xe NMR в A (регистр 6021) - чтение и запись
        self._additional_operational_laser_psu_current = 0.0  # Operational Laser PSU current в A (регистр 6031) - чтение и запись
        self._additional_rf_pulse_duration = 0.0  # RF pulse duration (регистр 6041) - чтение и запись
        self._additional_resonance_frequency = 0.0  # Resonance frequency в kHz (регистр 6051) - чтение и запись
        self._additional_proton_rf_pulse_power = 0.0  # Proton RF pulse power в % (регистр 6061) - чтение и запись
        self._additional_hp_129xe_rf_pulse_power = 0.0  # HP 129Xe RF pulse power в % (регистр 6071) - чтение и запись
        self._additional_step_size_b0_sweep_hp_129xe = 0.0  # Step size during B0 field sweep for HP 129Xe в A (регистр 6081) - чтение и запись
        self._additional_step_size_b0_sweep_protons = 0.0  # Step size during B0 field sweep for protons в A (регистр 6091) - чтение и запись
        self._additional_xe_alicats_pressure = 0.0  # Xe ALICATS pressure в Torr (регистр 6101) - чтение и запись
        self._additional_nitrogen_alicats_pressure = 0.0  # Nitrogen ALICATS pressure в Torr (регистр 6111) - чтение и запись
        self._additional_chiller_temp_setpoint = 0.0  # Chiller Temp setpoint (регистр 6121) - чтение и запись
        self._additional_seop_resonance_frequency = 0.0  # SEOP Resonance Frequency в nm (регистр 6131) - чтение и запись
        self._additional_seop_resonance_frequency_tolerance = 0.0  # SEOP Resonance Frequency Tolerance (регистр 6141) - чтение и запись
        self._additional_ir_spectrometer_number_of_scans = 0.0  # IR spectrometer number of scans (регистр 6151) - чтение и запись
        self._additional_ir_spectrometer_exposure_duration = 0.0  # IR spectrometer exposure duration в ms (регистр 6161) - чтение и запись
        self._additional_1h_reference_n_scans = 0.0  # 1H Reference N Scans (регистр 6171) - чтение и запись
        self._additional_1h_current_sweep_n_scans = 0.0  # 1H Current Sweep N Scans (регистр 6181) - чтение и запись
        self._additional_baseline_correction_min_frequency = 0.0  # Baseline correction min frequency в kHz (регистр 6191) - чтение и запись
        self._additional_baseline_correction_max_frequency = 0.0  # Baseline correction max frequency в kHz (регистр 6201) - чтение и запись
        # Флаги взаимодействия пользователя для автообновления
        self._additional_magnet_psu_current_proton_nmr_user_interaction = False
        self._additional_magnet_psu_current_129xe_nmr_user_interaction = False
        self._additional_operational_laser_psu_current_user_interaction = False
        self._additional_rf_pulse_duration_user_interaction = False
        self._additional_resonance_frequency_user_interaction = False
        self._additional_proton_rf_pulse_power_user_interaction = False
        self._additional_hp_129xe_rf_pulse_power_user_interaction = False
        self._additional_step_size_b0_sweep_hp_129xe_user_interaction = False
        self._additional_step_size_b0_sweep_protons_user_interaction = False
        self._additional_xe_alicats_pressure_user_interaction = False
        self._additional_nitrogen_alicats_pressure_user_interaction = False
        self._additional_chiller_temp_setpoint_user_interaction = False
        self._additional_seop_resonance_frequency_user_interaction = False
        self._additional_seop_resonance_frequency_tolerance_user_interaction = False
        self._additional_ir_spectrometer_number_of_scans_user_interaction = False
        self._additional_ir_spectrometer_exposure_duration_user_interaction = False
        self._additional_1h_reference_n_scans_user_interaction = False
        self._additional_1h_current_sweep_n_scans_user_interaction = False
        self._additional_baseline_correction_min_frequency_user_interaction = False
        self._additional_baseline_correction_max_frequency_user_interaction = False
        # Флаги взаимодействия пользователя для Manual mode settings
        self._manual_mode_rf_pulse_frequency_user_interaction = False
        self._manual_mode_rf_pulse_power_user_interaction = False
        self._manual_mode_rf_pulse_duration_user_interaction = False
        self._manual_mode_pre_acquisition_user_interaction = False
        self._manual_mode_nmr_gain_user_interaction = False
        self._manual_mode_nmr_number_of_scans_user_interaction = False
        self._manual_mode_nmr_recovery_user_interaction = False
        self._manual_mode_center_frequency_user_interaction = False
        self._manual_mode_frequency_span_user_interaction = False
        # Флаги взаимодействия пользователя для автообновления
        self._measured_cold_cell_ir_signal_user_interaction = False
        self._measured_hot_cell_ir_signal_user_interaction = False
        self._measured_water_1h_nmr_reference_signal_user_interaction = False
        self._measured_water_t2_user_interaction = False
        self._measured_hp_129xe_t2_user_interaction = False
        # Флаги взаимодействия пользователя для автообновления
        self._seop_laser_max_temp_user_interaction = False
        self._seop_laser_min_temp_user_interaction = False
        self._seop_cell_max_temp_user_interaction = False
        self._seop_cell_min_temp_user_interaction = False
        self._seop_ramp_temp_user_interaction = False
        self._seop_temp_user_interaction = False
        self._seop_cell_refill_temp_user_interaction = False
        self._seop_loop_time_user_interaction = False
        self._seop_process_duration_user_interaction = False
        self._seop_laser_max_output_power_user_interaction = False
        self._seop_laser_psu_max_current_user_interaction = False
        self._seop_water_chiller_max_temp_user_interaction = False
        self._seop_water_chiller_min_temp_user_interaction = False
        self._seop_xe_concentration_user_interaction = False
        self._seop_water_proton_concentration_user_interaction = False
        self._seop_cell_number_user_interaction = False
        self._seop_refill_cycle_user_interaction = False

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
        self._reading_power_supply = False
        self._reading_1251 = False
        self._reading_1611 = False
        self._reading_1651 = False
        self._reading_1701 = False
        self._reading_1131 = False
        self._reading_pid_controller = False
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
        
        # Таймер для чтения регистра 1511 (температура Water Chiller) - быстрое обновление (старый, для обратной совместимости)
        self._water_chiller_temp_timer = QTimer(self)
        self._water_chiller_temp_timer.timeout.connect(self._readWaterChillerTemperature)
        self._water_chiller_temp_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
        # Таймер для чтения регистров Water Chiller (1511, 1521, 1531, 1541) - быстрое обновление
        self._water_chiller_timer = QTimer(self)
        self._water_chiller_timer.timeout.connect(self._readWaterChiller)
        self._water_chiller_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        
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

        # Таймер для чтения регистров Power Supply (Laser PSU и Magnet PSU) - быстрое обновление
        self._power_supply_timer = QTimer(self)
        self._power_supply_timer.timeout.connect(self._readPowerSupply)
        self._power_supply_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления

        # Таймер для чтения регистров PID Controller (1411, 1421, 1431) - быстрое обновление
        self._pid_controller_timer = QTimer(self)
        self._pid_controller_timer.timeout.connect(self._readPIDController)
        self._pid_controller_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления

        # Таймер для чтения регистров Alicats (1611, 1621, 1651, 1661) - быстрое обновление
        self._alicats_timer = QTimer(self)
        self._alicats_timer.timeout.connect(self._readAlicats)
        self._alicats_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_alicats = False  # Флаг для предотвращения параллельных чтений

        # Таймер для чтения регистра Vacuum Controller (1701) - быстрое обновление
        self._vacuum_controller_timer = QTimer(self)
        self._vacuum_controller_timer.timeout.connect(self._readVacuumController)
        self._vacuum_controller_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_vacuum_controller = False  # Флаг для предотвращения параллельных чтений

        # Таймер для чтения регистров Laser (1811, 1821, 1831, 1841) - быстрое обновление
        self._laser_timer = QTimer(self)
        self._laser_timer.timeout.connect(self._readLaser)
        self._laser_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_laser = False  # Флаг для предотвращения параллельных чтений

        # Таймер для чтения регистров SEOP Parameters (3011-3081) - быстрое обновление
        self._seop_parameters_timer = QTimer(self)
        self._seop_parameters_timer.timeout.connect(self._readSEOPParameters)
        self._seop_parameters_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_seop_parameters = False  # Флаг для предотвращения параллельных чтений

        # Таймер для чтения регистров Calculated Parameters (4011-4101) - быстрое обновление
        self._calculated_parameters_timer = QTimer(self)
        self._calculated_parameters_timer.timeout.connect(self._readCalculatedParameters)
        self._calculated_parameters_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_calculated_parameters = False  # Флаг для предотвращения параллельных чтений

        # Таймер для чтения регистров Measured Parameters (5011-5081) - быстрое обновление
        self._measured_parameters_timer = QTimer(self)
        self._measured_parameters_timer.timeout.connect(self._readMeasuredParameters)
        self._measured_parameters_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_measured_parameters = False  # Флаг для предотвращения параллельных чтений

        # Таймер для чтения регистров Additional Parameters (6011-6201) - быстрое обновление
        self._additional_parameters_timer = QTimer(self)
        self._additional_parameters_timer.timeout.connect(self._readAdditionalParameters)
        self._additional_parameters_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_additional_parameters = False  # Флаг для предотвращения параллельных чтений
        
        # Таймер для чтения регистров Manual mode settings (6301-6381) - быстрое обновление
        self._manual_mode_settings_timer = QTimer(self)
        self._manual_mode_settings_timer.timeout.connect(self._readManualModeSettings)
        self._manual_mode_settings_timer.setInterval(300)  # Чтение каждые 300 мс для максимально быстрого обновления
        self._reading_manual_mode_settings = False  # Флаг для предотвращения параллельных чтений

        # Список таймеров для паузы/возобновления опросов
        self._polling_timers = [
            self._connection_check_timer,
            self._sync_timer,
            self._relay_1021_timer,
            self._valve_1111_timer,
            self._water_chiller_temp_timer,
            self._water_chiller_timer,
            self._seop_cell_temp_timer,
            self._magnet_psu_current_timer,
            self._laser_psu_current_timer,
            self._xenon_pressure_timer,
            self._n2_pressure_timer,
            self._vacuum_pressure_timer,
            self._fan_1131_timer,
            self._power_supply_timer,
            self._pid_controller_timer,
            self._alicats_timer,
            self._vacuum_controller_timer,
            self._laser_timer,
            self._seop_parameters_timer,
            self._calculated_parameters_timer,
            self._measured_parameters_timer,
            self._additional_parameters_timer,
            self._manual_mode_settings_timer,
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
    
    def _addLog(self, message: str):
        """Добавить сообщение в лог для отображения в Clinicalmode"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logMessageChanged.emit(log_entry)
        logger.info(f"LOG: {log_entry}")
    
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
    def enableRelayPolling(self):
        """Включить чтение регистра 1021 (реле) по требованию (например, при открытии External Relays)"""
        if self._is_connected and not self._polling_paused:
            if not self._relay_1021_timer.isActive():
                self._relay_1021_timer.start()
                logger.info("▶️ Опрос реле (регистр 1021) включен")
    
    @Slot()
    def disableRelayPolling(self):
        """Выключить чтение регистра 1021 (реле) по требованию (например, при закрытии External Relays)"""
        if self._relay_1021_timer.isActive():
            self._relay_1021_timer.stop()
            logger.info("⏸ Опрос реле (регистр 1021) выключен")
    
    @Slot()
    def enableValvePolling(self):
        """Включить чтение регистра 1111 (клапаны) по требованию (например, при открытии Valves and Fans)"""
        if self._is_connected and not self._polling_paused:
            if not self._valve_1111_timer.isActive():
                self._valve_1111_timer.start()
                logger.info("▶️ Опрос клапанов (регистр 1111) включен")
    
    @Slot()
    def disableValvePolling(self):
        """Выключить чтение регистра 1111 (клапаны) по требованию (например, при закрытии Valves and Fans)"""
        if self._valve_1111_timer.isActive():
            self._valve_1111_timer.stop()
            logger.info("⏸ Опрос клапанов (регистр 1111) выключен")
    
    @Slot()
    def enableFanPolling(self):
        """Включить чтение регистра 1131 (вентиляторы) по требованию (например, при открытии Valves and Fans)"""
        if self._is_connected and not self._polling_paused:
            if not self._fan_1131_timer.isActive():
                self._fan_1131_timer.start()
                logger.info("▶️ Опрос вентиляторов (регистр 1131) включен")
    
    @Slot()
    def disableFanPolling(self):
        """Выключить чтение регистра 1131 (вентиляторы) по требованию (например, при закрытии Valves and Fans)"""
        if self._fan_1131_timer.isActive():
            self._fan_1131_timer.stop()
            logger.info("⏸ Опрос вентиляторов (регистр 1131) выключен")
    
    @Slot()
    def enablePowerSupplyPolling(self):
        """Включить чтение регистров Power Supply (Laser PSU и Magnet PSU) по требованию (например, при открытии Power Supply)"""
        if self._is_connected and not self._polling_paused:
            if not self._power_supply_timer.isActive():
                self._power_supply_timer.start()
                logger.info("▶️ Опрос Power Supply включен")
    
    @Slot()
    def disablePowerSupplyPolling(self):
        """Выключить чтение регистров Power Supply по требованию (например, при закрытии Power Supply)"""
        if self._power_supply_timer.isActive():
            self._power_supply_timer.stop()
            logger.info("⏸ Опрос Power Supply выключен")
    
    @Slot()
    def enablePIDControllerPolling(self):
        """Включить чтение регистров PID Controller (1411, 1421, 1431) по требованию (например, при открытии PID Controller)"""
        if self._is_connected and not self._polling_paused:
            if not self._pid_controller_timer.isActive():
                self._pid_controller_timer.start()
                logger.info("▶️ Опрос PID Controller включен")
    
    @Slot()
    def disablePIDControllerPolling(self):
        """Выключить чтение регистров PID Controller по требованию (например, при закрытии PID Controller)"""
        if self._pid_controller_timer.isActive():
            self._pid_controller_timer.stop()
            logger.info("⏸ Опрос PID Controller выключен")
    
    @Slot()
    def enableWaterChillerPolling(self):
        """Включить чтение регистров Water Chiller (1511, 1521, 1531, 1541) по требованию (например, при открытии Water Chiller)"""
        logger.info(f"enableWaterChillerPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._water_chiller_timer.isActive():
                self._water_chiller_timer.start()
                logger.info("▶️ Опрос Water Chiller включен")
            else:
                logger.info("⏸ Опрос Water Chiller уже активен")
        else:
            logger.warning(f"⏸ Опрос Water Chiller не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableWaterChillerPolling(self):
        """Выключить чтение регистров Water Chiller по требованию (например, при закрытии Water Chiller)"""
        if self._water_chiller_timer.isActive():
            self._water_chiller_timer.stop()
            logger.info("⏸ Опрос Water Chiller выключен")
    
    @Slot()
    def enableAlicatsPolling(self):
        """Включить чтение регистров Alicats (1611, 1621, 1651, 1661) по требованию (например, при открытии Alicats)"""
        logger.info(f"enableAlicatsPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._alicats_timer.isActive():
                self._alicats_timer.start()
                logger.info("▶️ Опрос Alicats включен")
            else:
                logger.info("⏸ Опрос Alicats уже активен")
        else:
            logger.warning(f"⏸ Опрос Alicats не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableAlicatsPolling(self):
        """Выключить чтение регистров Alicats по требованию (например, при закрытии Alicats)"""
        if self._alicats_timer.isActive():
            self._alicats_timer.stop()
            logger.info("⏸ Опрос Alicats выключен")
    
    @Slot()
    def enableVacuumControllerPolling(self):
        """Включить чтение регистра Vacuum Controller (1701) по требованию (например, при открытии Vacuum Controller)"""
        logger.info(f"enableVacuumControllerPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        # Включаем опрос даже если устройство не подключено - поле должно отображаться всегда
        if not self._polling_paused:
            if not self._vacuum_controller_timer.isActive():
                self._vacuum_controller_timer.start()
                logger.info("▶️ Опрос Vacuum Controller включен")
            else:
                logger.info("⏸ Опрос Vacuum Controller уже активен")
        else:
            logger.info("⏸ Опрос Vacuum Controller приостановлен (polling paused)")
    
    @Slot()
    def disableVacuumControllerPolling(self):
        """Выключить чтение регистра Vacuum Controller по требованию (например, при закрытии Vacuum Controller)"""
        if self._vacuum_controller_timer.isActive():
            self._vacuum_controller_timer.stop()
            logger.info("⏸ Опрос Vacuum Controller выключен")
    
    @Slot()
    def enableLaserPolling(self):
        """Включить чтение регистров Laser (1811, 1821, 1831, 1841) по требованию (например, при открытии Laser)"""
        logger.info(f"enableLaserPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._laser_timer.isActive():
                self._laser_timer.start()
                logger.info("▶️ Опрос Laser включен")
            else:
                logger.info("⏸ Опрос Laser уже активен")
        else:
            logger.warning(f"⏸ Опрос Laser не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableLaserPolling(self):
        """Выключить чтение регистров Laser по требованию (например, при закрытии Laser)"""
        if self._laser_timer.isActive():
            self._laser_timer.stop()
            logger.info("⏸ Опрос Laser выключен")
    
    @Slot()
    def enableSEOPParametersPolling(self):
        """Включить чтение регистров SEOP Parameters (3011-3081) по требованию (например, при открытии SEOP Parameters)"""
        logger.info(f"enableSEOPParametersPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._seop_parameters_timer.isActive():
                # Сразу делаем первое чтение, не ждем таймера
                self._readSEOPParameters()
                self._seop_parameters_timer.start()
                logger.info("▶️ Опрос SEOP Parameters включен (первое чтение выполнено сразу)")
            else:
                logger.info("⏸ Опрос SEOP Parameters уже активен")
        else:
            logger.warning(f"⏸ Опрос SEOP Parameters не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableSEOPParametersPolling(self):
        """Выключить чтение регистров SEOP Parameters по требованию (например, при закрытии SEOP Parameters)"""
        if self._seop_parameters_timer.isActive():
            self._seop_parameters_timer.stop()
            logger.info("⏸ Опрос SEOP Parameters выключен")
    
    @Slot()
    def enableCalculatedParametersPolling(self):
        """Включить чтение регистров Calculated Parameters (4011-4101) по требованию (например, при открытии Calculated Parameters)"""
        logger.info(f"enableCalculatedParametersPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._calculated_parameters_timer.isActive():
                # Сразу делаем первое чтение, не ждем таймера
                self._readCalculatedParameters()
                self._calculated_parameters_timer.start()
                logger.info("▶️ Опрос Calculated Parameters включен (первое чтение выполнено сразу)")
            else:
                logger.info("⏸ Опрос Calculated Parameters уже активен")
        else:
            logger.warning(f"⏸ Опрос Calculated Parameters не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableCalculatedParametersPolling(self):
        """Выключить чтение регистров Calculated Parameters по требованию (например, при закрытии Calculated Parameters)"""
        if self._calculated_parameters_timer.isActive():
            self._calculated_parameters_timer.stop()
            logger.info("⏸ Опрос Calculated Parameters выключен")
    
    @Slot()
    def enableMeasuredParametersPolling(self):
        """Включить чтение регистров Measured Parameters (5011-5081) по требованию (например, при открытии Measured Parameters)"""
        logger.info(f"enableMeasuredParametersPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._measured_parameters_timer.isActive():
                # Сразу делаем первое чтение, не ждем таймера
                self._readMeasuredParameters()
                self._measured_parameters_timer.start()
                logger.info("▶️ Опрос Measured Parameters включен (первое чтение выполнено сразу)")
            else:
                logger.info("⏸ Опрос Measured Parameters уже активен")
        else:
            logger.warning(f"⏸ Опрос Measured Parameters не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableMeasuredParametersPolling(self):
        """Выключить чтение регистров Measured Parameters по требованию (например, при закрытии Measured Parameters)"""
        if self._measured_parameters_timer.isActive():
            self._measured_parameters_timer.stop()
            logger.info("⏸ Опрос Measured Parameters выключен")
    
    @Slot()
    def enableAdditionalParametersPolling(self):
        """Включить чтение регистров Additional Parameters (6011-6201) по требованию (например, при открытии Additional Parameters)"""
        logger.info(f"enableAdditionalParametersPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._additional_parameters_timer.isActive():
                # Сразу делаем первое чтение, не ждем таймера
                self._readAdditionalParameters()
                self._additional_parameters_timer.start()
                logger.info("▶️ Опрос Additional Parameters включен (первое чтение выполнено сразу)")
            else:
                logger.info("⏸ Опрос Additional Parameters уже активен")
        else:
            logger.warning(f"⏸ Опрос Additional Parameters не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableAdditionalParametersPolling(self):
        """Выключить чтение регистров Additional Parameters по требованию (например, при закрытии Additional Parameters)"""
        if self._additional_parameters_timer.isActive():
            self._additional_parameters_timer.stop()
            logger.info("⏸ Опрос Additional Parameters выключен")
    
    @Slot()
    def enableManualModeSettingsPolling(self):
        """Включить чтение регистров Manual mode settings (6301-6381) по требованию (например, при открытии Manual mode settings)"""
        logger.info(f"enableManualModeSettingsPolling вызван: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
        if self._is_connected and not self._polling_paused:
            if not self._manual_mode_settings_timer.isActive():
                # Сразу делаем первое чтение, не ждем таймера
                self._readManualModeSettings()
                self._manual_mode_settings_timer.start()
                logger.info("▶️ Опрос Manual mode settings включен (первое чтение выполнено сразу)")
            else:
                logger.info("⏸ Опрос Manual mode settings уже активен")
        else:
            logger.warning(f"⏸ Опрос Manual mode settings не включен: _is_connected={self._is_connected}, _polling_paused={self._polling_paused}")
    
    @Slot()
    def disableManualModeSettingsPolling(self):
        """Выключить чтение регистров Manual mode settings (6301-6381)"""
        if self._manual_mode_settings_timer.isActive():
            self._manual_mode_settings_timer.stop()
            logger.info("⏸ Опрос Manual mode settings выключен")
    
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
    
    @Property(int, notify=seopCellNumberChanged)
    def seopCellNumber(self):
        """Cell number (регистр 3171)"""
        return self._seop_cell_number
    
    @Property(int, notify=seopRefillCycleChanged)
    def seopRefillCycle(self):
        """Refill cycle (регистр 3181)"""
        return self._seop_refill_cycle
    
    @Property(float, notify=calculatedFittedXePolarizationMaxChanged)
    def calculatedFittedXePolarizationMax(self):
        """Fitted 129Xe Polarization maximum (регистр 4071)"""
        return self._calculated_fitted_xe_polarization_max
    
    @Property(float, notify=calculatedFittedXePolarizationMaxErrorChanged)
    def calculatedFittedXePolarizationMaxError(self):
        """Fitted 129Xe Polarization max error bar (регистр 4081)"""
        return self._calculated_fitted_xe_polarization_max_error
    
    @Property(float, notify=calculatedXePolarizationChanged)
    def calculatedXePolarization(self):
        """129Xe Polarization (регистр 4021)"""
        return self._calculated_xe_polarization
    
    @Property(float, notify=calculatedXePolarizationErrorChanged)
    def calculatedXePolarizationError(self):
        """Error bar for 129Xe Polarization (регистр 4051)"""
        return self._calculated_xe_polarization_error
    
    @Property(float, notify=calculatedBuildupRateChanged)
    def calculatedBuildupRate(self):
        """The buildup rate (g-SEOP) (регистр 4031)"""
        return self._calculated_buildup_rate
    
    @Property(float, notify=calculatedBuildupRateErrorChanged)
    def calculatedBuildupRateError(self):
        """Error bar for the buildup rate (g-SEOP) (регистр 4061)"""
        return self._calculated_buildup_rate_error
    
    @Property(float, notify=calculatedHPXeT1Changed)
    def calculatedHPXeT1(self):
        """HP 129Xe T1 (регистр 4091)"""
        return self._calculated_hp_xe_t1
    
    @Property(float, notify=calculatedHPXeT1ErrorChanged)
    def calculatedHPXeT1Error(self):
        """Error bar for 129Xe T1 (регистр 4101)"""
        return self._calculated_hp_xe_t1_error
    
    @Property(float, notify=calculatedElectronPolarizationChanged)
    def calculatedElectronPolarization(self):
        """Electron Polarization (PRb) (регистр 4011)"""
        return self._calculated_electron_polarization
    
    @Property(float, notify=calculatedElectronPolarizationErrorChanged)
    def calculatedElectronPolarizationError(self):
        """Error bar for Electron Polarization (регистр 4041)"""
        return self._calculated_electron_polarization_error
    
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
        self._pid_controller_setpoint_auto_update_timer.start()
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
        elif key == "power_supply":
            self._applyPowerSupplyValue(value)
        elif key == "pid_controller":
            self._applyPIDControllerValue(value)
        elif key == "water_chiller":
            self._applyWaterChillerValue(value)
        elif key == "alicats":
            self._applyAlicatsValue(value)
        elif key == "vacuum_controller":
            self._applyVacuumControllerValue(value)
        elif key == "laser":
            self._applyLaserValue(value)
        elif key == "seop_parameters":
            self._applySEOPParametersValue(value)
        elif key == "calculated_parameters":
            self._applyCalculatedParametersValue(value)
        elif key == "measured_parameters":
            self._applyMeasuredParametersValue(value)
        elif key == "additional_parameters":
            self._applyAdditionalParametersValue(value)
        elif key == "manual_mode_settings":
            self._applyManualModeSettingsValue(value)
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

    def _applyPowerSupplyValue(self, value: object):
        """Применение результатов чтения Power Supply (Laser PSU и Magnet PSU)"""
        self._reading_power_supply = False
        if value is None or not isinstance(value, dict):
            return
        
        # Laser PSU
        if 'laser_voltage' in value:
            self.laserPSUVoltageChanged.emit(float(value['laser_voltage']))
        if 'laser_current' in value:
            self.laserPSUCurrentChanged.emit(float(value['laser_current']))
        if 'laser_voltage_setpoint' in value:
            self.laserPSUVoltageSetpointChanged.emit(float(value['laser_voltage_setpoint']))
        if 'laser_current_setpoint' in value:
            self.laserPSUSetpointChanged.emit(float(value['laser_current_setpoint']))
        if 'laser_state' in value:
            self.laserPSUStateChanged.emit(bool(value['laser_state']))
        
        # Magnet PSU
        if 'magnet_voltage' in value:
            self.magnetPSUVoltageChanged.emit(float(value['magnet_voltage']))
        if 'magnet_current' in value:
            self.magnetPSUCurrentChanged.emit(float(value['magnet_current']))
        if 'magnet_voltage_setpoint' in value:
            self.magnetPSUVoltageSetpointChanged.emit(float(value['magnet_voltage_setpoint']))
        if 'magnet_current_setpoint' in value:
            self.magnetPSUSetpointChanged.emit(float(value['magnet_current_setpoint']))
        if 'magnet_state' in value:
            self.magnetPSUStateChanged.emit(bool(value['magnet_state']))
    
    def _applyPIDControllerValue(self, value: object):
        """Применение результатов чтения PID Controller (1411, 1421, 1431)"""
        self._reading_pid_controller = False
        if value is None or not isinstance(value, dict):
            return
        
        if 'temperature' in value:
            temp = float(value['temperature'])
            self._pid_controller_temperature = temp
            self.pidControllerTemperatureChanged.emit(temp)
        if 'setpoint' in value:
            setpoint = float(value['setpoint'])
            # Обновляем только если пользователь не взаимодействует с полем
            if not self._pid_controller_setpoint_user_interaction:
                self._pid_controller_setpoint = setpoint
                self.pidControllerSetpointChanged.emit(setpoint)
        if 'state' in value:
            state = bool(value['state'])
            self._pid_controller_state = state
            self.pidControllerStateChanged.emit(state)
    
    def _applyWaterChillerValue(self, value: object):
        """Применение результатов чтения Water Chiller (1511, 1521, 1531, 1541)"""
        self._reading_water_chiller = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyWaterChillerValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyWaterChillerValue: received value={value}")
        
        if 'inlet_temperature' in value:
            temp = float(value['inlet_temperature'])
            self._water_chiller_inlet_temperature = temp
            self._water_chiller_temperature = temp  # Для обратной совместимости
            self.waterChillerInletTemperatureChanged.emit(temp)
            self.waterChillerTemperatureChanged.emit(temp)  # Старый сигнал для обратной совместимости
            logger.debug(f"Water Chiller inlet temperature: {temp}°C")
        if 'outlet_temperature' in value:
            temp = float(value['outlet_temperature'])
            self._water_chiller_outlet_temperature = temp
            self.waterChillerOutletTemperatureChanged.emit(temp)
            logger.debug(f"Water Chiller outlet temperature: {temp}°C")
        if 'setpoint' in value:
            setpoint = float(value['setpoint'])
            # Обновляем только если пользователь не взаимодействует с полем
            if not self._water_chiller_setpoint_user_interaction:
                self._water_chiller_setpoint = setpoint
                self.waterChillerSetpointChanged.emit(setpoint)
                logger.debug(f"Water Chiller setpoint: {setpoint}°C")
        if 'state' in value:
            state = bool(value['state'])
            self._water_chiller_state = state
            self.waterChillerStateChanged.emit(state)
            logger.debug(f"Water Chiller state: {state}")
    
    def _applyAlicatsValue(self, value: object):
        """Применение результатов чтения Alicats (1611, 1621, 1651, 1661)"""
        self._reading_alicats = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyAlicatsValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyAlicatsValue: received value={value}")
        
        if 'xenon_pressure' in value:
            pressure = float(value['xenon_pressure'])
            self._xenon_pressure = pressure
            self.xenonPressureChanged.emit(pressure)
            logger.debug(f"Alicat 1 Xenon pressure: {pressure} Torr")
        if 'xenon_setpoint' in value:
            setpoint = float(value['xenon_setpoint'])
            # Обновляем только если пользователь не взаимодействует с полем
            if not self._xenon_setpoint_user_interaction:
                self._xenon_setpoint = setpoint
                self.xenonSetpointChanged.emit(setpoint)
                logger.debug(f"Alicat 1 Xenon setpoint: {setpoint} Torr")
        if 'n2_pressure' in value:
            pressure = float(value['n2_pressure'])
            self._n2_pressure = pressure
            self.n2PressureChanged.emit(pressure)
            logger.debug(f"Alicat 2 N2 pressure: {pressure} Torr")
        if 'n2_setpoint' in value:
            setpoint = float(value['n2_setpoint'])
            # Обновляем только если пользователь не взаимодействует с полем
            if not self._n2_setpoint_user_interaction:
                self._n2_setpoint = setpoint
                self.n2SetpointChanged.emit(setpoint)
                logger.debug(f"Alicat 2 N2 setpoint: {setpoint} Torr")
    
    def _applyVacuumControllerValue(self, value: object):
        """Применение результатов чтения Vacuum Controller (1701)"""
        self._reading_vacuum_controller = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyVacuumControllerValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyVacuumControllerValue: received value={value}")
        
        if 'pressure' in value:
            pressure_mtorr = float(value['pressure'])
            self._vacuum_controller_pressure = pressure_mtorr
            self.vacuumControllerPressureChanged.emit(pressure_mtorr)
            logger.debug(f"Vacuum Controller pressure: {pressure_mtorr} mTorr")
    
    def _applyLaserValue(self, value: object):
        """Применение результатов чтения Laser (1811, 1821, 1831, 1841)"""
        self._reading_laser = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyLaserValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyLaserValue: received value={value}")
        
        if 'beam_state' in value:
            state = bool(value['beam_state'])
            self._laser_beam_state = state
            self.laserBeamStateChanged.emit(state)
            logger.debug(f"Laser Beam state: {state}")
        if 'mpd' in value:
            mpd = float(value['mpd'])
            self._laser_mpd = mpd
            self.laserMPDChanged.emit(mpd)
            logger.debug(f"Laser MPD: {mpd} uA")
        if 'output_power' in value:
            output_power = float(value['output_power'])
            self._laser_output_power = output_power
            self.laserOutputPowerChanged.emit(output_power)
            logger.debug(f"Laser Output Power: {output_power}")
        if 'temp' in value:
            temp = float(value['temp'])
            self._laser_temp = temp
            self.laserTempChanged.emit(temp)
            logger.debug(f"Laser Temp: {temp}")
    
    def _applySEOPParametersValue(self, value: object):
        """Применение результатов чтения SEOP Parameters (3011-3081)"""
        self._reading_seop_parameters = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applySEOPParametersValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applySEOPParametersValue: received value={value}")
        
        if 'laser_max_temp' in value:
            temp = float(value['laser_max_temp'])
            if not self._seop_laser_max_temp_user_interaction:
                self._seop_laser_max_temp = temp
                self.seopLaserMaxTempChanged.emit(temp)
                logger.debug(f"SEOP Laser Max Temp: {temp}°C")
        if 'laser_min_temp' in value:
            temp = float(value['laser_min_temp'])
            if not self._seop_laser_min_temp_user_interaction:
                self._seop_laser_min_temp = temp
                self.seopLaserMinTempChanged.emit(temp)
                logger.debug(f"SEOP Laser Min Temp: {temp}°C")
        if 'cell_max_temp' in value:
            temp = float(value['cell_max_temp'])
            if not self._seop_cell_max_temp_user_interaction:
                self._seop_cell_max_temp = temp
                self.seopCellMaxTempChanged.emit(temp)
                logger.debug(f"SEOP Cell Max Temp: {temp}°C")
        if 'cell_min_temp' in value:
            temp = float(value['cell_min_temp'])
            if not self._seop_cell_min_temp_user_interaction:
                self._seop_cell_min_temp = temp
                self.seopCellMinTempChanged.emit(temp)
                logger.debug(f"SEOP Cell Min Temp: {temp}°C")
        if 'ramp_temp' in value:
            temp = float(value['ramp_temp'])
            if not self._seop_ramp_temp_user_interaction:
                self._seop_ramp_temp = temp
                self.seopRampTempChanged.emit(temp)
                logger.debug(f"SEOP Ramp Temp: {temp}°C")
        if 'seop_temp' in value:
            temp = float(value['seop_temp'])
            if not self._seop_temp_user_interaction:
                self._seop_temp = temp
                self.seopTempChanged.emit(temp)
                logger.debug(f"SEOP Temp: {temp}°C")
        if 'cell_refill_temp' in value:
            temp = float(value['cell_refill_temp'])
            if not self._seop_cell_refill_temp_user_interaction:
                self._seop_cell_refill_temp = temp
                self.seopCellRefillTempChanged.emit(temp)
                logger.debug(f"SEOP Cell Refill Temp: {temp}°C")
        if 'loop_time' in value:
            time_val = float(value['loop_time'])
            if not self._seop_loop_time_user_interaction:
                self._seop_loop_time = time_val
                self.seopLoopTimeChanged.emit(time_val)
                logger.debug(f"SEOP Loop Time: {time_val} s")
        if 'process_duration' in value:
            duration = float(value['process_duration'])
            if not self._seop_process_duration_user_interaction:
                self._seop_process_duration = duration
                self.seopProcessDurationChanged.emit(duration)
                logger.debug(f"SEOP Process Duration: {duration} min")
        if 'laser_max_output_power' in value:
            power = float(value['laser_max_output_power'])
            if not self._seop_laser_max_output_power_user_interaction:
                self._seop_laser_max_output_power = power
                self.seopLaserMaxOutputPowerChanged.emit(power)
                logger.debug(f"SEOP Laser Max Output Power: {power} W")
        if 'laser_psu_max_current' in value:
            current = float(value['laser_psu_max_current'])
            if not self._seop_laser_psu_max_current_user_interaction:
                self._seop_laser_psu_max_current = current
                self.seopLaserPSUMaxCurrentChanged.emit(current)
                logger.debug(f"SEOP Laser PSU MAX Current: {current} A")
        if 'water_chiller_max_temp' in value:
            temp = float(value['water_chiller_max_temp'])
            if not self._seop_water_chiller_max_temp_user_interaction:
                self._seop_water_chiller_max_temp = temp
                self.seopWaterChillerMaxTempChanged.emit(temp)
                logger.debug(f"SEOP Water Chiller Max Temp: {temp}°C")
        if 'water_chiller_min_temp' in value:
            temp = float(value['water_chiller_min_temp'])
            if not self._seop_water_chiller_min_temp_user_interaction:
                self._seop_water_chiller_min_temp = temp
                self.seopWaterChillerMinTempChanged.emit(temp)
                logger.debug(f"SEOP Water Chiller Min Temp: {temp}°C")
        if 'xe_concentration' in value:
            concentration = float(value['xe_concentration'])
            if not self._seop_xe_concentration_user_interaction:
                self._seop_xe_concentration = concentration
                self.seopXeConcentrationChanged.emit(concentration)
                logger.debug(f"SEOP 129Xe concentration: {concentration} mMol")
        if 'water_proton_concentration' in value:
            concentration = float(value['water_proton_concentration'])
            if not self._seop_water_proton_concentration_user_interaction:
                self._seop_water_proton_concentration = concentration
                self.seopWaterProtonConcentrationChanged.emit(concentration)
                logger.debug(f"SEOP Water proton concentration: {concentration} Mol")
        if 'cell_number' in value:
            cell_num = int(value['cell_number'])
            if not self._seop_cell_number_user_interaction:
                self._seop_cell_number = cell_num
                self.seopCellNumberChanged.emit(cell_num)
                logger.debug(f"SEOP Cell number: {cell_num}")
        if 'refill_cycle' in value:
            refill = int(value['refill_cycle'])
            if not self._seop_refill_cycle_user_interaction:
                self._seop_refill_cycle = refill
                self.seopRefillCycleChanged.emit(refill)
                logger.debug(f"SEOP Refill cycle: {refill}")
    
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
            import struct
            # Читаем 400..414 и 420..477 (как в test_modbus при ir)
            # Метаданные лучше читать одним блоком (15 регистров) — иначе иногда "плывут" поля.
            meta = client.read_input_registers_direct(400, 15, max_chunk=15)
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
            # Метаданные IR (как в test_modbus): устройство реально хранит x/y range в регистрах
            # 401-408, но порядок слов/байт может отличаться. Подбираем вариант по x_min/x_max,
            # чтобы далее декодировать остальные float (y_min/y_max/res_freq/freq/integral) в том же формате.

            def _float_variants_from_regs(reg1: int, reg2: int) -> dict:
                """
                Декодируем float из двух uint16 во всех популярных Modbus byte/word order.
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
            else:
                # fallback (старое поведение)
                x_min = 792.0
                x_max = 798.0

            # Декодируем остальные float-метаданные в том же формате, если удалось подобрать ключ
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

                # Иногда отдельные поля могут приехать "битые". Тогда добираем res_freq/freq
                # из вариантов, которые попадают в диапазон X.
                def _pick_any_in_range(reg1: int, reg2: int, lo: float, hi: float) -> float:
                    vmap = _float_variants_from_regs(reg1, reg2)
                    in_range = [v for v in vmap.values() if lo <= v <= hi]
                    if not in_range:
                        return float("nan")
                    # выбираем ближе к центру диапазона
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
                # Fallback: старый IR байтсвап (для некоторых полей может быть неверно, но лучше чем NaN)
                y_min_meta = self._registers_to_float_ir(y_min_r1, y_min_r2)
                y_max_meta = self._registers_to_float_ir(y_max_r1, y_max_r2)

                # Для палок пробуем подобрать вариант, который попадает в диапазон X
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
                    res_freq = self._registers_to_float_ir(res_r1, res_r2)
                if not math.isfinite(freq):
                    freq = self._registers_to_float_ir(freq_r1, freq_r2)

                integral = self._registers_to_float_ir(int_r1, int_r2)

            # Для логов/передачи: y_min/y_max по умолчанию берем из метаданных (как в регистре),
            # но если невалидно — позже перетрем диапазоном по данным.
            y_min = float(y_min_meta) if math.isfinite(y_min_meta) else 0.0
            y_max = float(y_max_meta) if math.isfinite(y_max_meta) else 1.0

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
                "meta_float_key": meta_float_key,
                "x_min_regs": [xmin_r1, xmin_r2],
                "x_max_regs": [xmax_r1, xmax_r2],
                "y_min_regs": [y_min_r1, y_min_r2],
                "y_max_regs": [y_max_r1, y_max_r2],
                "y_min_meta": float(y_min_meta) if math.isfinite(y_min_meta) else None,
                "y_max_meta": float(y_max_meta) if math.isfinite(y_max_meta) else None,
                # Диагностика декодирования "палок" (409-410 / 411-412)
                "res_freq_regs": [res_r1, res_r2],
                "freq_regs": [freq_r1, freq_r2],
                "x_min_variants": {k: float(v) for k, v in x_min_variants.items()},
                "x_max_variants": {k: float(v) for k, v in x_max_variants.items()},
                "res_freq_variants": {k: float(v) for k, v in _float_variants_from_regs(res_r1, res_r2).items()},
                "freq_variants": {k: float(v) for k, v in _float_variants_from_regs(freq_r1, freq_r2).items()},
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
    
    def _autoUpdatePIDControllerSetpoint(self):
        """
        Автоматическое обновление setpoint PID Controller из текущей температуры, если пользователь не взаимодействует с полем
        Вызывается каждые 20 секунд
        """
        if not self._is_connected:
            return
        
        # Если пользователь не взаимодействовал с полем, обновляем setpoint из текущей температуры
        if not self._pid_controller_setpoint_user_interaction:
            # Не обновляем если текущая температура равна 0.0 или невалидная (устройство только подключено)
            if self._pid_controller_temperature > 0.1 and abs(self._pid_controller_temperature - self._pid_controller_setpoint) > 0.1:  # Обновляем только если разница > 0.1°C и температура валидная
                logger.info(f"Автообновление setpoint PID Controller: {self._pid_controller_setpoint}°C -> {self._pid_controller_temperature}°C")
                self._pid_controller_setpoint = self._pid_controller_temperature
                self.pidControllerSetpointChanged.emit(self._pid_controller_temperature)
        else:
            # Сбрасываем флаг взаимодействия для следующего цикла
            self._pid_controller_setpoint_user_interaction = False
    
    def _autoUpdateXenonSetpoint(self):
        """Автоматическое обновление setpoint Xenon из устройства (если пользователь не взаимодействует с полем)"""
        if not self._xenon_setpoint_user_interaction:
            # Пользователь не взаимодействует с полем - можно обновить из устройства
            logger.debug("Автообновление setpoint Xenon из устройства")
            # Чтение будет выполнено через таймер _alicats_timer
        else:
            # Пользователь взаимодействует с полем - не обновляем
            logger.debug("Автообновление setpoint Xenon пропущено (пользователь взаимодействует с полем)")
        # Сбрасываем флаг взаимодействия пользователя
        self._xenon_setpoint_user_interaction = False
    
    def _autoUpdateN2Setpoint(self):
        """Автоматическое обновление setpoint N2 из устройства (если пользователь не взаимодействует с полем)"""
        if not self._n2_setpoint_user_interaction:
            # Пользователь не взаимодействует с полем - можно обновить из устройства
            logger.debug("Автообновление setpoint N2 из устройства")
            # Чтение будет выполнено через таймер _alicats_timer
        else:
            # Пользователь взаимодействует с полем - не обновляем
            logger.debug("Автообновление setpoint N2 пропущено (пользователь взаимодействует с полем)")
        # Сбрасываем флаг взаимодействия пользователя
        self._n2_setpoint_user_interaction = False
    
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
        # Логируем действие
        self._addLog(f"Xenon Pressure: {pressure} Torr")
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
        # Логируем действие
        self._addLog(f"N2 Pressure: {pressure} Torr")
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
    
    def _readPowerSupply(self):
        """Чтение регистров Power Supply (Laser PSU и Magnet PSU)"""
        if not self._is_connected or self._modbus_client is None or self._reading_power_supply:
            return

        self._reading_power_supply = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Power Supply"""
            import struct
            # Laser PSU: Voltage Value (1211), Voltage Setpoint (1221), Current Value (1231), Current Setpoint (1241), On/Off (1251)
            # Magnet PSU: Voltage Value (1301), Voltage Setpoint (1311), Current Value (1321), Current Setpoint (1331), On/Off (1341)
            # Читаем по 2 регистра для float значений (Voltage и Current)
            laser_voltage_regs = client.read_input_registers_direct(1211, 2, max_chunk=2)
            laser_current_regs = client.read_input_registers_direct(1231, 2, max_chunk=2)
            laser_voltage_setpoint_regs = client.read_input_registers_direct(1221, 2, max_chunk=2)
            laser_current_setpoint_regs = client.read_input_registers_direct(1241, 2, max_chunk=2)
            laser_state_reg = client.read_input_registers_direct(1251, 1, max_chunk=1)
            
            magnet_voltage_regs = client.read_input_registers_direct(1301, 2, max_chunk=2)
            magnet_current_regs = client.read_input_registers_direct(1321, 2, max_chunk=2)
            magnet_voltage_setpoint_regs = client.read_input_registers_direct(1311, 2, max_chunk=2)
            magnet_current_setpoint_regs = client.read_input_registers_direct(1331, 2, max_chunk=2)
            magnet_state_reg = client.read_input_registers_direct(1341, 1, max_chunk=1)
            
            # Декодируем float из двух регистров (используем тот же метод, что и для IR)
            def _registers_to_float(reg1: int, reg2: int) -> float:
                """Декодируем float из двух uint16 (порядок байт: ABCD)"""
                try:
                    byte1 = (reg1 >> 8) & 0xFF
                    byte2 = reg1 & 0xFF
                    byte3 = (reg2 >> 8) & 0xFF
                    byte4 = reg2 & 0xFF
                    # Попробуем разные варианты порядка байт
                    variants = [
                        bytes([byte1, byte2, byte3, byte4]),  # ABCD
                        bytes([byte2, byte1, byte4, byte3]),  # BADC
                        bytes([byte3, byte4, byte1, byte2]),  # CDAB
                        bytes([byte4, byte3, byte2, byte1]),  # DCBA
                    ]
                    for bb in variants:
                        try:
                            val = float(struct.unpack(">f", bb)[0])
                            if val != 0.0 and -1000.0 < val < 1000.0:  # Разумный диапазон для напряжения/тока
                                return val
                        except:
                            continue
                    # Если ничего не подошло, пробуем просто разделить на 100 (как для температуры)
                    return float((reg1 << 16 | reg2) / 100.0) if (reg1 << 16 | reg2) != 0 else 0.0
                except Exception:
                    return 0.0
            
            result = {}
            
            # Laser PSU
            if laser_voltage_regs and len(laser_voltage_regs) >= 2:
                result['laser_voltage'] = _registers_to_float(int(laser_voltage_regs[0]), int(laser_voltage_regs[1]))
            if laser_current_regs and len(laser_current_regs) >= 2:
                result['laser_current'] = _registers_to_float(int(laser_current_regs[0]), int(laser_current_regs[1]))
            if laser_voltage_setpoint_regs and len(laser_voltage_setpoint_regs) >= 2:
                result['laser_voltage_setpoint'] = _registers_to_float(int(laser_voltage_setpoint_regs[0]), int(laser_voltage_setpoint_regs[1]))
            if laser_current_setpoint_regs and len(laser_current_setpoint_regs) >= 2:
                result['laser_current_setpoint'] = _registers_to_float(int(laser_current_setpoint_regs[0]), int(laser_current_setpoint_regs[1]))
            if laser_state_reg and len(laser_state_reg) >= 1:
                result['laser_state'] = bool(int(laser_state_reg[0]) & 0x01)
            
            # Magnet PSU
            if magnet_voltage_regs and len(magnet_voltage_regs) >= 2:
                result['magnet_voltage'] = _registers_to_float(int(magnet_voltage_regs[0]), int(magnet_voltage_regs[1]))
            if magnet_current_regs and len(magnet_current_regs) >= 2:
                result['magnet_current'] = _registers_to_float(int(magnet_current_regs[0]), int(magnet_current_regs[1]))
            if magnet_voltage_setpoint_regs and len(magnet_voltage_setpoint_regs) >= 2:
                result['magnet_voltage_setpoint'] = _registers_to_float(int(magnet_voltage_setpoint_regs[0]), int(magnet_voltage_setpoint_regs[1]))
            if magnet_current_setpoint_regs and len(magnet_current_setpoint_regs) >= 2:
                result['magnet_current_setpoint'] = _registers_to_float(int(magnet_current_setpoint_regs[0]), int(magnet_current_setpoint_regs[1]))
            if magnet_state_reg and len(magnet_state_reg) >= 1:
                result['magnet_state'] = bool(int(magnet_state_reg[0]) & 0x01)
            
            return result
        
        self._enqueue_read("power_supply", task)
    
    def _readPIDController(self):
        """Чтение регистров PID Controller (1411 - температура, 1421 - setpoint, 1431 - on/off)"""
        if not self._is_connected or self._modbus_client is None or self._reading_pid_controller:
            return

        self._reading_pid_controller = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров PID Controller"""
            # Регистр 1411 - температура (value) в градусах Цельсия
            temp_value = client.read_register_1411_direct()
            # Регистр 1421 - setpoint в градусах Цельсия
            setpoint_value = client.read_register_1421_direct()
            # Регистр 1431 - on/off (1 = вкл, 0 = выкл)
            state_value = client.read_input_registers_direct(1431, 1, max_chunk=1)
            
            result = {}
            if temp_value is not None:
                # Преобразуем из int (температура * 100) в float
                result['temperature'] = float(temp_value) / 100.0
            if setpoint_value is not None:
                # Преобразуем из int (температура * 100) в float
                result['setpoint'] = float(setpoint_value) / 100.0
            if state_value and len(state_value) >= 1:
                result['state'] = bool(int(state_value[0]) & 0x01)
            
            return result
        
        self._enqueue_read("pid_controller", task)
    
    def _readWaterChiller(self):
        """Чтение регистров Water Chiller (1511 - inlet temp, 1521 - outlet temp, 1531 - setpoint, 1541 - on/off)"""
        if not self._is_connected or self._modbus_client is None or self._reading_water_chiller:
            return

        self._reading_water_chiller = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Water Chiller"""
            # Регистр 1511 - температура на входе (inlet temp) в градусах Цельсия
            inlet_temp_value = client.read_register_1511_direct()
            # Регистр 1521 - температура на выходе (outlet temp) в градусах Цельсия
            outlet_temp_regs = client.read_input_registers_direct(1521, 1, max_chunk=1)
            # Регистр 1531 - setpoint в градусах Цельсия (holding register, пробуем через read_holding_register)
            setpoint_value = client.read_holding_register(1531)
            # Регистр 1541 - on/off (1 = вкл, 0 = выкл)
            state_regs = client.read_input_registers_direct(1541, 1, max_chunk=1)
            
            result = {}
            if inlet_temp_value is not None:
                # Преобразуем из int (температура * 100) в float
                result['inlet_temperature'] = float(inlet_temp_value) / 100.0
            if outlet_temp_regs and len(outlet_temp_regs) >= 1:
                # Преобразуем из int (температура * 100) в float
                result['outlet_temperature'] = float(int(outlet_temp_regs[0])) / 100.0
            if setpoint_value is not None:
                # Преобразуем из int (температура * 100) в float
                result['setpoint'] = float(int(setpoint_value)) / 100.0
            if state_regs and len(state_regs) >= 1:
                result['state'] = bool(int(state_regs[0]) & 0x01)
            
            return result
        
        self._enqueue_read("water_chiller", task)
    
    def _readAlicats(self):
        """Чтение регистров Alicats (1611 - Xenon value, 1621 - Xenon setpoint, 1651 - N2 value, 1661 - N2 setpoint)"""
        if not self._is_connected or self._modbus_client is None or self._reading_alicats:
            return

        self._reading_alicats = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Alicats"""
            # Alicat 1 Xenon: value Torr (регистр 1611), setpoint Torr (регистр 1621)
            xenon_value_regs = client.read_input_registers_direct(1611, 1, max_chunk=1)
            xenon_setpoint_value = client.read_holding_register(1621)
            
            # Alicat 2 N2: value Torr (регистр 1651), setpoint Torr (регистр 1661)
            n2_value_regs = client.read_input_registers_direct(1651, 1, max_chunk=1)
            n2_setpoint_value = client.read_holding_register(1661)
            
            result = {}
            if xenon_value_regs and len(xenon_value_regs) >= 1:
                # Преобразуем из int (давление * 100) в float
                result['xenon_pressure'] = float(int(xenon_value_regs[0])) / 100.0
            if xenon_setpoint_value is not None:
                # Преобразуем из int (давление * 100) в float
                result['xenon_setpoint'] = float(int(xenon_setpoint_value)) / 100.0
            if n2_value_regs and len(n2_value_regs) >= 1:
                # Преобразуем из int (давление * 100) в float
                result['n2_pressure'] = float(int(n2_value_regs[0])) / 100.0
            if n2_setpoint_value is not None:
                # Преобразуем из int (давление * 100) в float
                result['n2_setpoint'] = float(int(n2_setpoint_value)) / 100.0
            
            return result
        
        self._enqueue_read("alicats", task)
    
    def _readVacuumController(self):
        """Чтение регистра Vacuum Controller (1701 - давление в mTorr)"""
        # Проверяем только флаг чтения и наличие клиента, но не подключение
        # Поле должно отображаться всегда, даже если устройство не подключено
        if self._modbus_client is None or self._reading_vacuum_controller:
            return
        
        # Если устройство не подключено, не пытаемся читать, но таймер продолжает работать
        if not self._is_connected:
            logger.debug("Vacuum Controller: устройство не подключено, пропускаем чтение")
            return

        self._reading_vacuum_controller = True
        client = self._modbus_client
        
        def task():
            """Чтение регистра Vacuum Controller"""
            # Регистр 1701 - давление Vacuum (уже в mTorr)
            value = client.read_register_1701_direct()
            
            result = {}
            if value is not None:
                # Значение уже в mTorr, просто преобразуем в float
                pressure_mtorr = float(int(value))
                result['pressure'] = pressure_mtorr
            
            return result
        
        self._enqueue_read("vacuum_controller", task)
    
    def _readLaser(self):
        """Чтение регистров Laser (1811 - Beam on/off, 1821 - MPD uA, 1831 - Output Power, 1841 - Temp)"""
        if not self._is_connected or self._modbus_client is None or self._reading_laser:
            return

        self._reading_laser = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Laser"""
            # Регистр 1811 - Beam on/off (1 = on, 0 = off)
            beam_state_regs = client.read_input_registers_direct(1811, 1, max_chunk=1)
            # Регистр 1821 - MPD в uA
            mpd_regs = client.read_input_registers_direct(1821, 1, max_chunk=1)
            # Регистр 1831 - Output Power
            output_power_regs = client.read_input_registers_direct(1831, 1, max_chunk=1)
            # Регистр 1841 - Temp
            temp_regs = client.read_input_registers_direct(1841, 1, max_chunk=1)
            
            result = {}
            if beam_state_regs and len(beam_state_regs) >= 1:
                result['beam_state'] = bool(int(beam_state_regs[0]) & 0x01)
            if mpd_regs and len(mpd_regs) >= 1:
                # MPD в uA - значение уже в нужных единицах
                result['mpd'] = float(int(mpd_regs[0]))
            if output_power_regs and len(output_power_regs) >= 1:
                # Output Power - значение уже в нужных единицах
                result['output_power'] = float(int(output_power_regs[0]))
            if temp_regs and len(temp_regs) >= 1:
                # Temp - значение уже в нужных единицах
                result['temp'] = float(int(temp_regs[0]))
            
            return result
        
        self._enqueue_read("laser", task)
    
    def _readSEOPParameters(self):
        """Чтение регистров SEOP Parameters (3011-3181)"""
        if not self._is_connected or self._modbus_client is None or self._reading_seop_parameters:
            return

        self._reading_seop_parameters = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров SEOP Parameters"""
            # Регистры 3011-3081 - первые 8 параметров
            laser_max_temp_regs = client.read_input_registers_direct(3011, 1, max_chunk=1)
            laser_min_temp_regs = client.read_input_registers_direct(3021, 1, max_chunk=1)
            cell_max_temp_regs = client.read_input_registers_direct(3031, 1, max_chunk=1)
            cell_min_temp_regs = client.read_input_registers_direct(3041, 1, max_chunk=1)
            ramp_temp_regs = client.read_input_registers_direct(3051, 1, max_chunk=1)
            seop_temp_regs = client.read_input_registers_direct(3061, 1, max_chunk=1)
            cell_refill_temp_regs = client.read_input_registers_direct(3071, 1, max_chunk=1)
            loop_time_regs = client.read_input_registers_direct(3081, 1, max_chunk=1)
            # Новые регистры 3091-3151
            process_duration_regs = client.read_input_registers_direct(3091, 1, max_chunk=1)
            laser_max_output_power_regs = client.read_input_registers_direct(3101, 1, max_chunk=1)
            laser_psu_max_current_regs = client.read_input_registers_direct(3111, 1, max_chunk=1)
            water_chiller_max_temp_regs = client.read_input_registers_direct(3121, 1, max_chunk=1)
            water_chiller_min_temp_regs = client.read_input_registers_direct(3131, 1, max_chunk=1)
            xe_concentration_regs = client.read_input_registers_direct(3141, 1, max_chunk=1)
            water_proton_concentration_regs = client.read_input_registers_direct(3151, 1, max_chunk=1)
            # Регистры 3171-3181
            cell_number_regs = client.read_input_registers_direct(3171, 1, max_chunk=1)
            refill_cycle_regs = client.read_input_registers_direct(3181, 1, max_chunk=1)
            
            result = {}
            if laser_max_temp_regs and len(laser_max_temp_regs) >= 1:
                result['laser_max_temp'] = float(int(laser_max_temp_regs[0])) / 100.0
            if laser_min_temp_regs and len(laser_min_temp_regs) >= 1:
                result['laser_min_temp'] = float(int(laser_min_temp_regs[0])) / 100.0
            if cell_max_temp_regs and len(cell_max_temp_regs) >= 1:
                result['cell_max_temp'] = float(int(cell_max_temp_regs[0])) / 100.0
            if cell_min_temp_regs and len(cell_min_temp_regs) >= 1:
                result['cell_min_temp'] = float(int(cell_min_temp_regs[0])) / 100.0
            if ramp_temp_regs and len(ramp_temp_regs) >= 1:
                result['ramp_temp'] = float(int(ramp_temp_regs[0])) / 100.0
            if seop_temp_regs and len(seop_temp_regs) >= 1:
                result['seop_temp'] = float(int(seop_temp_regs[0])) / 100.0
            if cell_refill_temp_regs and len(cell_refill_temp_regs) >= 1:
                result['cell_refill_temp'] = float(int(cell_refill_temp_regs[0])) / 100.0
            if loop_time_regs and len(loop_time_regs) >= 1:
                # SEOP loop time в секундах - значение уже в секундах
                result['loop_time'] = float(int(loop_time_regs[0]))
            if process_duration_regs and len(process_duration_regs) >= 1:
                # SEOP process duration в секундах - значение уже в секундах (отображается как m:s)
                result['process_duration'] = float(int(process_duration_regs[0]))
            if laser_max_output_power_regs and len(laser_max_output_power_regs) >= 1:
                # Laser Max Output Power в W - преобразуем из int (W * 100) в float
                result['laser_max_output_power'] = float(int(laser_max_output_power_regs[0])) / 100.0
            if laser_psu_max_current_regs and len(laser_psu_max_current_regs) >= 1:
                # Laser PSU MAX Current в A - преобразуем из int (A * 100) в float
                result['laser_psu_max_current'] = float(int(laser_psu_max_current_regs[0])) / 100.0
            if water_chiller_max_temp_regs and len(water_chiller_max_temp_regs) >= 1:
                # Water Chiller Max Temp в C - преобразуем из int (температура * 100) в float
                result['water_chiller_max_temp'] = float(int(water_chiller_max_temp_regs[0])) / 100.0
            if water_chiller_min_temp_regs and len(water_chiller_min_temp_regs) >= 1:
                # Water Chiller Min Temp в C - преобразуем из int (температура * 100) в float
                result['water_chiller_min_temp'] = float(int(water_chiller_min_temp_regs[0])) / 100.0
            if xe_concentration_regs and len(xe_concentration_regs) >= 1:
                # 129Xe concentration в mMol - значение уже в mMol, ничего умножать не надо
                result['xe_concentration'] = float(int(xe_concentration_regs[0]))
            if water_proton_concentration_regs and len(water_proton_concentration_regs) >= 1:
                # Water proton concentration в Mol - преобразуем из int (Mol * 100) в float
                result['water_proton_concentration'] = float(int(water_proton_concentration_regs[0])) / 100.0
            if cell_number_regs and len(cell_number_regs) >= 1:
                # Cell number - целое число
                result['cell_number'] = int(cell_number_regs[0])
            if refill_cycle_regs and len(refill_cycle_regs) >= 1:
                # Refill cycle - целое число
                result['refill_cycle'] = int(refill_cycle_regs[0])
            
            return result
        
        self._enqueue_read("seop_parameters", task)
    
    def _readCalculatedParameters(self):
        """Чтение регистров Calculated Parameters (4011-4101)"""
        if not self._is_connected or self._modbus_client is None or self._reading_calculated_parameters:
            return

        self._reading_calculated_parameters = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Calculated Parameters"""
            # Регистры 4011-4101
            electron_polarization_regs = client.read_input_registers_direct(4011, 1, max_chunk=1)
            xe_polarization_regs = client.read_input_registers_direct(4021, 1, max_chunk=1)
            buildup_rate_regs = client.read_input_registers_direct(4031, 1, max_chunk=1)
            electron_polarization_error_regs = client.read_input_registers_direct(4041, 1, max_chunk=1)
            xe_polarization_error_regs = client.read_input_registers_direct(4051, 1, max_chunk=1)
            buildup_rate_error_regs = client.read_input_registers_direct(4061, 1, max_chunk=1)
            fitted_xe_polarization_max_regs = client.read_input_registers_direct(4071, 1, max_chunk=1)
            fitted_xe_polarization_max_error_regs = client.read_input_registers_direct(4081, 1, max_chunk=1)
            hp_xe_t1_regs = client.read_input_registers_direct(4091, 1, max_chunk=1)
            hp_xe_t1_error_regs = client.read_input_registers_direct(4101, 1, max_chunk=1)
            
            result = {}
            if electron_polarization_regs and len(electron_polarization_regs) >= 1:
                # Electron Polarization (PRb %) - преобразуем из int (PRb * 100) в float
                result['electron_polarization'] = float(int(electron_polarization_regs[0])) / 100.0
            if xe_polarization_regs and len(xe_polarization_regs) >= 1:
                # 129Xe Polarization (PXe %) - преобразуем из int (PXe * 100) в float
                result['xe_polarization'] = float(int(xe_polarization_regs[0])) / 100.0
            if buildup_rate_regs and len(buildup_rate_regs) >= 1:
                # The buildup rate (g-SEOP 1/min) - преобразуем из int (g-SEOP * 100) в float
                result['buildup_rate'] = float(int(buildup_rate_regs[0])) / 100.0
            if electron_polarization_error_regs and len(electron_polarization_error_regs) >= 1:
                # Error bar for Electron Polarization (PRb-err %) - преобразуем из int (PRb-err * 100) в float
                result['electron_polarization_error'] = float(int(electron_polarization_error_regs[0])) / 100.0
            if xe_polarization_error_regs and len(xe_polarization_error_regs) >= 1:
                # Error bar for 129Xe Polarization (PXe err %) - преобразуем из int (PXe err * 100) в float
                result['xe_polarization_error'] = float(int(xe_polarization_error_regs[0])) / 100.0
            if buildup_rate_error_regs and len(buildup_rate_error_regs) >= 1:
                # Error bar for the buildup rate (g-SEOP err 1/min) - преобразуем из int (g-SEOP err * 100) в float
                result['buildup_rate_error'] = float(int(buildup_rate_error_regs[0])) / 100.0
            if fitted_xe_polarization_max_regs and len(fitted_xe_polarization_max_regs) >= 1:
                # Fitted 129Xe Polarization maximum (PXe max %) - преобразуем из int (PXe max * 100) в float
                result['fitted_xe_polarization_max'] = float(int(fitted_xe_polarization_max_regs[0])) / 100.0
            if fitted_xe_polarization_max_error_regs and len(fitted_xe_polarization_max_error_regs) >= 1:
                # Fitted 129Xe Polarization max error bar (PXe max err %) - преобразуем из int (PXe max err * 100) в float
                result['fitted_xe_polarization_max_error'] = float(int(fitted_xe_polarization_max_error_regs[0])) / 100.0
            if hp_xe_t1_regs and len(hp_xe_t1_regs) >= 1:
                # HP 129Xe T1 (T1 min) - преобразуем из int (T1 * 100) в float
                result['hp_xe_t1'] = float(int(hp_xe_t1_regs[0])) / 100.0
            if hp_xe_t1_error_regs and len(hp_xe_t1_error_regs) >= 1:
                # Error bar for 129Xe T1 (T1 err min) - преобразуем из int (T1 err * 100) в float
                result['hp_xe_t1_error'] = float(int(hp_xe_t1_error_regs[0])) / 100.0
            
            return result
        
        self._enqueue_read("calculated_parameters", task)
    
    def _applyCalculatedParametersValue(self, value: object):
        """Применение результатов чтения Calculated Parameters (4011-4101)"""
        self._reading_calculated_parameters = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyCalculatedParametersValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyCalculatedParametersValue: received value={value}")
        
        if 'electron_polarization' in value:
            val = float(value['electron_polarization'])
            self._calculated_electron_polarization = val
            self.calculatedElectronPolarizationChanged.emit(val)
            logger.debug(f"Calculated Electron Polarization: {val}%")
        if 'xe_polarization' in value:
            val = float(value['xe_polarization'])
            self._calculated_xe_polarization = val
            self.calculatedXePolarizationChanged.emit(val)
            logger.debug(f"Calculated 129Xe Polarization: {val}%")
        if 'buildup_rate' in value:
            val = float(value['buildup_rate'])
            self._calculated_buildup_rate = val
            self.calculatedBuildupRateChanged.emit(val)
            logger.debug(f"Calculated Buildup Rate: {val} 1/min")
        if 'electron_polarization_error' in value:
            val = float(value['electron_polarization_error'])
            self._calculated_electron_polarization_error = val
            self.calculatedElectronPolarizationErrorChanged.emit(val)
            logger.debug(f"Calculated Electron Polarization Error: {val}%")
        if 'xe_polarization_error' in value:
            val = float(value['xe_polarization_error'])
            self._calculated_xe_polarization_error = val
            self.calculatedXePolarizationErrorChanged.emit(val)
            logger.debug(f"Calculated 129Xe Polarization Error: {val}%")
        if 'buildup_rate_error' in value:
            val = float(value['buildup_rate_error'])
            self._calculated_buildup_rate_error = val
            self.calculatedBuildupRateErrorChanged.emit(val)
            logger.debug(f"Calculated Buildup Rate Error: {val} 1/min")
        if 'fitted_xe_polarization_max' in value:
            val = float(value['fitted_xe_polarization_max'])
            self._calculated_fitted_xe_polarization_max = val
            self.calculatedFittedXePolarizationMaxChanged.emit(val)
            logger.debug(f"Calculated Fitted 129Xe Polarization Max: {val}%")
        if 'fitted_xe_polarization_max_error' in value:
            val = float(value['fitted_xe_polarization_max_error'])
            self._calculated_fitted_xe_polarization_max_error = val
            self.calculatedFittedXePolarizationMaxErrorChanged.emit(val)
            logger.debug(f"Calculated Fitted 129Xe Polarization Max Error: {val}%")
        if 'hp_xe_t1' in value:
            val = float(value['hp_xe_t1'])
            self._calculated_hp_xe_t1 = val
            self.calculatedHPXeT1Changed.emit(val)
            logger.debug(f"Calculated HP 129Xe T1: {val} min")
        if 'hp_xe_t1_error' in value:
            val = float(value['hp_xe_t1_error'])
            self._calculated_hp_xe_t1_error = val
            self.calculatedHPXeT1ErrorChanged.emit(val)
            logger.debug(f"Calculated HP 129Xe T1 Error: {val} min")
    
    def _readMeasuredParameters(self):
        """Чтение регистров Measured Parameters (5011-5081)"""
        if not self._is_connected or self._modbus_client is None or self._reading_measured_parameters:
            return

        self._reading_measured_parameters = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Measured Parameters"""
            # Регистры идут с шагом 10 (5011, 5021, 5031...), поэтому читаем их по отдельности
            # Но используем max_chunk=10 для оптимизации внутри read_input_registers_direct
            current_ir_signal_regs = client.read_input_registers_direct(5011, 1, max_chunk=10)
            cold_cell_ir_signal_regs = client.read_input_registers_direct(5021, 1, max_chunk=10)
            hot_cell_ir_signal_regs = client.read_input_registers_direct(5031, 1, max_chunk=10)
            water_1h_nmr_reference_signal_regs = client.read_input_registers_direct(5041, 1, max_chunk=10)
            water_t2_regs = client.read_input_registers_direct(5051, 1, max_chunk=10)
            hp_129xe_nmr_signal_regs = client.read_input_registers_direct(5061, 1, max_chunk=10)
            hp_129xe_t2_regs = client.read_input_registers_direct(5071, 1, max_chunk=10)
            t2_correction_factor_regs = client.read_input_registers_direct(5081, 1, max_chunk=10)
            
            result = {}
            if current_ir_signal_regs and len(current_ir_signal_regs) >= 1:
                # Current IR Signal - значение уже в нужных единицах
                result['current_ir_signal'] = float(int(current_ir_signal_regs[0]))
            if cold_cell_ir_signal_regs and len(cold_cell_ir_signal_regs) >= 1:
                # Cold Cell IR Signal - значение уже в нужных единицах
                result['cold_cell_ir_signal'] = float(int(cold_cell_ir_signal_regs[0]))
            if hot_cell_ir_signal_regs and len(hot_cell_ir_signal_regs) >= 1:
                # Hot Cell IR Signal - значение уже в нужных единицах
                result['hot_cell_ir_signal'] = float(int(hot_cell_ir_signal_regs[0]))
            if water_1h_nmr_reference_signal_regs and len(water_1h_nmr_reference_signal_regs) >= 1:
                # Water 1H NMR Reference Signal - значение уже в нужных единицах
                result['water_1h_nmr_reference_signal'] = float(int(water_1h_nmr_reference_signal_regs[0]))
            if water_t2_regs and len(water_t2_regs) >= 1:
                # Water T2 в ms - преобразуем из int (ms * 100) в float
                result['water_t2'] = float(int(water_t2_regs[0])) / 100.0
            if hp_129xe_nmr_signal_regs and len(hp_129xe_nmr_signal_regs) >= 1:
                # HP 129Xe NMR Signal - значение уже в нужных единицах
                result['hp_129xe_nmr_signal'] = float(int(hp_129xe_nmr_signal_regs[0]))
            if hp_129xe_t2_regs and len(hp_129xe_t2_regs) >= 1:
                # HP 129Xe T2 в ms - преобразуем из int (ms * 100) в float
                result['hp_129xe_t2'] = float(int(hp_129xe_t2_regs[0])) / 100.0
            if t2_correction_factor_regs and len(t2_correction_factor_regs) >= 1:
                # T2* correction factor - значение уже в нужных единицах
                result['t2_correction_factor'] = float(int(t2_correction_factor_regs[0]))
            
            return result
        
        self._enqueue_read("measured_parameters", task)
    
    def _applyMeasuredParametersValue(self, value: object):
        """Применение результатов чтения Measured Parameters (5011-5081)"""
        self._reading_measured_parameters = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyMeasuredParametersValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyMeasuredParametersValue: received value={value}")
        
        if 'current_ir_signal' in value:
            val = float(value['current_ir_signal'])
            self._measured_current_ir_signal = val
            self.measuredCurrentIRSignalChanged.emit(val)
            logger.debug(f"Measured Current IR Signal: {val}")
        if 'cold_cell_ir_signal' in value:
            val = float(value['cold_cell_ir_signal'])
            if not self._measured_cold_cell_ir_signal_user_interaction:
                self._measured_cold_cell_ir_signal = val
                self.measuredColdCellIRSignalChanged.emit(val)
                logger.debug(f"Measured Cold Cell IR Signal: {val}")
        if 'hot_cell_ir_signal' in value:
            val = float(value['hot_cell_ir_signal'])
            if not self._measured_hot_cell_ir_signal_user_interaction:
                self._measured_hot_cell_ir_signal = val
                self.measuredHotCellIRSignalChanged.emit(val)
                logger.debug(f"Measured Hot Cell IR Signal: {val}")
        if 'water_1h_nmr_reference_signal' in value:
            val = float(value['water_1h_nmr_reference_signal'])
            if not self._measured_water_1h_nmr_reference_signal_user_interaction:
                self._measured_water_1h_nmr_reference_signal = val
                self.measuredWater1HNMRReferenceSignalChanged.emit(val)
                logger.debug(f"Measured Water 1H NMR Reference Signal: {val}")
        if 'water_t2' in value:
            val = float(value['water_t2'])
            if not self._measured_water_t2_user_interaction:
                self._measured_water_t2 = val
                self.measuredWaterT2Changed.emit(val)
                logger.debug(f"Measured Water T2: {val} ms")
        if 'hp_129xe_nmr_signal' in value:
            val = float(value['hp_129xe_nmr_signal'])
            self._measured_hp_129xe_nmr_signal = val
            self.measuredHP129XeNMRSignalChanged.emit(val)
            logger.debug(f"Measured HP 129Xe NMR Signal: {val}")
        if 'hp_129xe_t2' in value:
            val = float(value['hp_129xe_t2'])
            if not self._measured_hp_129xe_t2_user_interaction:
                self._measured_hp_129xe_t2 = val
                self.measuredHP129XeT2Changed.emit(val)
                logger.debug(f"Measured HP 129Xe T2: {val} ms")
        if 't2_correction_factor' in value:
            val = float(value['t2_correction_factor'])
            self._measured_t2_correction_factor = val
            self.measuredT2CorrectionFactorChanged.emit(val)
            logger.debug(f"Measured T2* correction factor: {val}")
    
    def _readAdditionalParameters(self):
        """Чтение регистров Additional Parameters (6011-6201)"""
        if not self._is_connected or self._modbus_client is None or self._reading_additional_parameters:
            return

        self._reading_additional_parameters = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Additional Parameters"""
            # Регистры идут с шагом 10 (6011, 6021, 6031...), поэтому читаем их по отдельности
            # Но используем max_chunk=10 для оптимизации внутри read_input_registers_direct
            magnet_psu_current_proton_nmr_regs = client.read_input_registers_direct(6011, 1, max_chunk=10)
            magnet_psu_current_129xe_nmr_regs = client.read_input_registers_direct(6021, 1, max_chunk=10)
            operational_laser_psu_current_regs = client.read_input_registers_direct(6031, 1, max_chunk=10)
            rf_pulse_duration_regs = client.read_input_registers_direct(6041, 1, max_chunk=10)
            resonance_frequency_regs = client.read_input_registers_direct(6051, 1, max_chunk=10)
            proton_rf_pulse_power_regs = client.read_input_registers_direct(6061, 1, max_chunk=10)
            hp_129xe_rf_pulse_power_regs = client.read_input_registers_direct(6071, 1, max_chunk=10)
            step_size_b0_sweep_hp_129xe_regs = client.read_input_registers_direct(6081, 1, max_chunk=10)
            step_size_b0_sweep_protons_regs = client.read_input_registers_direct(6091, 1, max_chunk=10)
            xe_alicats_pressure_regs = client.read_input_registers_direct(6101, 1, max_chunk=10)
            nitrogen_alicats_pressure_regs = client.read_input_registers_direct(6111, 1, max_chunk=10)
            chiller_temp_setpoint_regs = client.read_input_registers_direct(6121, 1, max_chunk=10)
            seop_resonance_frequency_regs = client.read_input_registers_direct(6131, 1, max_chunk=10)
            seop_resonance_frequency_tolerance_regs = client.read_input_registers_direct(6141, 1, max_chunk=10)
            ir_spectrometer_number_of_scans_regs = client.read_input_registers_direct(6151, 1, max_chunk=10)
            ir_spectrometer_exposure_duration_regs = client.read_input_registers_direct(6161, 1, max_chunk=10)
            h1_reference_n_scans_regs = client.read_input_registers_direct(6171, 1, max_chunk=10)
            h1_current_sweep_n_scans_regs = client.read_input_registers_direct(6181, 1, max_chunk=10)
            baseline_correction_min_frequency_regs = client.read_input_registers_direct(6191, 1, max_chunk=10)
            baseline_correction_max_frequency_regs = client.read_input_registers_direct(6201, 1, max_chunk=10)
            
            result = {}
            if magnet_psu_current_proton_nmr_regs and len(magnet_psu_current_proton_nmr_regs) >= 1:
                # Magnet PSU current for proton NMR в A - преобразуем из int (A * 100) в float
                result['magnet_psu_current_proton_nmr'] = float(int(magnet_psu_current_proton_nmr_regs[0])) / 100.0
            if magnet_psu_current_129xe_nmr_regs and len(magnet_psu_current_129xe_nmr_regs) >= 1:
                # Magnet PSU current for 129Xe NMR в A - преобразуем из int (A * 100) в float
                result['magnet_psu_current_129xe_nmr'] = float(int(magnet_psu_current_129xe_nmr_regs[0])) / 100.0
            if operational_laser_psu_current_regs and len(operational_laser_psu_current_regs) >= 1:
                # Operational Laser PSU current в A - преобразуем из int (A * 100) в float
                result['operational_laser_psu_current'] = float(int(operational_laser_psu_current_regs[0])) / 100.0
            if rf_pulse_duration_regs and len(rf_pulse_duration_regs) >= 1:
                # RF pulse duration - значение уже в нужных единицах
                result['rf_pulse_duration'] = float(int(rf_pulse_duration_regs[0]))
            if resonance_frequency_regs and len(resonance_frequency_regs) >= 1:
                # Resonance frequency в kHz - преобразуем из int (kHz * 100) в float
                result['resonance_frequency'] = float(int(resonance_frequency_regs[0])) / 100.0
            if proton_rf_pulse_power_regs and len(proton_rf_pulse_power_regs) >= 1:
                # Proton RF pulse power в % - преобразуем из int (% * 100) в float
                result['proton_rf_pulse_power'] = float(int(proton_rf_pulse_power_regs[0])) / 100.0
            if hp_129xe_rf_pulse_power_regs and len(hp_129xe_rf_pulse_power_regs) >= 1:
                # HP 129Xe RF pulse power в % - преобразуем из int (% * 100) в float
                result['hp_129xe_rf_pulse_power'] = float(int(hp_129xe_rf_pulse_power_regs[0])) / 100.0
            if step_size_b0_sweep_hp_129xe_regs and len(step_size_b0_sweep_hp_129xe_regs) >= 1:
                # Step size during B0 field sweep for HP 129Xe в A - преобразуем из int (A * 100) в float
                result['step_size_b0_sweep_hp_129xe'] = float(int(step_size_b0_sweep_hp_129xe_regs[0])) / 100.0
            if step_size_b0_sweep_protons_regs and len(step_size_b0_sweep_protons_regs) >= 1:
                # Step size during B0 field sweep for protons в A - преобразуем из int (A * 100) в float
                result['step_size_b0_sweep_protons'] = float(int(step_size_b0_sweep_protons_regs[0])) / 100.0
            if xe_alicats_pressure_regs and len(xe_alicats_pressure_regs) >= 1:
                # Xe ALICATS pressure в Torr - преобразуем из int (Torr * 100) в float
                result['xe_alicats_pressure'] = float(int(xe_alicats_pressure_regs[0])) / 100.0
            if nitrogen_alicats_pressure_regs and len(nitrogen_alicats_pressure_regs) >= 1:
                # Nitrogen ALICATS pressure в Torr - преобразуем из int (Torr * 100) в float
                result['nitrogen_alicats_pressure'] = float(int(nitrogen_alicats_pressure_regs[0])) / 100.0
            if chiller_temp_setpoint_regs and len(chiller_temp_setpoint_regs) >= 1:
                # Chiller Temp setpoint - значение уже в нужных единицах (предполагаем что это int)
                result['chiller_temp_setpoint'] = float(int(chiller_temp_setpoint_regs[0]))
            if seop_resonance_frequency_regs and len(seop_resonance_frequency_regs) >= 1:
                # SEOP Resonance Frequency в nm - преобразуем из int (nm * 100) в float
                result['seop_resonance_frequency'] = float(int(seop_resonance_frequency_regs[0])) / 100.0
            if seop_resonance_frequency_tolerance_regs and len(seop_resonance_frequency_tolerance_regs) >= 1:
                # SEOP Resonance Frequency Tolerance - значение уже в нужных единицах (предполагаем что это int)
                result['seop_resonance_frequency_tolerance'] = float(int(seop_resonance_frequency_tolerance_regs[0]))
            if ir_spectrometer_number_of_scans_regs and len(ir_spectrometer_number_of_scans_regs) >= 1:
                # IR spectrometer number of scans - значение уже в нужных единицах (предполагаем что это int)
                result['ir_spectrometer_number_of_scans'] = float(int(ir_spectrometer_number_of_scans_regs[0]))
            if ir_spectrometer_exposure_duration_regs and len(ir_spectrometer_exposure_duration_regs) >= 1:
                # IR spectrometer exposure duration в ms - преобразуем из int (ms * 100) в float
                result['ir_spectrometer_exposure_duration'] = float(int(ir_spectrometer_exposure_duration_regs[0])) / 100.0
            if h1_reference_n_scans_regs and len(h1_reference_n_scans_regs) >= 1:
                # 1H Reference N Scans - значение уже в нужных единицах (предполагаем что это int)
                result['h1_reference_n_scans'] = float(int(h1_reference_n_scans_regs[0]))
            if h1_current_sweep_n_scans_regs and len(h1_current_sweep_n_scans_regs) >= 1:
                # 1H Current Sweep N Scans - значение уже в нужных единицах (предполагаем что это int)
                result['h1_current_sweep_n_scans'] = float(int(h1_current_sweep_n_scans_regs[0]))
            if baseline_correction_min_frequency_regs and len(baseline_correction_min_frequency_regs) >= 1:
                # Baseline correction min frequency в kHz - преобразуем из int (kHz * 100) в float
                result['baseline_correction_min_frequency'] = float(int(baseline_correction_min_frequency_regs[0])) / 100.0
            if baseline_correction_max_frequency_regs and len(baseline_correction_max_frequency_regs) >= 1:
                # Baseline correction max frequency в kHz - преобразуем из int (kHz * 100) в float
                result['baseline_correction_max_frequency'] = float(int(baseline_correction_max_frequency_regs[0])) / 100.0
            
            return result
        
        self._enqueue_read("additional_parameters", task)
    
    def _applyAdditionalParametersValue(self, value: object):
        """Применение результатов чтения Additional Parameters (6011-6201)"""
        self._reading_additional_parameters = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyAdditionalParametersValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyAdditionalParametersValue: received value={value}")
        
        if 'magnet_psu_current_proton_nmr' in value:
            val = float(value['magnet_psu_current_proton_nmr'])
            if not self._additional_magnet_psu_current_proton_nmr_user_interaction:
                self._additional_magnet_psu_current_proton_nmr = val
                self.additionalMagnetPSUCurrentProtonNMRChanged.emit(val)
                logger.debug(f"Additional Magnet PSU current for proton NMR: {val} A")
        if 'magnet_psu_current_129xe_nmr' in value:
            val = float(value['magnet_psu_current_129xe_nmr'])
            if not self._additional_magnet_psu_current_129xe_nmr_user_interaction:
                self._additional_magnet_psu_current_129xe_nmr = val
                self.additionalMagnetPSUCurrent129XeNMRChanged.emit(val)
                logger.debug(f"Additional Magnet PSU current for 129Xe NMR: {val} A")
        if 'operational_laser_psu_current' in value:
            val = float(value['operational_laser_psu_current'])
            if not self._additional_operational_laser_psu_current_user_interaction:
                self._additional_operational_laser_psu_current = val
                self.additionalOperationalLaserPSUCurrentChanged.emit(val)
                logger.debug(f"Additional Operational Laser PSU current: {val} A")
        if 'rf_pulse_duration' in value:
            val = float(value['rf_pulse_duration'])
            if not self._additional_rf_pulse_duration_user_interaction:
                self._additional_rf_pulse_duration = val
                self.additionalRFPulseDurationChanged.emit(val)
                logger.debug(f"Additional RF pulse duration: {val}")
        if 'resonance_frequency' in value:
            val = float(value['resonance_frequency'])
            if not self._additional_resonance_frequency_user_interaction:
                self._additional_resonance_frequency = val
                self.additionalResonanceFrequencyChanged.emit(val)
                logger.debug(f"Additional Resonance frequency: {val} kHz")
        if 'proton_rf_pulse_power' in value:
            val = float(value['proton_rf_pulse_power'])
            if not self._additional_proton_rf_pulse_power_user_interaction:
                self._additional_proton_rf_pulse_power = val
                self.additionalProtonRFPulsePowerChanged.emit(val)
                logger.debug(f"Additional Proton RF pulse power: {val}%")
        if 'hp_129xe_rf_pulse_power' in value:
            val = float(value['hp_129xe_rf_pulse_power'])
            if not self._additional_hp_129xe_rf_pulse_power_user_interaction:
                self._additional_hp_129xe_rf_pulse_power = val
                self.additionalHP129XeRFPulsePowerChanged.emit(val)
                logger.debug(f"Additional HP 129Xe RF pulse power: {val}%")
        if 'step_size_b0_sweep_hp_129xe' in value:
            val = float(value['step_size_b0_sweep_hp_129xe'])
            if not self._additional_step_size_b0_sweep_hp_129xe_user_interaction:
                self._additional_step_size_b0_sweep_hp_129xe = val
                self.additionalStepSizeB0SweepHP129XeChanged.emit(val)
                logger.debug(f"Additional Step size during B0 field sweep for HP 129Xe: {val} A")
        if 'step_size_b0_sweep_protons' in value:
            val = float(value['step_size_b0_sweep_protons'])
            if not self._additional_step_size_b0_sweep_protons_user_interaction:
                self._additional_step_size_b0_sweep_protons = val
                self.additionalStepSizeB0SweepProtonsChanged.emit(val)
                logger.debug(f"Additional Step size during B0 field sweep for protons: {val} A")
        if 'xe_alicats_pressure' in value:
            val = float(value['xe_alicats_pressure'])
            if not self._additional_xe_alicats_pressure_user_interaction:
                self._additional_xe_alicats_pressure = val
                self.additionalXeAlicatsPressureChanged.emit(val)
                logger.debug(f"Additional Xe ALICATS pressure: {val} Torr")
        if 'nitrogen_alicats_pressure' in value:
            val = float(value['nitrogen_alicats_pressure'])
            if not self._additional_nitrogen_alicats_pressure_user_interaction:
                self._additional_nitrogen_alicats_pressure = val
                self.additionalNitrogenAlicatsPressureChanged.emit(val)
                logger.debug(f"Additional Nitrogen ALICATS pressure: {val} Torr")
        if 'chiller_temp_setpoint' in value:
            val = float(value['chiller_temp_setpoint'])
            if not self._additional_chiller_temp_setpoint_user_interaction:
                self._additional_chiller_temp_setpoint = val
                self.additionalChillerTempSetpointChanged.emit(val)
                logger.debug(f"Additional Chiller Temp setpoint: {val}")
        if 'seop_resonance_frequency' in value:
            val = float(value['seop_resonance_frequency'])
            if not self._additional_seop_resonance_frequency_user_interaction:
                self._additional_seop_resonance_frequency = val
                self.additionalSEOPResonanceFrequencyChanged.emit(val)
                logger.debug(f"Additional SEOP Resonance Frequency: {val} nm")
        if 'seop_resonance_frequency_tolerance' in value:
            val = float(value['seop_resonance_frequency_tolerance'])
            if not self._additional_seop_resonance_frequency_tolerance_user_interaction:
                self._additional_seop_resonance_frequency_tolerance = val
                self.additionalSEOPResonanceFrequencyToleranceChanged.emit(val)
                logger.debug(f"Additional SEOP Resonance Frequency Tolerance: {val}")
        if 'ir_spectrometer_number_of_scans' in value:
            val = float(value['ir_spectrometer_number_of_scans'])
            if not self._additional_ir_spectrometer_number_of_scans_user_interaction:
                self._additional_ir_spectrometer_number_of_scans = val
                self.additionalIRSpectrometerNumberOfScansChanged.emit(val)
                logger.debug(f"Additional IR spectrometer number of scans: {val}")
        if 'ir_spectrometer_exposure_duration' in value:
            val = float(value['ir_spectrometer_exposure_duration'])
            if not self._additional_ir_spectrometer_exposure_duration_user_interaction:
                self._additional_ir_spectrometer_exposure_duration = val
                self.additionalIRSpectrometerExposureDurationChanged.emit(val)
                logger.debug(f"Additional IR spectrometer exposure duration: {val} ms")
        if 'h1_reference_n_scans' in value:
            val = float(value['h1_reference_n_scans'])
            if not self._additional_1h_reference_n_scans_user_interaction:
                self._additional_1h_reference_n_scans = val
                self.additional1HReferenceNScansChanged.emit(val)
                logger.debug(f"Additional 1H Reference N Scans: {val}")
        if 'h1_current_sweep_n_scans' in value:
            val = float(value['h1_current_sweep_n_scans'])
            if not self._additional_1h_current_sweep_n_scans_user_interaction:
                self._additional_1h_current_sweep_n_scans = val
                self.additional1HCurrentSweepNScansChanged.emit(val)
                logger.debug(f"Additional 1H Current Sweep N Scans: {val}")
        if 'baseline_correction_min_frequency' in value:
            val = float(value['baseline_correction_min_frequency'])
            if not self._additional_baseline_correction_min_frequency_user_interaction:
                self._additional_baseline_correction_min_frequency = val
                self.additionalBaselineCorrectionMinFrequencyChanged.emit(val)
                logger.debug(f"Additional Baseline correction min frequency: {val} kHz")
        if 'baseline_correction_max_frequency' in value:
            val = float(value['baseline_correction_max_frequency'])
            if not self._additional_baseline_correction_max_frequency_user_interaction:
                self._additional_baseline_correction_max_frequency = val
                self.additionalBaselineCorrectionMaxFrequencyChanged.emit(val)
                logger.debug(f"Additional Baseline correction max frequency: {val} kHz")
    
    def _readManualModeSettings(self):
        """Чтение регистров Manual mode settings (6301-6381)"""
        if not self._is_connected or self._modbus_client is None or self._reading_manual_mode_settings:
            return

        self._reading_manual_mode_settings = True
        client = self._modbus_client
        
        def task():
            """Чтение всех регистров Manual mode settings"""
            # Регистры 6301-6381
            rf_pulse_frequency_regs = client.read_input_registers_direct(6301, 1, max_chunk=1)
            rf_pulse_power_regs = client.read_input_registers_direct(6311, 1, max_chunk=1)
            rf_pulse_duration_regs = client.read_input_registers_direct(6321, 1, max_chunk=1)
            pre_acquisition_regs = client.read_input_registers_direct(6331, 1, max_chunk=1)
            nmr_gain_regs = client.read_input_registers_direct(6341, 1, max_chunk=1)
            nmr_number_of_scans_regs = client.read_input_registers_direct(6351, 1, max_chunk=1)
            nmr_recovery_regs = client.read_input_registers_direct(6361, 1, max_chunk=1)
            center_frequency_regs = client.read_input_registers_direct(6371, 1, max_chunk=1)
            frequency_span_regs = client.read_input_registers_direct(6381, 1, max_chunk=1)
            
            result = {}
            if rf_pulse_frequency_regs and len(rf_pulse_frequency_regs) >= 1:
                # RF pulse frequency в kHz - преобразуем из int (kHz * 100) в float
                result['rf_pulse_frequency'] = float(int(rf_pulse_frequency_regs[0])) / 100.0
            if rf_pulse_power_regs and len(rf_pulse_power_regs) >= 1:
                # RF pulse power в % - преобразуем из int (% * 100) в float
                result['rf_pulse_power'] = float(int(rf_pulse_power_regs[0])) / 100.0
            if rf_pulse_duration_regs and len(rf_pulse_duration_regs) >= 1:
                # RF pulse duration в T/2 - преобразуем из int (T/2 * 100) в float
                result['rf_pulse_duration'] = float(int(rf_pulse_duration_regs[0])) / 100.0
            if pre_acquisition_regs and len(pre_acquisition_regs) >= 1:
                # Pre acquisition в ms - преобразуем из int (ms * 100) в float
                result['pre_acquisition'] = float(int(pre_acquisition_regs[0])) / 100.0
            if nmr_gain_regs and len(nmr_gain_regs) >= 1:
                # NMR gain в dB - преобразуем из int (dB * 100) в float
                result['nmr_gain'] = float(int(nmr_gain_regs[0])) / 100.0
            if nmr_number_of_scans_regs and len(nmr_number_of_scans_regs) >= 1:
                # NMR number of scans - значение уже в нужных единицах (предполагаем что это int)
                result['nmr_number_of_scans'] = float(int(nmr_number_of_scans_regs[0]))
            if nmr_recovery_regs and len(nmr_recovery_regs) >= 1:
                # NMR recovery в ms - преобразуем из int (ms * 100) в float
                result['nmr_recovery'] = float(int(nmr_recovery_regs[0])) / 100.0
            if center_frequency_regs and len(center_frequency_regs) >= 1:
                # Center frequency в kHz - преобразуем из int (kHz * 100) в float
                result['center_frequency'] = float(int(center_frequency_regs[0])) / 100.0
            if frequency_span_regs and len(frequency_span_regs) >= 1:
                # Frequency span в kHz - преобразуем из int (kHz * 100) в float
                result['frequency_span'] = float(int(frequency_span_regs[0])) / 100.0
            
            return result
        
        self._enqueue_read("manual_mode_settings", task)
    
    def _applyManualModeSettingsValue(self, value: object):
        """Применение результатов чтения Manual mode settings (6301-6381)"""
        self._reading_manual_mode_settings = False
        if value is None or not isinstance(value, dict):
            logger.warning(f"_applyManualModeSettingsValue: value is None or not dict: {value}")
            return
        
        logger.debug(f"_applyManualModeSettingsValue: received value={value}")
        
        if 'rf_pulse_frequency' in value:
            val = float(value['rf_pulse_frequency'])
            if not self._manual_mode_rf_pulse_frequency_user_interaction:
                self._manual_mode_rf_pulse_frequency = val
                self.manualModeRFPulseFrequencyChanged.emit(val)
                logger.debug(f"Manual mode RF pulse frequency: {val} kHz")
        if 'rf_pulse_power' in value:
            val = float(value['rf_pulse_power'])
            if not self._manual_mode_rf_pulse_power_user_interaction:
                self._manual_mode_rf_pulse_power = val
                self.manualModeRFPulsePowerChanged.emit(val)
                logger.debug(f"Manual mode RF pulse power: {val}%")
        if 'rf_pulse_duration' in value:
            val = float(value['rf_pulse_duration'])
            if not self._manual_mode_rf_pulse_duration_user_interaction:
                self._manual_mode_rf_pulse_duration = val
                self.manualModeRFPulseDurationChanged.emit(val)
                logger.debug(f"Manual mode RF pulse duration: {val} T/2")
        if 'pre_acquisition' in value:
            val = float(value['pre_acquisition'])
            if not self._manual_mode_pre_acquisition_user_interaction:
                self._manual_mode_pre_acquisition = val
                self.manualModePreAcquisitionChanged.emit(val)
                logger.debug(f"Manual mode Pre acquisition: {val} ms")
        if 'nmr_gain' in value:
            val = float(value['nmr_gain'])
            if not self._manual_mode_nmr_gain_user_interaction:
                self._manual_mode_nmr_gain = val
                self.manualModeNMRGainChanged.emit(val)
                logger.debug(f"Manual mode NMR gain: {val} dB")
        if 'nmr_number_of_scans' in value:
            val = float(value['nmr_number_of_scans'])
            if not self._manual_mode_nmr_number_of_scans_user_interaction:
                self._manual_mode_nmr_number_of_scans = val
                self.manualModeNMRNumberOfScansChanged.emit(val)
                logger.debug(f"Manual mode NMR number of scans: {val}")
        if 'nmr_recovery' in value:
            val = float(value['nmr_recovery'])
            if not self._manual_mode_nmr_recovery_user_interaction:
                self._manual_mode_nmr_recovery = val
                self.manualModeNMRRecoveryChanged.emit(val)
                logger.debug(f"Manual mode NMR recovery: {val} ms")
        if 'center_frequency' in value:
            val = float(value['center_frequency'])
            if not self._manual_mode_center_frequency_user_interaction:
                self._manual_mode_center_frequency = val
                self.manualModeCenterFrequencyChanged.emit(val)
                logger.debug(f"Manual mode Center frequency: {val} kHz")
        if 'frequency_span' in value:
            val = float(value['frequency_span'])
            if not self._manual_mode_frequency_span_user_interaction:
                self._manual_mode_frequency_span = val
                self.manualModeFrequencySpanChanged.emit(val)
                logger.debug(f"Manual mode Frequency span: {val} kHz")
    
    # ===== Measured Parameters методы записи =====
    @Slot(float, result=bool)
    def setMeasuredColdCellIRSignal(self, value: float) -> bool:
        """Установка Cold Cell IR Signal (регистр 5021)"""
        # Логируем действие
        self._addLog(f"Cold Cell IR Signal: {value}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._measured_cold_cell_ir_signal = value
        self._measured_cold_cell_ir_signal_user_interaction = True
        self.measuredColdCellIRSignalChanged.emit(value)
        register_value = int(value)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(5021, register_value)
            return bool(result)
        self._enqueue_write("measured_cold_cell_ir_signal", task, {"value": value})
        return True
    
    @Slot(result=bool)
    def increaseMeasuredColdCellIRSignal(self) -> bool:
        """Увеличение Cold Cell IR Signal на 1"""
        return self.setMeasuredColdCellIRSignal(self._measured_cold_cell_ir_signal + 1.0)
    
    @Slot(result=bool)
    def decreaseMeasuredColdCellIRSignal(self) -> bool:
        """Уменьшение Cold Cell IR Signal на 1"""
        return self.setMeasuredColdCellIRSignal(self._measured_cold_cell_ir_signal - 1.0)
    
    @Slot(float, result=bool)
    def setMeasuredHotCellIRSignal(self, value: float) -> bool:
        """Установка Hot Cell IR Signal (регистр 5031)"""
        # Логируем действие
        self._addLog(f"Hot Cell IR Signal: {value}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._measured_hot_cell_ir_signal = value
        self._measured_hot_cell_ir_signal_user_interaction = True
        self.measuredHotCellIRSignalChanged.emit(value)
        register_value = int(value)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(5031, register_value)
            return bool(result)
        self._enqueue_write("measured_hot_cell_ir_signal", task, {"value": value})
        return True
    
    @Slot(result=bool)
    def increaseMeasuredHotCellIRSignal(self) -> bool:
        """Увеличение Hot Cell IR Signal на 1"""
        return self.setMeasuredHotCellIRSignal(self._measured_hot_cell_ir_signal + 1.0)
    
    @Slot(result=bool)
    def decreaseMeasuredHotCellIRSignal(self) -> bool:
        """Уменьшение Hot Cell IR Signal на 1"""
        return self.setMeasuredHotCellIRSignal(self._measured_hot_cell_ir_signal - 1.0)
    
    @Slot(float, result=bool)
    def setMeasuredWater1HNMRReferenceSignal(self, value: float) -> bool:
        """Установка Water 1H NMR Reference Signal (регистр 5041)"""
        # Логируем действие
        self._addLog(f"Water 1H NMR Reference Signal: {value}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._measured_water_1h_nmr_reference_signal = value
        self._measured_water_1h_nmr_reference_signal_user_interaction = True
        self.measuredWater1HNMRReferenceSignalChanged.emit(value)
        register_value = int(value)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(5041, register_value)
            return bool(result)
        self._enqueue_write("measured_water_1h_nmr_reference_signal", task, {"value": value})
        return True
    
    @Slot(result=bool)
    def increaseMeasuredWater1HNMRReferenceSignal(self) -> bool:
        """Увеличение Water 1H NMR Reference Signal на 1"""
        return self.setMeasuredWater1HNMRReferenceSignal(self._measured_water_1h_nmr_reference_signal + 1.0)
    
    @Slot(result=bool)
    def decreaseMeasuredWater1HNMRReferenceSignal(self) -> bool:
        """Уменьшение Water 1H NMR Reference Signal на 1"""
        return self.setMeasuredWater1HNMRReferenceSignal(self._measured_water_1h_nmr_reference_signal - 1.0)
    
    @Slot(float, result=bool)
    def setMeasuredWaterT2(self, value_ms: float) -> bool:
        """Установка Water T2 в ms (регистр 5051)"""
        # Логируем действие
        self._addLog(f"Water T2: {value_ms} ms")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._measured_water_t2 = value_ms
        self._measured_water_t2_user_interaction = True
        self.measuredWaterT2Changed.emit(value_ms)
        register_value = int(value_ms * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(5051, register_value)
            return bool(result)
        self._enqueue_write("measured_water_t2", task, {"value_ms": value_ms})
        return True
    
    @Slot(result=bool)
    def increaseMeasuredWaterT2(self) -> bool:
        """Увеличение Water T2 на 0.01 ms"""
        return self.setMeasuredWaterT2(self._measured_water_t2 + 0.01)
    
    @Slot(result=bool)
    def decreaseMeasuredWaterT2(self) -> bool:
        """Уменьшение Water T2 на 0.01 ms"""
        return self.setMeasuredWaterT2(self._measured_water_t2 - 0.01)
    
    @Slot(float, result=bool)
    def setMeasuredHP129XeT2(self, value_ms: float) -> bool:
        """Установка HP 129Xe T2 в ms (регистр 5071)"""
        # Логируем действие
        self._addLog(f"HP 129Xe T2: {value_ms} ms")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._measured_hp_129xe_t2 = value_ms
        self._measured_hp_129xe_t2_user_interaction = True
        self.measuredHP129XeT2Changed.emit(value_ms)
        register_value = int(value_ms * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(5071, register_value)
            return bool(result)
        self._enqueue_write("measured_hp_129xe_t2", task, {"value_ms": value_ms})
        return True
    
    @Slot(result=bool)
    def increaseMeasuredHP129XeT2(self) -> bool:
        """Увеличение HP 129Xe T2 на 0.01 ms"""
        return self.setMeasuredHP129XeT2(self._measured_hp_129xe_t2 + 0.01)
    
    @Slot(result=bool)
    def decreaseMeasuredHP129XeT2(self) -> bool:
        """Уменьшение HP 129Xe T2 на 0.01 ms"""
        return self.setMeasuredHP129XeT2(self._measured_hp_129xe_t2 - 0.01)
    
    # Методы setValue для TextField (ввод с клавиатуры)
    @Slot(float, result=bool)
    def setMeasuredColdCellIRSignalValue(self, value: float) -> bool:
        """Обновление внутреннего значения Cold Cell IR Signal без отправки на устройство"""
        self._measured_cold_cell_ir_signal = value
        self.measuredColdCellIRSignalChanged.emit(value)
        self._measured_cold_cell_ir_signal_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setMeasuredHotCellIRSignalValue(self, value: float) -> bool:
        """Обновление внутреннего значения Hot Cell IR Signal без отправки на устройство"""
        self._measured_hot_cell_ir_signal = value
        self.measuredHotCellIRSignalChanged.emit(value)
        self._measured_hot_cell_ir_signal_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setMeasuredWater1HNMRReferenceSignalValue(self, value: float) -> bool:
        """Обновление внутреннего значения Water 1H NMR Reference Signal без отправки на устройство"""
        self._measured_water_1h_nmr_reference_signal = value
        self.measuredWater1HNMRReferenceSignalChanged.emit(value)
        self._measured_water_1h_nmr_reference_signal_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setMeasuredWaterT2Value(self, value_ms: float) -> bool:
        """Обновление внутреннего значения Water T2 без отправки на устройство"""
        self._measured_water_t2 = value_ms
        self.measuredWaterT2Changed.emit(value_ms)
        self._measured_water_t2_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setMeasuredHP129XeT2Value(self, value_ms: float) -> bool:
        """Обновление внутреннего значения HP 129Xe T2 без отправки на устройство"""
        self._measured_hp_129xe_t2 = value_ms
        self.measuredHP129XeT2Changed.emit(value_ms)
        self._measured_hp_129xe_t2_user_interaction = True
        return True
    
    # ===== Additional Parameters методы записи =====
    @Slot(float, result=bool)
    def setAdditionalMagnetPSUCurrentProtonNMR(self, current_a: float) -> bool:
        """Установка Magnet PSU current for proton NMR в A (регистр 6011)"""
        # Логируем действие
        self._addLog(f"Magnet PSU Current Proton NMR: {current_a} A")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_magnet_psu_current_proton_nmr = current_a
        self._additional_magnet_psu_current_proton_nmr_user_interaction = True
        self.additionalMagnetPSUCurrentProtonNMRChanged.emit(current_a)
        register_value = int(current_a * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6011, register_value)
            return bool(result)
        self._enqueue_write("additional_magnet_psu_current_proton_nmr", task, {"current_a": current_a})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalMagnetPSUCurrentProtonNMR(self) -> bool:
        """Увеличение Magnet PSU current for proton NMR на 0.01 A"""
        return self.setAdditionalMagnetPSUCurrentProtonNMR(self._additional_magnet_psu_current_proton_nmr + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalMagnetPSUCurrentProtonNMR(self) -> bool:
        """Уменьшение Magnet PSU current for proton NMR на 0.01 A"""
        return self.setAdditionalMagnetPSUCurrentProtonNMR(self._additional_magnet_psu_current_proton_nmr - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalMagnetPSUCurrent129XeNMR(self, current_a: float) -> bool:
        """Установка Magnet PSU current for 129Xe NMR в A (регистр 6021)"""
        # Логируем действие
        self._addLog(f"Magnet PSU Current 129Xe NMR: {current_a} A")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_magnet_psu_current_129xe_nmr = current_a
        self._additional_magnet_psu_current_129xe_nmr_user_interaction = True
        self.additionalMagnetPSUCurrent129XeNMRChanged.emit(current_a)
        register_value = int(current_a * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6021, register_value)
            return bool(result)
        self._enqueue_write("additional_magnet_psu_current_129xe_nmr", task, {"current_a": current_a})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalMagnetPSUCurrent129XeNMR(self) -> bool:
        """Увеличение Magnet PSU current for 129Xe NMR на 0.01 A"""
        return self.setAdditionalMagnetPSUCurrent129XeNMR(self._additional_magnet_psu_current_129xe_nmr + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalMagnetPSUCurrent129XeNMR(self) -> bool:
        """Уменьшение Magnet PSU current for 129Xe NMR на 0.01 A"""
        return self.setAdditionalMagnetPSUCurrent129XeNMR(self._additional_magnet_psu_current_129xe_nmr - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalOperationalLaserPSUCurrent(self, current_a: float) -> bool:
        """Установка Operational Laser PSU current в A (регистр 6031)"""
        # Логируем действие
        self._addLog(f"Operational Laser PSU Current: {current_a} A")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_operational_laser_psu_current = current_a
        self._additional_operational_laser_psu_current_user_interaction = True
        self.additionalOperationalLaserPSUCurrentChanged.emit(current_a)
        register_value = int(current_a * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6031, register_value)
            return bool(result)
        self._enqueue_write("additional_operational_laser_psu_current", task, {"current_a": current_a})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalOperationalLaserPSUCurrent(self) -> bool:
        """Увеличение Operational Laser PSU current на 0.01 A"""
        return self.setAdditionalOperationalLaserPSUCurrent(self._additional_operational_laser_psu_current + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalOperationalLaserPSUCurrent(self) -> bool:
        """Уменьшение Operational Laser PSU current на 0.01 A"""
        return self.setAdditionalOperationalLaserPSUCurrent(self._additional_operational_laser_psu_current - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalRFPulseDuration(self, duration: float) -> bool:
        """Установка RF pulse duration (регистр 6041)"""
        # Логируем действие
        self._addLog(f"RF Pulse Duration: {duration}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_rf_pulse_duration = duration
        self._additional_rf_pulse_duration_user_interaction = True
        self.additionalRFPulseDurationChanged.emit(duration)
        register_value = int(duration)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6041, register_value)
            return bool(result)
        self._enqueue_write("additional_rf_pulse_duration", task, {"duration": duration})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalRFPulseDuration(self) -> bool:
        """Увеличение RF pulse duration на 1"""
        return self.setAdditionalRFPulseDuration(self._additional_rf_pulse_duration + 1.0)
    
    @Slot(result=bool)
    def decreaseAdditionalRFPulseDuration(self) -> bool:
        """Уменьшение RF pulse duration на 1"""
        return self.setAdditionalRFPulseDuration(self._additional_rf_pulse_duration - 1.0)
    
    @Slot(float, result=bool)
    def setAdditionalResonanceFrequency(self, frequency_khz: float) -> bool:
        """Установка Resonance frequency в kHz (регистр 6051)"""
        # Логируем действие
        self._addLog(f"Resonance Frequency: {frequency_khz} kHz")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_resonance_frequency = frequency_khz
        self._additional_resonance_frequency_user_interaction = True
        self.additionalResonanceFrequencyChanged.emit(frequency_khz)
        register_value = int(frequency_khz * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6051, register_value)
            return bool(result)
        self._enqueue_write("additional_resonance_frequency", task, {"frequency_khz": frequency_khz})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalResonanceFrequency(self) -> bool:
        """Увеличение Resonance frequency на 0.01 kHz"""
        return self.setAdditionalResonanceFrequency(self._additional_resonance_frequency + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalResonanceFrequency(self) -> bool:
        """Уменьшение Resonance frequency на 0.01 kHz"""
        return self.setAdditionalResonanceFrequency(self._additional_resonance_frequency - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalProtonRFPulsePower(self, power_percent: float) -> bool:
        """Установка Proton RF pulse power в % (регистр 6061)"""
        # Логируем действие
        self._addLog(f"Proton RF Pulse Power: {power_percent}%")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_proton_rf_pulse_power = power_percent
        self._additional_proton_rf_pulse_power_user_interaction = True
        self.additionalProtonRFPulsePowerChanged.emit(power_percent)
        register_value = int(power_percent * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6061, register_value)
            return bool(result)
        self._enqueue_write("additional_proton_rf_pulse_power", task, {"power_percent": power_percent})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalProtonRFPulsePower(self) -> bool:
        """Увеличение Proton RF pulse power на 0.01%"""
        return self.setAdditionalProtonRFPulsePower(self._additional_proton_rf_pulse_power + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalProtonRFPulsePower(self) -> bool:
        """Уменьшение Proton RF pulse power на 0.01%"""
        return self.setAdditionalProtonRFPulsePower(self._additional_proton_rf_pulse_power - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalHP129XeRFPulsePower(self, power_percent: float) -> bool:
        """Установка HP 129Xe RF pulse power в % (регистр 6071)"""
        # Логируем действие
        self._addLog(f"HP 129Xe RF Pulse Power: {power_percent}%")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_hp_129xe_rf_pulse_power = power_percent
        self._additional_hp_129xe_rf_pulse_power_user_interaction = True
        self.additionalHP129XeRFPulsePowerChanged.emit(power_percent)
        register_value = int(power_percent * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6071, register_value)
            return bool(result)
        self._enqueue_write("additional_hp_129xe_rf_pulse_power", task, {"power_percent": power_percent})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalHP129XeRFPulsePower(self) -> bool:
        """Увеличение HP 129Xe RF pulse power на 0.01%"""
        return self.setAdditionalHP129XeRFPulsePower(self._additional_hp_129xe_rf_pulse_power + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalHP129XeRFPulsePower(self) -> bool:
        """Уменьшение HP 129Xe RF pulse power на 0.01%"""
        return self.setAdditionalHP129XeRFPulsePower(self._additional_hp_129xe_rf_pulse_power - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalStepSizeB0SweepHP129Xe(self, step_size_a: float) -> bool:
        """Установка Step size during B0 field sweep for HP 129Xe в A (регистр 6081)"""
        # Логируем действие
        self._addLog(f"Step Size B0 Sweep HP 129Xe: {step_size_a} A")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_step_size_b0_sweep_hp_129xe = step_size_a
        self._additional_step_size_b0_sweep_hp_129xe_user_interaction = True
        self.additionalStepSizeB0SweepHP129XeChanged.emit(step_size_a)
        register_value = int(step_size_a * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6081, register_value)
            return bool(result)
        self._enqueue_write("additional_step_size_b0_sweep_hp_129xe", task, {"step_size_a": step_size_a})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalStepSizeB0SweepHP129Xe(self) -> bool:
        """Увеличение Step size during B0 field sweep for HP 129Xe на 0.01 A"""
        return self.setAdditionalStepSizeB0SweepHP129Xe(self._additional_step_size_b0_sweep_hp_129xe + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalStepSizeB0SweepHP129Xe(self) -> bool:
        """Уменьшение Step size during B0 field sweep for HP 129Xe на 0.01 A"""
        return self.setAdditionalStepSizeB0SweepHP129Xe(self._additional_step_size_b0_sweep_hp_129xe - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalStepSizeB0SweepProtons(self, step_size_a: float) -> bool:
        """Установка Step size during B0 field sweep for protons в A (регистр 6091)"""
        # Логируем действие
        self._addLog(f"Step Size B0 Sweep Protons: {step_size_a} A")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_step_size_b0_sweep_protons = step_size_a
        self._additional_step_size_b0_sweep_protons_user_interaction = True
        self.additionalStepSizeB0SweepProtonsChanged.emit(step_size_a)
        register_value = int(step_size_a * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6091, register_value)
            return bool(result)
        self._enqueue_write("additional_step_size_b0_sweep_protons", task, {"step_size_a": step_size_a})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalStepSizeB0SweepProtons(self) -> bool:
        """Увеличение Step size during B0 field sweep for protons на 0.01 A"""
        return self.setAdditionalStepSizeB0SweepProtons(self._additional_step_size_b0_sweep_protons + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalStepSizeB0SweepProtons(self) -> bool:
        """Уменьшение Step size during B0 field sweep for protons на 0.01 A"""
        return self.setAdditionalStepSizeB0SweepProtons(self._additional_step_size_b0_sweep_protons - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalXeAlicatsPressure(self, pressure_torr: float) -> bool:
        """Установка Xe ALICATS pressure в Torr (регистр 6101)"""
        # Логируем действие
        self._addLog(f"Xe ALICATS Pressure: {pressure_torr} Torr")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_xe_alicats_pressure = pressure_torr
        self._additional_xe_alicats_pressure_user_interaction = True
        self.additionalXeAlicatsPressureChanged.emit(pressure_torr)
        register_value = int(pressure_torr * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6101, register_value)
            return bool(result)
        self._enqueue_write("additional_xe_alicats_pressure", task, {"pressure_torr": pressure_torr})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalXeAlicatsPressure(self) -> bool:
        """Увеличение Xe ALICATS pressure на 0.01 Torr"""
        return self.setAdditionalXeAlicatsPressure(self._additional_xe_alicats_pressure + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalXeAlicatsPressure(self) -> bool:
        """Уменьшение Xe ALICATS pressure на 0.01 Torr"""
        return self.setAdditionalXeAlicatsPressure(self._additional_xe_alicats_pressure - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalNitrogenAlicatsPressure(self, pressure_torr: float) -> bool:
        """Установка Nitrogen ALICATS pressure в Torr (регистр 6111)"""
        # Логируем действие
        self._addLog(f"Nitrogen ALICATS Pressure: {pressure_torr} Torr")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_nitrogen_alicats_pressure = pressure_torr
        self._additional_nitrogen_alicats_pressure_user_interaction = True
        self.additionalNitrogenAlicatsPressureChanged.emit(pressure_torr)
        register_value = int(pressure_torr * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6111, register_value)
            return bool(result)
        self._enqueue_write("additional_nitrogen_alicats_pressure", task, {"pressure_torr": pressure_torr})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalNitrogenAlicatsPressure(self) -> bool:
        """Увеличение Nitrogen ALICATS pressure на 0.01 Torr"""
        return self.setAdditionalNitrogenAlicatsPressure(self._additional_nitrogen_alicats_pressure + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalNitrogenAlicatsPressure(self) -> bool:
        """Уменьшение Nitrogen ALICATS pressure на 0.01 Torr"""
        return self.setAdditionalNitrogenAlicatsPressure(self._additional_nitrogen_alicats_pressure - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalChillerTempSetpoint(self, setpoint: float) -> bool:
        """Установка Chiller Temp setpoint (регистр 6121)"""
        # Логируем действие
        self._addLog(f"Chiller Temp Setpoint: {setpoint}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_chiller_temp_setpoint = setpoint
        self._additional_chiller_temp_setpoint_user_interaction = True
        self.additionalChillerTempSetpointChanged.emit(setpoint)
        register_value = int(setpoint)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6121, register_value)
            return bool(result)
        self._enqueue_write("additional_chiller_temp_setpoint", task, {"setpoint": setpoint})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalChillerTempSetpoint(self) -> bool:
        """Увеличение Chiller Temp setpoint на 1"""
        return self.setAdditionalChillerTempSetpoint(self._additional_chiller_temp_setpoint + 1.0)
    
    @Slot(result=bool)
    def decreaseAdditionalChillerTempSetpoint(self) -> bool:
        """Уменьшение Chiller Temp setpoint на 1"""
        return self.setAdditionalChillerTempSetpoint(self._additional_chiller_temp_setpoint - 1.0)
    
    @Slot(float, result=bool)
    def setAdditionalSEOPResonanceFrequency(self, frequency_nm: float) -> bool:
        """Установка SEOP Resonance Frequency в nm (регистр 6131)"""
        # Логируем действие
        self._addLog(f"SEOP Resonance Frequency: {frequency_nm} nm")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_seop_resonance_frequency = frequency_nm
        self._additional_seop_resonance_frequency_user_interaction = True
        self.additionalSEOPResonanceFrequencyChanged.emit(frequency_nm)
        register_value = int(frequency_nm * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6131, register_value)
            return bool(result)
        self._enqueue_write("additional_seop_resonance_frequency", task, {"frequency_nm": frequency_nm})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalSEOPResonanceFrequency(self) -> bool:
        """Увеличение SEOP Resonance Frequency на 0.01 nm"""
        return self.setAdditionalSEOPResonanceFrequency(self._additional_seop_resonance_frequency + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalSEOPResonanceFrequency(self) -> bool:
        """Уменьшение SEOP Resonance Frequency на 0.01 nm"""
        return self.setAdditionalSEOPResonanceFrequency(self._additional_seop_resonance_frequency - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalSEOPResonanceFrequencyTolerance(self, tolerance: float) -> bool:
        """Установка SEOP Resonance Frequency Tolerance (регистр 6141)"""
        # Логируем действие
        self._addLog(f"SEOP Resonance Frequency Tolerance: {tolerance}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_seop_resonance_frequency_tolerance = tolerance
        self._additional_seop_resonance_frequency_tolerance_user_interaction = True
        self.additionalSEOPResonanceFrequencyToleranceChanged.emit(tolerance)
        register_value = int(tolerance)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6141, register_value)
            return bool(result)
        self._enqueue_write("additional_seop_resonance_frequency_tolerance", task, {"tolerance": tolerance})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalSEOPResonanceFrequencyTolerance(self) -> bool:
        """Увеличение SEOP Resonance Frequency Tolerance на 1"""
        return self.setAdditionalSEOPResonanceFrequencyTolerance(self._additional_seop_resonance_frequency_tolerance + 1.0)
    
    @Slot(result=bool)
    def decreaseAdditionalSEOPResonanceFrequencyTolerance(self) -> bool:
        """Уменьшение SEOP Resonance Frequency Tolerance на 1"""
        return self.setAdditionalSEOPResonanceFrequencyTolerance(self._additional_seop_resonance_frequency_tolerance - 1.0)
    
    @Slot(float, result=bool)
    def setAdditionalIRSpectrometerNumberOfScans(self, num_scans: float) -> bool:
        """Установка IR spectrometer number of scans (регистр 6151)"""
        # Логируем действие
        self._addLog(f"IR Spectrometer Number of Scans: {num_scans}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_ir_spectrometer_number_of_scans = num_scans
        self._additional_ir_spectrometer_number_of_scans_user_interaction = True
        self.additionalIRSpectrometerNumberOfScansChanged.emit(num_scans)
        register_value = int(num_scans)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6151, register_value)
            return bool(result)
        self._enqueue_write("additional_ir_spectrometer_number_of_scans", task, {"num_scans": num_scans})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalIRSpectrometerNumberOfScans(self) -> bool:
        """Увеличение IR spectrometer number of scans на 1"""
        return self.setAdditionalIRSpectrometerNumberOfScans(self._additional_ir_spectrometer_number_of_scans + 1.0)
    
    @Slot(result=bool)
    def decreaseAdditionalIRSpectrometerNumberOfScans(self) -> bool:
        """Уменьшение IR spectrometer number of scans на 1"""
        return self.setAdditionalIRSpectrometerNumberOfScans(self._additional_ir_spectrometer_number_of_scans - 1.0)
    
    @Slot(float, result=bool)
    def setAdditionalIRSpectrometerExposureDuration(self, duration_ms: float) -> bool:
        """Установка IR spectrometer exposure duration в ms (регистр 6161)"""
        # Логируем действие
        self._addLog(f"IR Spectrometer Exposure Duration: {duration_ms} ms")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_ir_spectrometer_exposure_duration = duration_ms
        self._additional_ir_spectrometer_exposure_duration_user_interaction = True
        self.additionalIRSpectrometerExposureDurationChanged.emit(duration_ms)
        register_value = int(duration_ms * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6161, register_value)
            return bool(result)
        self._enqueue_write("additional_ir_spectrometer_exposure_duration", task, {"duration_ms": duration_ms})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalIRSpectrometerExposureDuration(self) -> bool:
        """Увеличение IR spectrometer exposure duration на 0.01 ms"""
        return self.setAdditionalIRSpectrometerExposureDuration(self._additional_ir_spectrometer_exposure_duration + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalIRSpectrometerExposureDuration(self) -> bool:
        """Уменьшение IR spectrometer exposure duration на 0.01 ms"""
        return self.setAdditionalIRSpectrometerExposureDuration(self._additional_ir_spectrometer_exposure_duration - 0.01)
    
    @Slot(float, result=bool)
    def setAdditional1HReferenceNScans(self, num_scans: float) -> bool:
        """Установка 1H Reference N Scans (регистр 6171)"""
        # Логируем действие
        self._addLog(f"1H Reference N Scans: {num_scans}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_1h_reference_n_scans = num_scans
        self._additional_1h_reference_n_scans_user_interaction = True
        self.additional1HReferenceNScansChanged.emit(num_scans)
        register_value = int(num_scans)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6171, register_value)
            return bool(result)
        self._enqueue_write("additional_1h_reference_n_scans", task, {"num_scans": num_scans})
        return True
    
    @Slot(result=bool)
    def increaseAdditional1HReferenceNScans(self) -> bool:
        """Увеличение 1H Reference N Scans на 1"""
        return self.setAdditional1HReferenceNScans(self._additional_1h_reference_n_scans + 1.0)
    
    @Slot(result=bool)
    def decreaseAdditional1HReferenceNScans(self) -> bool:
        """Уменьшение 1H Reference N Scans на 1"""
        return self.setAdditional1HReferenceNScans(self._additional_1h_reference_n_scans - 1.0)
    
    @Slot(float, result=bool)
    def setAdditional1HCurrentSweepNScans(self, num_scans: float) -> bool:
        """Установка 1H Current Sweep N Scans (регистр 6181)"""
        # Логируем действие
        self._addLog(f"1H Current Sweep N Scans: {num_scans}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_1h_current_sweep_n_scans = num_scans
        self._additional_1h_current_sweep_n_scans_user_interaction = True
        self.additional1HCurrentSweepNScansChanged.emit(num_scans)
        register_value = int(num_scans)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6181, register_value)
            return bool(result)
        self._enqueue_write("additional_1h_current_sweep_n_scans", task, {"num_scans": num_scans})
        return True
    
    @Slot(result=bool)
    def increaseAdditional1HCurrentSweepNScans(self) -> bool:
        """Увеличение 1H Current Sweep N Scans на 1"""
        return self.setAdditional1HCurrentSweepNScans(self._additional_1h_current_sweep_n_scans + 1.0)
    
    @Slot(result=bool)
    def decreaseAdditional1HCurrentSweepNScans(self) -> bool:
        """Уменьшение 1H Current Sweep N Scans на 1"""
        return self.setAdditional1HCurrentSweepNScans(self._additional_1h_current_sweep_n_scans - 1.0)
    
    @Slot(float, result=bool)
    def setAdditionalBaselineCorrectionMinFrequency(self, frequency_khz: float) -> bool:
        """Установка Baseline correction min frequency в kHz (регистр 6191)"""
        # Логируем действие
        self._addLog(f"Baseline Correction Min Frequency: {frequency_khz} kHz")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_baseline_correction_min_frequency = frequency_khz
        self._additional_baseline_correction_min_frequency_user_interaction = True
        self.additionalBaselineCorrectionMinFrequencyChanged.emit(frequency_khz)
        register_value = int(frequency_khz * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6191, register_value)
            return bool(result)
        self._enqueue_write("additional_baseline_correction_min_frequency", task, {"frequency_khz": frequency_khz})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalBaselineCorrectionMinFrequency(self) -> bool:
        """Увеличение Baseline correction min frequency на 0.01 kHz"""
        return self.setAdditionalBaselineCorrectionMinFrequency(self._additional_baseline_correction_min_frequency + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalBaselineCorrectionMinFrequency(self) -> bool:
        """Уменьшение Baseline correction min frequency на 0.01 kHz"""
        return self.setAdditionalBaselineCorrectionMinFrequency(self._additional_baseline_correction_min_frequency - 0.01)
    
    @Slot(float, result=bool)
    def setAdditionalBaselineCorrectionMaxFrequency(self, frequency_khz: float) -> bool:
        """Установка Baseline correction max frequency в kHz (регистр 6201)"""
        # Логируем действие
        self._addLog(f"Baseline Correction Max Frequency: {frequency_khz} kHz")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._additional_baseline_correction_max_frequency = frequency_khz
        self._additional_baseline_correction_max_frequency_user_interaction = True
        self.additionalBaselineCorrectionMaxFrequencyChanged.emit(frequency_khz)
        register_value = int(frequency_khz * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6201, register_value)
            return bool(result)
        self._enqueue_write("additional_baseline_correction_max_frequency", task, {"frequency_khz": frequency_khz})
        return True
    
    @Slot(result=bool)
    def increaseAdditionalBaselineCorrectionMaxFrequency(self) -> bool:
        """Увеличение Baseline correction max frequency на 0.01 kHz"""
        return self.setAdditionalBaselineCorrectionMaxFrequency(self._additional_baseline_correction_max_frequency + 0.01)
    
    @Slot(result=bool)
    def decreaseAdditionalBaselineCorrectionMaxFrequency(self) -> bool:
        """Уменьшение Baseline correction max frequency на 0.01 kHz"""
        return self.setAdditionalBaselineCorrectionMaxFrequency(self._additional_baseline_correction_max_frequency - 0.01)
    
    # Методы setValue для TextField (ввод с клавиатуры)
    @Slot(float, result=bool)
    def setAdditionalMagnetPSUCurrentProtonNMRValue(self, current_a: float) -> bool:
        """Обновление внутреннего значения Magnet PSU current for proton NMR без отправки на устройство"""
        self._additional_magnet_psu_current_proton_nmr = current_a
        self.additionalMagnetPSUCurrentProtonNMRChanged.emit(current_a)
        self._additional_magnet_psu_current_proton_nmr_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalMagnetPSUCurrent129XeNMRValue(self, current_a: float) -> bool:
        """Обновление внутреннего значения Magnet PSU current for 129Xe NMR без отправки на устройство"""
        self._additional_magnet_psu_current_129xe_nmr = current_a
        self.additionalMagnetPSUCurrent129XeNMRChanged.emit(current_a)
        self._additional_magnet_psu_current_129xe_nmr_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalOperationalLaserPSUCurrentValue(self, current_a: float) -> bool:
        """Обновление внутреннего значения Operational Laser PSU current без отправки на устройство"""
        self._additional_operational_laser_psu_current = current_a
        self.additionalOperationalLaserPSUCurrentChanged.emit(current_a)
        self._additional_operational_laser_psu_current_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalRFPulseDurationValue(self, duration: float) -> bool:
        """Обновление внутреннего значения RF pulse duration без отправки на устройство"""
        self._additional_rf_pulse_duration = duration
        self.additionalRFPulseDurationChanged.emit(duration)
        self._additional_rf_pulse_duration_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalResonanceFrequencyValue(self, frequency_khz: float) -> bool:
        """Обновление внутреннего значения Resonance frequency без отправки на устройство"""
        self._additional_resonance_frequency = frequency_khz
        self.additionalResonanceFrequencyChanged.emit(frequency_khz)
        self._additional_resonance_frequency_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalProtonRFPulsePowerValue(self, power_percent: float) -> bool:
        """Обновление внутреннего значения Proton RF pulse power без отправки на устройство"""
        self._additional_proton_rf_pulse_power = power_percent
        self.additionalProtonRFPulsePowerChanged.emit(power_percent)
        self._additional_proton_rf_pulse_power_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalHP129XeRFPulsePowerValue(self, power_percent: float) -> bool:
        """Обновление внутреннего значения HP 129Xe RF pulse power без отправки на устройство"""
        self._additional_hp_129xe_rf_pulse_power = power_percent
        self.additionalHP129XeRFPulsePowerChanged.emit(power_percent)
        self._additional_hp_129xe_rf_pulse_power_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalStepSizeB0SweepHP129XeValue(self, step_size_a: float) -> bool:
        """Обновление внутреннего значения Step size during B0 field sweep for HP 129Xe без отправки на устройство"""
        self._additional_step_size_b0_sweep_hp_129xe = step_size_a
        self.additionalStepSizeB0SweepHP129XeChanged.emit(step_size_a)
        self._additional_step_size_b0_sweep_hp_129xe_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalStepSizeB0SweepProtonsValue(self, step_size_a: float) -> bool:
        """Обновление внутреннего значения Step size during B0 field sweep for protons без отправки на устройство"""
        self._additional_step_size_b0_sweep_protons = step_size_a
        self.additionalStepSizeB0SweepProtonsChanged.emit(step_size_a)
        self._additional_step_size_b0_sweep_protons_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalXeAlicatsPressureValue(self, pressure_torr: float) -> bool:
        """Обновление внутреннего значения Xe ALICATS pressure без отправки на устройство"""
        self._additional_xe_alicats_pressure = pressure_torr
        self.additionalXeAlicatsPressureChanged.emit(pressure_torr)
        self._additional_xe_alicats_pressure_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalNitrogenAlicatsPressureValue(self, pressure_torr: float) -> bool:
        """Обновление внутреннего значения Nitrogen ALICATS pressure без отправки на устройство"""
        self._additional_nitrogen_alicats_pressure = pressure_torr
        self.additionalNitrogenAlicatsPressureChanged.emit(pressure_torr)
        self._additional_nitrogen_alicats_pressure_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalChillerTempSetpointValue(self, setpoint: float) -> bool:
        """Обновление внутреннего значения Chiller Temp setpoint без отправки на устройство"""
        self._additional_chiller_temp_setpoint = setpoint
        self.additionalChillerTempSetpointChanged.emit(setpoint)
        self._additional_chiller_temp_setpoint_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalSEOPResonanceFrequencyValue(self, frequency_nm: float) -> bool:
        """Обновление внутреннего значения SEOP Resonance Frequency без отправки на устройство"""
        self._additional_seop_resonance_frequency = frequency_nm
        self.additionalSEOPResonanceFrequencyChanged.emit(frequency_nm)
        self._additional_seop_resonance_frequency_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalSEOPResonanceFrequencyToleranceValue(self, tolerance: float) -> bool:
        """Обновление внутреннего значения SEOP Resonance Frequency Tolerance без отправки на устройство"""
        self._additional_seop_resonance_frequency_tolerance = tolerance
        self.additionalSEOPResonanceFrequencyToleranceChanged.emit(tolerance)
        self._additional_seop_resonance_frequency_tolerance_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalIRSpectrometerNumberOfScansValue(self, num_scans: float) -> bool:
        """Обновление внутреннего значения IR spectrometer number of scans без отправки на устройство"""
        self._additional_ir_spectrometer_number_of_scans = num_scans
        self.additionalIRSpectrometerNumberOfScansChanged.emit(num_scans)
        self._additional_ir_spectrometer_number_of_scans_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalIRSpectrometerExposureDurationValue(self, duration_ms: float) -> bool:
        """Обновление внутреннего значения IR spectrometer exposure duration без отправки на устройство"""
        self._additional_ir_spectrometer_exposure_duration = duration_ms
        self.additionalIRSpectrometerExposureDurationChanged.emit(duration_ms)
        self._additional_ir_spectrometer_exposure_duration_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditional1HReferenceNScansValue(self, num_scans: float) -> bool:
        """Обновление внутреннего значения 1H Reference N Scans без отправки на устройство"""
        self._additional_1h_reference_n_scans = num_scans
        self.additional1HReferenceNScansChanged.emit(num_scans)
        self._additional_1h_reference_n_scans_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditional1HCurrentSweepNScansValue(self, num_scans: float) -> bool:
        """Обновление внутреннего значения 1H Current Sweep N Scans без отправки на устройство"""
        self._additional_1h_current_sweep_n_scans = num_scans
        self.additional1HCurrentSweepNScansChanged.emit(num_scans)
        self._additional_1h_current_sweep_n_scans_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalBaselineCorrectionMinFrequencyValue(self, frequency_khz: float) -> bool:
        """Обновление внутреннего значения Baseline correction min frequency без отправки на устройство"""
        self._additional_baseline_correction_min_frequency = frequency_khz
        self.additionalBaselineCorrectionMinFrequencyChanged.emit(frequency_khz)
        self._additional_baseline_correction_min_frequency_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setAdditionalBaselineCorrectionMaxFrequencyValue(self, frequency_khz: float) -> bool:
        """Обновление внутреннего значения Baseline correction max frequency без отправки на устройство"""
        self._additional_baseline_correction_max_frequency = frequency_khz
        self.additionalBaselineCorrectionMaxFrequencyChanged.emit(frequency_khz)
        self._additional_baseline_correction_max_frequency_user_interaction = True
        return True
    
    # ===== Manual mode settings методы записи =====
    @Slot(float, result=bool)
    def setManualModeRFPulseFrequency(self, frequency_khz: float) -> bool:
        """Установка RF pulse frequency в kHz (регистр 6301)"""
        # Логируем действие
        self._addLog(f"RF Pulse Frequency: {frequency_khz} kHz")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_rf_pulse_frequency = frequency_khz
        self._manual_mode_rf_pulse_frequency_user_interaction = True
        self.manualModeRFPulseFrequencyChanged.emit(frequency_khz)
        register_value = int(frequency_khz * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6301, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_rf_pulse_frequency", task, {"frequency_khz": frequency_khz})
        return True
    
    @Slot(result=bool)
    def increaseManualModeRFPulseFrequency(self) -> bool:
        """Увеличение RF pulse frequency на 0.01 kHz"""
        return self.setManualModeRFPulseFrequency(self._manual_mode_rf_pulse_frequency + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModeRFPulseFrequency(self) -> bool:
        """Уменьшение RF pulse frequency на 0.01 kHz"""
        return self.setManualModeRFPulseFrequency(self._manual_mode_rf_pulse_frequency - 0.01)
    
    @Slot(float, result=bool)
    def setManualModeRFPulsePower(self, power_percent: float) -> bool:
        """Установка RF pulse power в % (регистр 6311)"""
        # Логируем действие
        self._addLog(f"RF Pulse Power: {power_percent}%")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_rf_pulse_power = power_percent
        self._manual_mode_rf_pulse_power_user_interaction = True
        self.manualModeRFPulsePowerChanged.emit(power_percent)
        register_value = int(power_percent * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6311, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_rf_pulse_power", task, {"power_percent": power_percent})
        return True
    
    @Slot(result=bool)
    def increaseManualModeRFPulsePower(self) -> bool:
        """Увеличение RF pulse power на 0.01%"""
        return self.setManualModeRFPulsePower(self._manual_mode_rf_pulse_power + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModeRFPulsePower(self) -> bool:
        """Уменьшение RF pulse power на 0.01%"""
        return self.setManualModeRFPulsePower(self._manual_mode_rf_pulse_power - 0.01)
    
    @Slot(float, result=bool)
    def setManualModeRFPulseDuration(self, duration_t2: float) -> bool:
        """Установка RF pulse duration в T/2 (регистр 6321)"""
        # Логируем действие
        self._addLog(f"RF Pulse Duration: {duration_t2} T/2")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_rf_pulse_duration = duration_t2
        self._manual_mode_rf_pulse_duration_user_interaction = True
        self.manualModeRFPulseDurationChanged.emit(duration_t2)
        register_value = int(duration_t2 * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6321, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_rf_pulse_duration", task, {"duration_t2": duration_t2})
        return True
    
    @Slot(result=bool)
    def increaseManualModeRFPulseDuration(self) -> bool:
        """Увеличение RF pulse duration на 0.01 T/2"""
        return self.setManualModeRFPulseDuration(self._manual_mode_rf_pulse_duration + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModeRFPulseDuration(self) -> bool:
        """Уменьшение RF pulse duration на 0.01 T/2"""
        return self.setManualModeRFPulseDuration(self._manual_mode_rf_pulse_duration - 0.01)
    
    @Slot(float, result=bool)
    def setManualModePreAcquisition(self, duration_ms: float) -> bool:
        """Установка Pre acquisition в ms (регистр 6331)"""
        # Логируем действие
        self._addLog(f"Pre Acquisition: {duration_ms} ms")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_pre_acquisition = duration_ms
        self._manual_mode_pre_acquisition_user_interaction = True
        self.manualModePreAcquisitionChanged.emit(duration_ms)
        register_value = int(duration_ms * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6331, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_pre_acquisition", task, {"duration_ms": duration_ms})
        return True
    
    @Slot(result=bool)
    def increaseManualModePreAcquisition(self) -> bool:
        """Увеличение Pre acquisition на 0.01 ms"""
        return self.setManualModePreAcquisition(self._manual_mode_pre_acquisition + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModePreAcquisition(self) -> bool:
        """Уменьшение Pre acquisition на 0.01 ms"""
        return self.setManualModePreAcquisition(self._manual_mode_pre_acquisition - 0.01)
    
    @Slot(float, result=bool)
    def setManualModeNMRGain(self, gain_db: float) -> bool:
        """Установка NMR gain в dB (регистр 6341)"""
        # Логируем действие
        self._addLog(f"NMR Gain: {gain_db} dB")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_nmr_gain = gain_db
        self._manual_mode_nmr_gain_user_interaction = True
        self.manualModeNMRGainChanged.emit(gain_db)
        register_value = int(gain_db * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6341, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_nmr_gain", task, {"gain_db": gain_db})
        return True
    
    @Slot(result=bool)
    def increaseManualModeNMRGain(self) -> bool:
        """Увеличение NMR gain на 0.01 dB"""
        return self.setManualModeNMRGain(self._manual_mode_nmr_gain + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModeNMRGain(self) -> bool:
        """Уменьшение NMR gain на 0.01 dB"""
        return self.setManualModeNMRGain(self._manual_mode_nmr_gain - 0.01)
    
    @Slot(float, result=bool)
    def setManualModeNMRNumberOfScans(self, num_scans: float) -> bool:
        """Установка NMR number of scans (регистр 6351)"""
        # Логируем действие
        self._addLog(f"NMR Number of Scans: {num_scans}")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_nmr_number_of_scans = num_scans
        self._manual_mode_nmr_number_of_scans_user_interaction = True
        self.manualModeNMRNumberOfScansChanged.emit(num_scans)
        register_value = int(num_scans)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6351, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_nmr_number_of_scans", task, {"num_scans": num_scans})
        return True
    
    @Slot(result=bool)
    def increaseManualModeNMRNumberOfScans(self) -> bool:
        """Увеличение NMR number of scans на 1"""
        return self.setManualModeNMRNumberOfScans(self._manual_mode_nmr_number_of_scans + 1.0)
    
    @Slot(result=bool)
    def decreaseManualModeNMRNumberOfScans(self) -> bool:
        """Уменьшение NMR number of scans на 1"""
        return self.setManualModeNMRNumberOfScans(self._manual_mode_nmr_number_of_scans - 1.0)
    
    @Slot(float, result=bool)
    def setManualModeNMRRecovery(self, duration_ms: float) -> bool:
        """Установка NMR recovery в ms (регистр 6361)"""
        # Логируем действие
        self._addLog(f"NMR Recovery: {duration_ms} ms")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_nmr_recovery = duration_ms
        self._manual_mode_nmr_recovery_user_interaction = True
        self.manualModeNMRRecoveryChanged.emit(duration_ms)
        register_value = int(duration_ms * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6361, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_nmr_recovery", task, {"duration_ms": duration_ms})
        return True
    
    @Slot(result=bool)
    def increaseManualModeNMRRecovery(self) -> bool:
        """Увеличение NMR recovery на 0.01 ms"""
        return self.setManualModeNMRRecovery(self._manual_mode_nmr_recovery + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModeNMRRecovery(self) -> bool:
        """Уменьшение NMR recovery на 0.01 ms"""
        return self.setManualModeNMRRecovery(self._manual_mode_nmr_recovery - 0.01)
    
    @Slot(float, result=bool)
    def setManualModeCenterFrequency(self, frequency_khz: float) -> bool:
        """Установка Center frequency в kHz (регистр 6371)"""
        # Логируем действие
        self._addLog(f"Center Frequency: {frequency_khz} kHz")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_center_frequency = frequency_khz
        self._manual_mode_center_frequency_user_interaction = True
        self.manualModeCenterFrequencyChanged.emit(frequency_khz)
        register_value = int(frequency_khz * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6371, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_center_frequency", task, {"frequency_khz": frequency_khz})
        return True
    
    @Slot(result=bool)
    def increaseManualModeCenterFrequency(self) -> bool:
        """Увеличение Center frequency на 0.01 kHz"""
        return self.setManualModeCenterFrequency(self._manual_mode_center_frequency + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModeCenterFrequency(self) -> bool:
        """Уменьшение Center frequency на 0.01 kHz"""
        return self.setManualModeCenterFrequency(self._manual_mode_center_frequency - 0.01)
    
    @Slot(float, result=bool)
    def setManualModeFrequencySpan(self, frequency_khz: float) -> bool:
        """Установка Frequency span в kHz (регистр 6381)"""
        # Логируем действие
        self._addLog(f"Frequency Span: {frequency_khz} kHz")
        if not self._is_connected or self._modbus_client is None:
            return False
        self._manual_mode_frequency_span = frequency_khz
        self._manual_mode_frequency_span_user_interaction = True
        self.manualModeFrequencySpanChanged.emit(frequency_khz)
        register_value = int(frequency_khz * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(6381, register_value)
            return bool(result)
        self._enqueue_write("manual_mode_frequency_span", task, {"frequency_khz": frequency_khz})
        return True
    
    @Slot(result=bool)
    def increaseManualModeFrequencySpan(self) -> bool:
        """Увеличение Frequency span на 0.01 kHz"""
        return self.setManualModeFrequencySpan(self._manual_mode_frequency_span + 0.01)
    
    @Slot(result=bool)
    def decreaseManualModeFrequencySpan(self) -> bool:
        """Уменьшение Frequency span на 0.01 kHz"""
        return self.setManualModeFrequencySpan(self._manual_mode_frequency_span - 0.01)
    
    # Методы setValue для TextField (ввод с клавиатуры)
    @Slot(float, result=bool)
    def setManualModeRFPulseFrequencyValue(self, frequency_khz: float) -> bool:
        """Обновление внутреннего значения RF pulse frequency без отправки на устройство"""
        self._manual_mode_rf_pulse_frequency = frequency_khz
        self.manualModeRFPulseFrequencyChanged.emit(frequency_khz)
        self._manual_mode_rf_pulse_frequency_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModeRFPulsePowerValue(self, power_percent: float) -> bool:
        """Обновление внутреннего значения RF pulse power без отправки на устройство"""
        self._manual_mode_rf_pulse_power = power_percent
        self.manualModeRFPulsePowerChanged.emit(power_percent)
        self._manual_mode_rf_pulse_power_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModeRFPulseDurationValue(self, duration_t2: float) -> bool:
        """Обновление внутреннего значения RF pulse duration без отправки на устройство"""
        self._manual_mode_rf_pulse_duration = duration_t2
        self.manualModeRFPulseDurationChanged.emit(duration_t2)
        self._manual_mode_rf_pulse_duration_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModePreAcquisitionValue(self, duration_ms: float) -> bool:
        """Обновление внутреннего значения Pre acquisition без отправки на устройство"""
        self._manual_mode_pre_acquisition = duration_ms
        self.manualModePreAcquisitionChanged.emit(duration_ms)
        self._manual_mode_pre_acquisition_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModeNMRGainValue(self, gain_db: float) -> bool:
        """Обновление внутреннего значения NMR gain без отправки на устройство"""
        self._manual_mode_nmr_gain = gain_db
        self.manualModeNMRGainChanged.emit(gain_db)
        self._manual_mode_nmr_gain_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModeNMRNumberOfScansValue(self, num_scans: float) -> bool:
        """Обновление внутреннего значения NMR number of scans без отправки на устройство"""
        self._manual_mode_nmr_number_of_scans = num_scans
        self.manualModeNMRNumberOfScansChanged.emit(num_scans)
        self._manual_mode_nmr_number_of_scans_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModeNMRRecoveryValue(self, duration_ms: float) -> bool:
        """Обновление внутреннего значения NMR recovery без отправки на устройство"""
        self._manual_mode_nmr_recovery = duration_ms
        self.manualModeNMRRecoveryChanged.emit(duration_ms)
        self._manual_mode_nmr_recovery_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModeCenterFrequencyValue(self, frequency_khz: float) -> bool:
        """Обновление внутреннего значения Center frequency без отправки на устройство"""
        self._manual_mode_center_frequency = frequency_khz
        self.manualModeCenterFrequencyChanged.emit(frequency_khz)
        self._manual_mode_center_frequency_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setManualModeFrequencySpanValue(self, frequency_khz: float) -> bool:
        """Обновление внутреннего значения Frequency span без отправки на устройство"""
        self._manual_mode_frequency_span = frequency_khz
        self.manualModeFrequencySpanChanged.emit(frequency_khz)
        self._manual_mode_frequency_span_user_interaction = True
        return True
    
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
            # Логируем действие
            self._addLog(f"{fan_name_mapping[10]}: {'ON' if state else 'OFF'}")
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
                # Логируем действие
                self._addLog(f"{fan_name_mapping[fanIndex]}: {'ON' if state else 'OFF'}")
            else:
                self._updateActionStatus(f"set fan {fanIndex + 1}")
                # Логируем действие
                self._addLog(f"Fan {fanIndex + 1}: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"Laser PSU: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"Magnet PSU: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"PID Controller: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"Water Chiller: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"Laser Beam: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"Vacuum Pump: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"Vacuum Gauge: {'ON' if state else 'OFF'}")
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
        # Логируем действие
        self._addLog(f"Valve X{valve_number}: {'OPEN' if state else 'CLOSED'}")
        
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
    
    # ===== Power Supply методы записи =====
    @Slot(float, result=bool)
    def setLaserPSUVoltageSetpoint(self, voltage: float) -> bool:
        """Установка заданного напряжения Laser PSU (регистр 1221)"""
        # Логируем действие
        self._addLog(f"Laser PSU Voltage Setpoint: {voltage} V")
        logger.info(f"🔵 setLaserPSUVoltageSetpoint вызван с напряжением: {voltage} V")
        if not self._is_connected or self._modbus_client is None:
            return False
        # Преобразуем напряжение в значение для регистра (умножаем на 100)
        register_value = int(voltage * 100)
        client = self._modbus_client
        def task() -> bool:
            # TODO: добавить метод write_register_1221_direct в modbus_client.py
            result = client.write_holding_register(1221, register_value)
            return bool(result)
        self._enqueue_write("1221", task, {"voltage": voltage})
        return True
    
    @Slot(float, result=bool)
    def setLaserPSUCurrentSetpoint(self, current: float) -> bool:
        """Установка заданного тока Laser PSU (регистр 1241)"""
        # Логируем действие
        self._addLog(f"Laser PSU Current Setpoint: {current} A")
        logger.info(f"🔵 setLaserPSUCurrentSetpoint вызван с током: {current} A")
        if not self._is_connected or self._modbus_client is None:
            return False
        # Преобразуем ток в значение для регистра (умножаем на 100)
        register_value = int(current * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_register_1241_direct(register_value)
            return bool(result)
        self._enqueue_write("1241", task, {"current": current})
        return True
    
    @Slot(bool, result=bool)
    def setLaserPSUPower(self, state: bool) -> bool:
        """Управление Laser PSU (регистр 1251: 1 = вкл, 0 = выкл)"""
        # Логируем действие
        self._addLog(f"Laser PSU Power: {'ON' if state else 'OFF'}")
        logger.info(f"🔵 setLaserPSUPower вызван: {state}")
        if not self._is_connected or self._modbus_client is None:
            return False
        register_value = 1 if state else 0
        client = self._modbus_client
        def task() -> bool:
            # TODO: добавить метод write_register_1251_direct в modbus_client.py
            result = client.write_holding_register(1251, register_value)
            return bool(result)
        self._enqueue_write("1251", task, {"state": state})
        # Обновляем UI сразу
        self.laserPSUStateChanged.emit(state)
        return True
    
    @Slot(float, result=bool)
    def setMagnetPSUVoltageSetpoint(self, voltage: float) -> bool:
        """Установка заданного напряжения Magnet PSU (регистр 1311)"""
        # Логируем действие
        self._addLog(f"Magnet PSU Voltage Setpoint: {voltage} V")
        logger.info(f"🔵 setMagnetPSUVoltageSetpoint вызван с напряжением: {voltage} V")
        if not self._is_connected or self._modbus_client is None:
            return False
        # Преобразуем напряжение в значение для регистра (умножаем на 100)
        register_value = int(voltage * 100)
        client = self._modbus_client
        def task() -> bool:
            # TODO: добавить метод write_register_1311_direct в modbus_client.py
            result = client.write_holding_register(1311, register_value)
            return bool(result)
        self._enqueue_write("1311", task, {"voltage": voltage})
        return True
    
    @Slot(float, result=bool)
    def setMagnetPSUCurrentSetpoint(self, current: float) -> bool:
        """Установка заданного тока Magnet PSU (регистр 1331)"""
        # Логируем действие
        self._addLog(f"Magnet PSU Current Setpoint: {current} A")
        logger.info(f"🔵 setMagnetPSUCurrentSetpoint вызван с током: {current} A")
        if not self._is_connected or self._modbus_client is None:
            return False
        # Преобразуем ток в значение для регистра (умножаем на 100)
        register_value = int(current * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_register_1331_direct(register_value)
            return bool(result)
        self._enqueue_write("1331", task, {"current": current})
        return True
    
    @Slot(bool, result=bool)
    def setMagnetPSUPower(self, state: bool) -> bool:
        """Управление Magnet PSU (регистр 1341: 1 = вкл, 0 = выкл)"""
        # Логируем действие
        self._addLog(f"Magnet PSU Power: {'ON' if state else 'OFF'}")
        logger.info(f"🔵 setMagnetPSUPower вызван: {state}")
        if not self._is_connected or self._modbus_client is None:
            return False
        register_value = 1 if state else 0
        client = self._modbus_client
        def task() -> bool:
            # TODO: добавить метод write_register_1341_direct в modbus_client.py
            result = client.write_holding_register(1341, register_value)
            return bool(result)
        self._enqueue_write("1341", task, {"state": state})
        # Обновляем UI сразу
        self.magnetPSUStateChanged.emit(state)
        return True
    
    # ===== PID Controller методы записи =====
    @Slot(float, result=bool)
    def setPIDControllerTemperature(self, temperature: float) -> bool:
        """
        Установка заданной температуры PID Controller в регистр 1421
        
        Args:
            temperature: Температура в градусах Цельсия (например, 23.0)
        
        Returns:
            True если успешно, False в противном случае
        """
        # Логируем действие
        self._addLog(f"PID Controller Temperature: {temperature}°C")
        logger.info(f"🔵 setPIDControllerTemperature вызван с температурой: {temperature}°C")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set pid controller to {temperature:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки температуры PID Controller без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
        logger.info(f"🔵 Обновление _pid_controller_setpoint: {self._pid_controller_setpoint}°C -> {temperature}°C")
        self._pid_controller_setpoint = temperature
        # Отправляем сигнал для обновления UI (setpoint)
        logger.info(f"🔵 Эмитируем сигнал pidControllerSetpointChanged: {temperature}°C")
        self.pidControllerSetpointChanged.emit(temperature)
        
        # Преобразуем температуру в значение для регистра (умножаем на 100)
        # Например, 23.0°C -> 2300
        register_value = int(temperature * 100)
        
        logger.info(f"Установка температуры PID Controller: {temperature}°C (регистр 1421 = {register_value})")
        
        client = self._modbus_client

        def task() -> bool:
            result = client.write_register_1421_direct(register_value)
            if result:
                logger.info(f"✅ Заданная температура PID Controller успешно установлена: {temperature}°C")
            else:
                logger.error(f"❌ Не удалось установить заданную температуру PID Controller: {temperature}°C")
            return bool(result)

        self._enqueue_write("1421_pid", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increasePIDControllerTemperature(self) -> bool:
        """Увеличение заданной температуры PID Controller на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Увеличение температуры PID Controller: текущее значение = {self._pid_controller_setpoint}°C")
        new_temp = self._pid_controller_setpoint + 1.0
        logger.debug(f"Новое значение после увеличения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._pid_controller_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._pid_controller_setpoint_auto_update_timer.stop()
        self._pid_controller_setpoint_auto_update_timer.start()
        return self.setPIDControllerTemperature(new_temp)
    
    @Slot(result=bool)
    def decreasePIDControllerTemperature(self) -> bool:
        """Уменьшение заданной температуры PID Controller на 1°C"""
        if not self._is_connected:
            return False
        logger.debug(f"Уменьшение температуры PID Controller: текущее значение = {self._pid_controller_setpoint}°C")
        new_temp = self._pid_controller_setpoint - 1.0
        logger.debug(f"Новое значение после уменьшения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._pid_controller_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._pid_controller_setpoint_auto_update_timer.stop()
        self._pid_controller_setpoint_auto_update_timer.start()
        return self.setPIDControllerTemperature(new_temp)
    
    @Slot(bool, result=bool)
    def setPIDControllerPower(self, state: bool) -> bool:
        """Управление PID Controller (регистр 1431: 1 = вкл, 0 = выкл)"""
        # Логируем действие
        self._addLog(f"PID Controller Power: {'ON' if state else 'OFF'}")
        logger.info(f"🔵 setPIDControllerPower вызван: {state}")
        if not self._is_connected or self._modbus_client is None:
            return False
        register_value = 1 if state else 0
        client = self._modbus_client
        def task() -> bool:
            # TODO: добавить метод write_register_1431_direct в modbus_client.py
            result = client.write_holding_register(1431, register_value)
            return bool(result)
        self._enqueue_write("1431", task, {"state": state})
        # Обновляем UI сразу
        self._pid_controller_state = state
        self.pidControllerStateChanged.emit(state)
        return True
    
    # ===== Water Chiller методы записи =====
    @Slot(float, result=bool)
    def setWaterChillerTemperature(self, temperature: float) -> bool:
        """
        Установка заданной температуры Water Chiller в регистр 1531
        
        Args:
            temperature: Температура в градусах Цельсия (например, 23.0)
        
        Returns:
            True если успешно, False в противном случае
        """
        # Логируем действие
        self._addLog(f"Water Chiller Temperature: {temperature}°C")
        logger.info(f"🔵 setWaterChillerTemperature вызван с температурой: {temperature}°C")
        
        # Обновляем статус (даже без подключения)
        self._updateActionStatus(f"set water chiller to {temperature:.2f}")
        
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установки температуры Water Chiller без подключения")
            return False
        
        # Обновляем внутреннее значение setpoint сразу (до отправки на устройство)
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
        logger.debug(f"Увеличение температуры Water Chiller: текущее значение = {self._water_chiller_setpoint}°C")
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
        logger.debug(f"Уменьшение температуры Water Chiller: текущее значение = {self._water_chiller_setpoint}°C")
        new_temp = self._water_chiller_setpoint - 1.0
        logger.debug(f"Новое значение после уменьшения: {new_temp}°C")
        # Отмечаем, что пользователь взаимодействует с полем
        self._water_chiller_setpoint_user_interaction = True
        # Перезапускаем таймер автообновления
        self._water_chiller_setpoint_auto_update_timer.stop()
        self._water_chiller_setpoint_auto_update_timer.start()
        return self.setWaterChillerTemperature(new_temp)
    
    @Slot(bool, result=bool)
    def setLaserBeam(self, state: bool) -> bool:
        """Управление Beam Laser через регистр 1811 (1 = on, 0 = off)"""
        # Логируем действие
        self._addLog(f"Laser Beam: {'ON' if state else 'OFF'}")
        if not self._is_connected or self._modbus_client is None:
            logger.warning("Попытка установить Laser Beam без подключения")
            return False
        
        # Оптимистично обновляем UI
        self._laser_beam_state = state
        self.laserBeamStateChanged.emit(state)
        
        register_value = 1 if state else 0
        client = self._modbus_client
        
        def task() -> bool:
            result = client.write_holding_register(1811, register_value)
            if not result:
                logger.warning(f"⚠️ Запись Laser Beam в регистр 1811 не удалась (value={register_value}).")
            return bool(result)
        
        self._enqueue_write("laser_beam", task, {"state": state, "value": register_value})
        return True
    
    # ===== SEOP Parameters методы записи =====
    @Slot(float, result=bool)
    def setSEOPLaserMaxTemp(self, temperature: float) -> bool:
        """Установка Laser Max Temp (регистр 3011)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_laser_max_temp = temperature
        self._seop_laser_max_temp_user_interaction = True
        self.seopLaserMaxTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3011, register_value)
            return bool(result)
        self._enqueue_write("seop_laser_max_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPLaserMaxTemp(self) -> bool:
        """Увеличение Laser Max Temp на 1°C"""
        return self.setSEOPLaserMaxTemp(self._seop_laser_max_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPLaserMaxTemp(self) -> bool:
        """Уменьшение Laser Max Temp на 1°C"""
        return self.setSEOPLaserMaxTemp(self._seop_laser_max_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPLaserMinTemp(self, temperature: float) -> bool:
        """Установка Laser Min Temp (регистр 3021)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_laser_min_temp = temperature
        self._seop_laser_min_temp_user_interaction = True
        self.seopLaserMinTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3021, register_value)
            return bool(result)
        self._enqueue_write("seop_laser_min_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPLaserMinTemp(self) -> bool:
        """Увеличение Laser Min Temp на 1°C"""
        return self.setSEOPLaserMinTemp(self._seop_laser_min_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPLaserMinTemp(self) -> bool:
        """Уменьшение Laser Min Temp на 1°C"""
        return self.setSEOPLaserMinTemp(self._seop_laser_min_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPCellMaxTemp(self, temperature: float) -> bool:
        """Установка SEOP Cell Max Temp (регистр 3031)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_cell_max_temp = temperature
        self._seop_cell_max_temp_user_interaction = True
        self.seopCellMaxTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3031, register_value)
            return bool(result)
        self._enqueue_write("seop_cell_max_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPCellMaxTemp(self) -> bool:
        """Увеличение SEOP Cell Max Temp на 1°C"""
        return self.setSEOPCellMaxTemp(self._seop_cell_max_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPCellMaxTemp(self) -> bool:
        """Уменьшение SEOP Cell Max Temp на 1°C"""
        return self.setSEOPCellMaxTemp(self._seop_cell_max_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPCellMinTemp(self, temperature: float) -> bool:
        """Установка SEOP Cell Min Temp (регистр 3041)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_cell_min_temp = temperature
        self._seop_cell_min_temp_user_interaction = True
        self.seopCellMinTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3041, register_value)
            return bool(result)
        self._enqueue_write("seop_cell_min_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPCellMinTemp(self) -> bool:
        """Увеличение SEOP Cell Min Temp на 1°C"""
        return self.setSEOPCellMinTemp(self._seop_cell_min_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPCellMinTemp(self) -> bool:
        """Уменьшение SEOP Cell Min Temp на 1°C"""
        return self.setSEOPCellMinTemp(self._seop_cell_min_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPRampTemp(self, temperature: float) -> bool:
        """Установка Seop ramp Temp (регистр 3051)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_ramp_temp = temperature
        self._seop_ramp_temp_user_interaction = True
        self.seopRampTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3051, register_value)
            return bool(result)
        self._enqueue_write("seop_ramp_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPRampTemp(self) -> bool:
        """Увеличение Seop ramp Temp на 1°C"""
        return self.setSEOPRampTemp(self._seop_ramp_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPRampTemp(self) -> bool:
        """Уменьшение Seop ramp Temp на 1°C"""
        return self.setSEOPRampTemp(self._seop_ramp_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPTemp(self, temperature: float) -> bool:
        """Установка SEOP Temp (регистр 3061)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_temp = temperature
        self._seop_temp_user_interaction = True
        self.seopTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3061, register_value)
            return bool(result)
        self._enqueue_write("seop_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPTemp(self) -> bool:
        """Увеличение SEOP Temp на 1°C"""
        return self.setSEOPTemp(self._seop_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPTemp(self) -> bool:
        """Уменьшение SEOP Temp на 1°C"""
        return self.setSEOPTemp(self._seop_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPCellRefillTemp(self, temperature: float) -> bool:
        """Установка Cell Refill Temp (регистр 3071)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_cell_refill_temp = temperature
        self._seop_cell_refill_temp_user_interaction = True
        self.seopCellRefillTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3071, register_value)
            return bool(result)
        self._enqueue_write("seop_cell_refill_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPCellRefillTemp(self) -> bool:
        """Увеличение Cell Refill Temp на 1°C"""
        return self.setSEOPCellRefillTemp(self._seop_cell_refill_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPCellRefillTemp(self) -> bool:
        """Уменьшение Cell Refill Temp на 1°C"""
        return self.setSEOPCellRefillTemp(self._seop_cell_refill_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPLoopTime(self, time_seconds: float) -> bool:
        """Установка SEOP loop time в секундах (регистр 3081)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_loop_time = time_seconds
        self._seop_loop_time_user_interaction = True
        self.seopLoopTimeChanged.emit(time_seconds)
        register_value = int(time_seconds)  # Время в секундах - целое число
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3081, register_value)
            return bool(result)
        self._enqueue_write("seop_loop_time", task, {"time_seconds": time_seconds})
        return True
    
    @Slot(result=bool)
    def increaseSEOPLoopTime(self) -> bool:
        """Увеличение SEOP loop time на 1 секунду"""
        return self.setSEOPLoopTime(self._seop_loop_time + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPLoopTime(self) -> bool:
        """Уменьшение SEOP loop time на 1 секунду"""
        return self.setSEOPLoopTime(self._seop_loop_time - 1.0)
    
    # Методы setValue для TextField (ввод с клавиатуры)
    @Slot(float, result=bool)
    def setSEOPLaserMaxTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения Laser Max Temp без отправки на устройство"""
        self._seop_laser_max_temp = temperature
        self.seopLaserMaxTempChanged.emit(temperature)
        self._seop_laser_max_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPLaserMinTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения Laser Min Temp без отправки на устройство"""
        self._seop_laser_min_temp = temperature
        self.seopLaserMinTempChanged.emit(temperature)
        self._seop_laser_min_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPCellMaxTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения SEOP Cell Max Temp без отправки на устройство"""
        self._seop_cell_max_temp = temperature
        self.seopCellMaxTempChanged.emit(temperature)
        self._seop_cell_max_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPCellMinTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения SEOP Cell Min Temp без отправки на устройство"""
        self._seop_cell_min_temp = temperature
        self.seopCellMinTempChanged.emit(temperature)
        self._seop_cell_min_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPRampTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения Seop ramp Temp без отправки на устройство"""
        self._seop_ramp_temp = temperature
        self.seopRampTempChanged.emit(temperature)
        self._seop_ramp_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения SEOP Temp без отправки на устройство"""
        self._seop_temp = temperature
        self.seopTempChanged.emit(temperature)
        self._seop_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPCellRefillTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения Cell Refill Temp без отправки на устройство"""
        self._seop_cell_refill_temp = temperature
        self.seopCellRefillTempChanged.emit(temperature)
        self._seop_cell_refill_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPLoopTimeValue(self, time_seconds: float) -> bool:
        """Обновление внутреннего значения SEOP loop time без отправки на устройство"""
        self._seop_loop_time = time_seconds
        self.seopLoopTimeChanged.emit(time_seconds)
        self._seop_loop_time_user_interaction = True
        return True
    
    # Новые методы для дополнительных параметров SEOP
    @Slot(float, result=bool)
    def setSEOPProcessDuration(self, duration_seconds: float) -> bool:
        """Установка SEOP process duration в секундах (регистр 3091), отображается как m:s"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_process_duration = duration_seconds
        self._seop_process_duration_user_interaction = True
        self.seopProcessDurationChanged.emit(duration_seconds)
        register_value = int(duration_seconds)  # В секундах - целое число
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3091, register_value)
            return bool(result)
        self._enqueue_write("seop_process_duration", task, {"duration_seconds": duration_seconds})
        return True
    
    @Slot(result=bool)
    def increaseSEOPProcessDuration(self) -> bool:
        """Увеличение SEOP process duration на 1 секунду"""
        return self.setSEOPProcessDuration(self._seop_process_duration + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPProcessDuration(self) -> bool:
        """Уменьшение SEOP process duration на 1 секунду"""
        return self.setSEOPProcessDuration(self._seop_process_duration - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPLaserMaxOutputPower(self, power_w: float) -> bool:
        """Установка Laser Max Output Power в W (регистр 3101)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_laser_max_output_power = power_w
        self._seop_laser_max_output_power_user_interaction = True
        self.seopLaserMaxOutputPowerChanged.emit(power_w)
        register_value = int(power_w * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3101, register_value)
            return bool(result)
        self._enqueue_write("seop_laser_max_output_power", task, {"power_w": power_w})
        return True
    
    @Slot(result=bool)
    def increaseSEOPLaserMaxOutputPower(self) -> bool:
        """Увеличение Laser Max Output Power на 0.1 W"""
        return self.setSEOPLaserMaxOutputPower(self._seop_laser_max_output_power + 0.1)
    
    @Slot(result=bool)
    def decreaseSEOPLaserMaxOutputPower(self) -> bool:
        """Уменьшение Laser Max Output Power на 0.1 W"""
        return self.setSEOPLaserMaxOutputPower(self._seop_laser_max_output_power - 0.1)
    
    @Slot(float, result=bool)
    def setSEOPLaserPSUMaxCurrent(self, current_a: float) -> bool:
        """Установка Laser PSU MAX Current в A (регистр 3111)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_laser_psu_max_current = current_a
        self._seop_laser_psu_max_current_user_interaction = True
        self.seopLaserPSUMaxCurrentChanged.emit(current_a)
        register_value = int(current_a * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3111, register_value)
            return bool(result)
        self._enqueue_write("seop_laser_psu_max_current", task, {"current_a": current_a})
        return True
    
    @Slot(result=bool)
    def increaseSEOPLaserPSUMaxCurrent(self) -> bool:
        """Увеличение Laser PSU MAX Current на 0.1 A"""
        return self.setSEOPLaserPSUMaxCurrent(self._seop_laser_psu_max_current + 0.1)
    
    @Slot(result=bool)
    def decreaseSEOPLaserPSUMaxCurrent(self) -> bool:
        """Уменьшение Laser PSU MAX Current на 0.1 A"""
        return self.setSEOPLaserPSUMaxCurrent(self._seop_laser_psu_max_current - 0.1)
    
    @Slot(float, result=bool)
    def setSEOPWaterChillerMaxTemp(self, temperature: float) -> bool:
        """Установка Water Chiller Max Temp в C (регистр 3121)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_water_chiller_max_temp = temperature
        self._seop_water_chiller_max_temp_user_interaction = True
        self.seopWaterChillerMaxTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3121, register_value)
            return bool(result)
        self._enqueue_write("seop_water_chiller_max_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPWaterChillerMaxTemp(self) -> bool:
        """Увеличение Water Chiller Max Temp на 1°C"""
        return self.setSEOPWaterChillerMaxTemp(self._seop_water_chiller_max_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPWaterChillerMaxTemp(self) -> bool:
        """Уменьшение Water Chiller Max Temp на 1°C"""
        return self.setSEOPWaterChillerMaxTemp(self._seop_water_chiller_max_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPWaterChillerMinTemp(self, temperature: float) -> bool:
        """Установка Water Chiller Min Temp в C (регистр 3131)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_water_chiller_min_temp = temperature
        self._seop_water_chiller_min_temp_user_interaction = True
        self.seopWaterChillerMinTempChanged.emit(temperature)
        register_value = int(temperature * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3131, register_value)
            return bool(result)
        self._enqueue_write("seop_water_chiller_min_temp", task, {"temperature": temperature})
        return True
    
    @Slot(result=bool)
    def increaseSEOPWaterChillerMinTemp(self) -> bool:
        """Увеличение Water Chiller Min Temp на 1°C"""
        return self.setSEOPWaterChillerMinTemp(self._seop_water_chiller_min_temp + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPWaterChillerMinTemp(self) -> bool:
        """Уменьшение Water Chiller Min Temp на 1°C"""
        return self.setSEOPWaterChillerMinTemp(self._seop_water_chiller_min_temp - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPXeConcentration(self, concentration_mmol: float) -> bool:
        """Установка 129Xe concentration of gas mixture в mMol (регистр 3141)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_xe_concentration = concentration_mmol
        self._seop_xe_concentration_user_interaction = True
        self.seopXeConcentrationChanged.emit(concentration_mmol)
        register_value = int(concentration_mmol)  # Уже в mMol, целое число
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3141, register_value)
            return bool(result)
        self._enqueue_write("seop_xe_concentration", task, {"concentration_mmol": concentration_mmol})
        return True
    
    @Slot(result=bool)
    def increaseSEOPXeConcentration(self) -> bool:
        """Увеличение 129Xe concentration на 1 mMol"""
        return self.setSEOPXeConcentration(self._seop_xe_concentration + 1.0)
    
    @Slot(result=bool)
    def decreaseSEOPXeConcentration(self) -> bool:
        """Уменьшение 129Xe concentration на 1 mMol"""
        return self.setSEOPXeConcentration(self._seop_xe_concentration - 1.0)
    
    @Slot(float, result=bool)
    def setSEOPWaterProtonConcentration(self, concentration_mol: float) -> bool:
        """Установка Water proton concentration в Mol (регистр 3151)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_water_proton_concentration = concentration_mol
        self._seop_water_proton_concentration_user_interaction = True
        self.seopWaterProtonConcentrationChanged.emit(concentration_mol)
        register_value = int(concentration_mol * 100)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3151, register_value)
            return bool(result)
        self._enqueue_write("seop_water_proton_concentration", task, {"concentration_mol": concentration_mol})
        return True
    
    @Slot(result=bool)
    def increaseSEOPWaterProtonConcentration(self) -> bool:
        """Увеличение Water proton concentration на 0.01 Mol"""
        return self.setSEOPWaterProtonConcentration(self._seop_water_proton_concentration + 0.01)
    
    @Slot(result=bool)
    def decreaseSEOPWaterProtonConcentration(self) -> bool:
        """Уменьшение Water proton concentration на 0.01 Mol"""
        return self.setSEOPWaterProtonConcentration(self._seop_water_proton_concentration - 0.01)
    
    # Методы setValue для новых параметров
    @Slot(float, result=bool)
    def setSEOPProcessDurationValue(self, duration_min: float) -> bool:
        """Обновление внутреннего значения SEOP process duration без отправки на устройство"""
        self._seop_process_duration = duration_min
        self.seopProcessDurationChanged.emit(duration_min)
        self._seop_process_duration_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPLaserMaxOutputPowerValue(self, power_w: float) -> bool:
        """Обновление внутреннего значения Laser Max Output Power без отправки на устройство"""
        self._seop_laser_max_output_power = power_w
        self.seopLaserMaxOutputPowerChanged.emit(power_w)
        self._seop_laser_max_output_power_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPLaserPSUMaxCurrentValue(self, current_a: float) -> bool:
        """Обновление внутреннего значения Laser PSU MAX Current без отправки на устройство"""
        self._seop_laser_psu_max_current = current_a
        self.seopLaserPSUMaxCurrentChanged.emit(current_a)
        self._seop_laser_psu_max_current_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPWaterChillerMaxTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения Water Chiller Max Temp без отправки на устройство"""
        self._seop_water_chiller_max_temp = temperature
        self.seopWaterChillerMaxTempChanged.emit(temperature)
        self._seop_water_chiller_max_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPWaterChillerMinTempValue(self, temperature: float) -> bool:
        """Обновление внутреннего значения Water Chiller Min Temp без отправки на устройство"""
        self._seop_water_chiller_min_temp = temperature
        self.seopWaterChillerMinTempChanged.emit(temperature)
        self._seop_water_chiller_min_temp_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPXeConcentrationValue(self, concentration_mmol: float) -> bool:
        """Обновление внутреннего значения 129Xe concentration без отправки на устройство"""
        self._seop_xe_concentration = concentration_mmol
        self.seopXeConcentrationChanged.emit(concentration_mmol)
        self._seop_xe_concentration_user_interaction = True
        return True
    
    @Slot(float, result=bool)
    def setSEOPWaterProtonConcentrationValue(self, concentration_mol: float) -> bool:
        """Обновление внутреннего значения Water proton concentration без отправки на устройство"""
        self._seop_water_proton_concentration = concentration_mol
        self.seopWaterProtonConcentrationChanged.emit(concentration_mol)
        self._seop_water_proton_concentration_user_interaction = True
        return True
    
    @Slot(int, result=bool)
    def setSEOPCellNumber(self, cell_number: int) -> bool:
        """Установка Cell number (регистр 3171)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_cell_number = cell_number
        self._seop_cell_number_user_interaction = True
        self.seopCellNumberChanged.emit(cell_number)
        register_value = int(cell_number)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3171, register_value)
            return bool(result)
        self._enqueue_write("seop_cell_number", task, {"cell_number": cell_number})
        return True
    
    @Slot(result=bool)
    def increaseSEOPCellNumber(self) -> bool:
        """Увеличение Cell number на 1"""
        return self.setSEOPCellNumber(self._seop_cell_number + 1)
    
    @Slot(result=bool)
    def decreaseSEOPCellNumber(self) -> bool:
        """Уменьшение Cell number на 1"""
        return self.setSEOPCellNumber(self._seop_cell_number - 1)
    
    @Slot(int, result=bool)
    def setSEOPRefillCycle(self, refill_cycle: int) -> bool:
        """Установка Refill cycle (регистр 3181)"""
        if not self._is_connected or self._modbus_client is None:
            return False
        self._seop_refill_cycle = refill_cycle
        self._seop_refill_cycle_user_interaction = True
        self.seopRefillCycleChanged.emit(refill_cycle)
        register_value = int(refill_cycle)
        client = self._modbus_client
        def task() -> bool:
            result = client.write_holding_register(3181, register_value)
            return bool(result)
        self._enqueue_write("seop_refill_cycle", task, {"refill_cycle": refill_cycle})
        return True
    
    @Slot(result=bool)
    def increaseSEOPRefillCycle(self) -> bool:
        """Увеличение Refill cycle на 1"""
        return self.setSEOPRefillCycle(self._seop_refill_cycle + 1)
    
    @Slot(result=bool)
    def decreaseSEOPRefillCycle(self) -> bool:
        """Уменьшение Refill cycle на 1"""
        return self.setSEOPRefillCycle(self._seop_refill_cycle - 1)
    
    # Методы setValue для новых параметров
    @Slot(float, result=bool)
    def setSEOPProcessDurationValue(self, duration_seconds: float) -> bool:
        """Обновление внутреннего значения SEOP process duration без отправки на устройство (в секундах)"""
        self._seop_process_duration = duration_seconds
        self.seopProcessDurationChanged.emit(duration_seconds)
        self._seop_process_duration_user_interaction = True
        return True
    
    @Slot(int, result=bool)
    def setSEOPCellNumberValue(self, cell_number: int) -> bool:
        """Обновление внутреннего значения Cell number без отправки на устройство"""
        self._seop_cell_number = cell_number
        self.seopCellNumberChanged.emit(cell_number)
        self._seop_cell_number_user_interaction = True
        return True
    
    @Slot(int, result=bool)
    def setSEOPRefillCycleValue(self, refill_cycle: int) -> bool:
        """Обновление внутреннего значения Refill cycle без отправки на устройство"""
        self._seop_refill_cycle = refill_cycle
        self.seopRefillCycleChanged.emit(refill_cycle)
        self._seop_refill_cycle_user_interaction = True
        return True
    
    @Slot(bool, result=bool)
    def setWaterChillerPower(self, state: bool) -> bool:
        """Управление Water Chiller (регистр 1541: 1 = вкл, 0 = выкл)"""
        # Логируем действие
        self._addLog(f"Water Chiller Power: {'ON' if state else 'OFF'}")
        logger.info(f"🔵 setWaterChillerPower вызван: {state}")
        if not self._is_connected or self._modbus_client is None:
            return False
        register_value = 1 if state else 0
        client = self._modbus_client
        def task() -> bool:
            # TODO: добавить метод write_register_1541_direct в modbus_client.py
            result = client.write_holding_register(1541, register_value)
            return bool(result)
        self._enqueue_write("1541", task, {"state": state})
        # Обновляем UI сразу
        self._water_chiller_state = state
        self.waterChillerStateChanged.emit(state)
        return True

