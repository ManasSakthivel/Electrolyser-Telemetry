#!/usr/bin/env python3
"""
plant_sim.py
============
Physics-based digital twin for a two-electrolyser plant (EL1, EL2) + 2 irradiance sensors.

Architecture
------------
PlantSimulator
├── ElectrolyserTwin (EL1)
│   ├── FaultInjector
│   └── per-sensor MQTT clients (one TLS connection per X.509 certificate)
├── ElectrolyserTwin (EL2)
│   └── ...
└── Irradiance sensor clients (sensor-plant-A-irradiance_1/2)

Physics model
-------------
Stack voltage:   V_stack = N × (U_rev + V_act + V_conc + R_ohm × I)
  where V_act  = (RT / αF) × arcsinh(I / 2I₀)        [Butler-Volmer activation overpotential]
        V_conc = (RT / 2F) × ln(I_lim / (I_lim − I)) [Nernst concentration overpotential]
H₂ production:   ṅ_H₂ = (η_F × N × I) / 2F          [Faraday's law]
Tank pressure:   P = nRT / V                           [ideal gas law]

Run
---
  python3 clients/python/plant_sim.py [--broker 127.0.0.1] [--port 8883] [--dt 1.0]
"""

from __future__ import annotations

import json
import logging
import math
import pathlib
import random
import ssl
import time
from threading import Event, Lock
from typing import Dict, List, Optional, Tuple

from paho.mqtt import client as mqtt

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("plant_sim")

ROOT = pathlib.Path(__file__).resolve().parents[2]

# ── Fault catalogue ───────────────────────────────────────────────────────────
FAULT_NONE              = 0
FAULT_MEMBRANE_PINHOLE  = 1
FAULT_GAS_CROSSOVER     = 2
FAULT_CELL_FLOODING     = 3
FAULT_CELL_DRYOUT       = 4
FAULT_PUMP_FAILURE      = 5
FAULT_DCDC_FAILURE      = 6
FAULT_SOLAR_TRANSIENT   = 7
FAULT_LEVEL_SENSOR      = 8
FAULT_IRRADIANCE_DRIFT  = 9
FAULT_VOLTAGE_SENSOR_DRIFT = 10
FAULT_TEMP_SENSOR_FAILURE  = 11
FAULT_LOOSE_BOLT           = 12
FAULT_O2_BLOCKAGE          = 13
FAULT_TELEMETRY_DROPOUT    = 14
FAULT_OVER_PRESSURE        = 15

FAULT_NAMES: Dict[str, int] = {
    "none":                 FAULT_NONE,
    "membrane_pinhole":     FAULT_MEMBRANE_PINHOLE,
    "gas_crossover":        FAULT_GAS_CROSSOVER,
    "cell_flooding":        FAULT_CELL_FLOODING,
    "cell_dryout":          FAULT_CELL_DRYOUT,
    "pump_failure":         FAULT_PUMP_FAILURE,
    "dcdc_failure":         FAULT_DCDC_FAILURE,
    "solar_transient":      FAULT_SOLAR_TRANSIENT,
    "level_sensor":         FAULT_LEVEL_SENSOR,
    "irradiance_drift":     FAULT_IRRADIANCE_DRIFT,
    "voltage_sensor_drift": FAULT_VOLTAGE_SENSOR_DRIFT,
    "temp_sensor_failure":  FAULT_TEMP_SENSOR_FAILURE,
    "loose_bolt":           FAULT_LOOSE_BOLT,
    "o2_blockage":          FAULT_O2_BLOCKAGE,
    "telemetry_dropout":    FAULT_TELEMETRY_DROPOUT,
    "over_pressure":        FAULT_OVER_PRESSURE,
}

# ── Physical constants ────────────────────────────────────────────────────────
FARADAY: float        = 96_485.332_12   # C/mol
R_GAS: float          = 8.314_462_618   # J/(mol·K)
U_REV: float          = 1.23            # V per cell  (reversible potential)
N_CELLS: int          = 5
# NOTE — Three-parameter regime (documented in scripts/validate_physics.py):
#   Simulation parameters (below) are intentionally scaled for fault-signature
#   diversity and training-data variety.  They do NOT represent a specific real cell.
#   Physics validation uses separately fitted reference parameters (R_OHM_REF=0.220 Ω,
#   I0_REF=0.010 A, I_LIM_REF=4.0 A) that reproduce published Monopoli et al. / NREL
#   polarisation curves to RMSE < 0.04 V, validating the *model structure*.
R_OHM: float          = 0.4             # Ω per cell  (simulation — scaled for fault diversity)
ALPHA: float          = 0.5             # charge-transfer coefficient (Butler-Volmer)
I0: float             = 1e-3            # exchange current density A  (simulation — scaled)
I_LIM: float          = 6.0             # A — limiting current density (simulation — scaled)
#   Reference-calibrated I_LIM_REF = 4.0 A (Koch et al. 2024 / Monopoli et al. 2024)
TANK_VOLUME_M3: float = 0.05            # 50 L
TANK_TEMP_K: float    = 298.15          # 25 °C
ATM_PA: float         = 101_325.0       # Pa
I_REF: float          = 1.8             # A desired stack current
V_MAX_PER_CELL: float = 2.2             # V safety trip threshold
WATER_FLOW_MIN: float = 0.5             # L/min safety threshold


# ── Helpers ───────────────────────────────────────────────────────────────────
def _activation_overpotential(i_stack: float) -> float:
    """Butler-Volmer activation overpotential (per cell).

    V_act = (RT / αF) × arcsinh(I / 2I₀)

    Captures the non-linear charge-transfer kinetics at the electrode surface.
    This term is responsible for the steep initial rise in the polarisation curve
    at low current densities and is absent from simple Ohmic-only models.
    """
    if i_stack <= 0.0:
        return 0.0
    return (R_GAS * TANK_TEMP_K / (ALPHA * FARADAY)) * math.asinh(i_stack / (2.0 * I0))


def _concentration_overpotential(i_stack: float, i_lim: float = I_LIM) -> float:
    """Nernst concentration (mass-transport) overpotential (per cell).

    V_conc = (RT / 2F) × ln(I_lim / (I_lim − I))

    At high current densities, mass-transport limitations at the membrane/electrode
    interface create a logarithmically diverging voltage penalty as I → I_lim.
    This term is significant above ~0.5 A/cm² and is necessary to reproduce the
    characteristic high-current knee in experimental PEM polarisation curves
    (Monopoli et al. 2024 [1]; Koch et al. 2024 [14]).

    Parameters
    ----------
    i_stack : float
        Stack current in Amperes.
    i_lim : float
        Limiting current density in Amperes.  Default is the simulation-scaled
        value; physics validation uses I_LIM_REF = 4.0 A.
    """
    if i_stack <= 0.0:
        return 0.0
    # Guard against approaching the limiting current (avoid ln(≤0))
    margin = max(i_lim - i_stack, 1e-6)
    return (R_GAS * TANK_TEMP_K / (2.0 * FARADAY)) * math.log(i_lim / margin)


# ── FaultInjector ─────────────────────────────────────────────────────────────
class FaultInjector:
    """Thread-safe registry of active fault IDs for one electrolyser."""

    def __init__(self) -> None:
        self._active: set[int] = set()
        self._lock = Lock()

    def set_fault(self, fault_name: str, active: bool = True) -> None:
        fid = FAULT_NAMES.get(fault_name)
        if fid is None:
            log.warning("Unknown fault: %s (ignored)", fault_name)
            return
        with self._lock:
            if active:
                self._active.add(fid)
                log.info("Fault ACTIVATED: %s", fault_name)
            else:
                self._active.discard(fid)
                log.info("Fault CLEARED:   %s", fault_name)

    def is_active(self, fault_id: int) -> bool:
        with self._lock:
            return fault_id in self._active

    def active_names(self) -> List[str]:
        with self._lock:
            return [k for k, v in FAULT_NAMES.items() if v in self._active]

    def clear_all(self) -> None:
        with self._lock:
            self._active.clear()


# ── MQTT helpers ──────────────────────────────────────────────────────────────
def _make_mqtt_client(
    cn: str,
    broker_host: str = "127.0.0.1",
    broker_port: int = 8883,
    client_id: Optional[str] = None,
) -> mqtt.Client:
    """Return a connected, loop-started MQTT client authenticated via X.509."""
    ca   = ROOT / "certs/ca/ca.crt"
    cert = ROOT / f"certs/clients/{cn}/client.crt"
    key  = ROOT / f"certs/clients/{cn}/client.key"

    c = mqtt.Client(client_id=client_id or cn, protocol=mqtt.MQTTv5)
    c.tls_set(
        ca_certs=str(ca),
        certfile=str(cert),
        keyfile=str(key),
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    c.tls_insecure_set(False)
    c.connect(broker_host, broker_port, keepalive=30)
    c.loop_start()
    return c


def _publish_json(client: mqtt.Client, topic: str, obj: dict) -> None:
    client.publish(topic, json.dumps(obj), qos=1)


# ── ElectrolyserTwin ──────────────────────────────────────────────────────────
class ElectrolyserTwin:
    """
    Software digital twin of a single PEM electrolyser stack.

    State variables are updated every timestep via update_from_pv().
    Telemetry is published via publish_all() using per-sensor MQTT clients.

    Physics
    -------
    V_stack = N × (U_rev + V_act + R_ohm × I)
      V_act = (RT/αF) × arcsinh(I / 2I₀)   ← Butler-Volmer activation term
    ṅ_H₂   = η_F × N × I / 2F
    P_tank  = n_H₂ × R × T / V_tank
    """

    #: Sensor names that require one MQTT client each
    SENSORS: List[Tuple[str, Optional[int]]] = [
        ("cell", 1), ("cell", 2), ("cell", 3), ("cell", 4), ("cell", 5),
        ("stack_current", None), ("stack_temperature", None),
        ("stack_pressure", None), ("h2_flow_rate", None),
        ("o2_flow_rate", None), ("tank_pressure", None), ("water_flow", None),
    ]

    def __init__(self, el_id: str) -> None:
        self.el = el_id
        self.N  = N_CELLS
        # Small manufacturing-tolerance variations
        self.U_rev = U_REV  * random.uniform(0.98, 1.02)
        self.R_ohm = R_OHM  * random.uniform(0.95, 1.05)
        self.eff_variation = random.uniform(0.95, 1.05)

        # State variables
        self.I_stack:          float = 0.0
        self.V_stack:          float = self.N * self.U_rev
        self.cell_voltages:    List[float] = [self.U_rev] * self.N
        self.stack_temp:       float = 45.0 + random.uniform(-1.0, 1.0)
        self.stack_pressure:   float = 1.2  + random.uniform(-0.05, 0.05)
        self.h2_flow_Lpm:      float = 0.0
        self.o2_flow_Lpm:      float = 0.0
        self.water_flow:       float = 1.2  * random.uniform(0.9, 1.1)
        self.tank_moles:       float = (ATM_PA * TANK_VOLUME_M3) / (R_GAS * TANK_TEMP_K)
        self.tank_pressure_pa: float = ATM_PA
        self.tank_pressure_bar: float = ATM_PA / 1e5

        self.tripped:      bool = False
        self.trip_reason:  Optional[str] = None
        self.fault_injector = FaultInjector()
        self.fault_timer:  float = 0.0
        self.seq:          int = 0

        self.clients: Dict[str, mqtt.Client] = {}

    # ── Connection management ─────────────────────────────────────────────
    def connect_clients(self, broker_host: str = "127.0.0.1", broker_port: int = 8883) -> None:
        for sensor_name, cell_no in self.SENSORS:
            cn = (
                f"sensor-{self.el}-cell_{cell_no}_voltage"
                if sensor_name == "cell"
                else f"sensor-{self.el}-{sensor_name}"
            )
            try:
                self.clients[cn] = _make_mqtt_client(cn, broker_host, broker_port)
            except Exception:
                log.exception("[%s] Failed to create MQTT client for %s", self.el, cn)

    def disconnect_clients(self) -> None:
        for cn, c in self.clients.items():
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:
                log.debug("[%s] disconnect skipped for %s", self.el, cn)

    # ── Physics update ────────────────────────────────────────────────────
    def update_from_pv(self, irradiance_wpm2: float, dt_seconds: float) -> None:
        """Step the digital twin forward by dt_seconds using the given irradiance."""
        # ── PV current availability ──────────────────────────────────────
        isc = 5.0 * (irradiance_wpm2 / 1000.0)          # A, scales linearly with irradiance
        pv_power = isc * 40.0 * 0.9                      # W, 10% derating
        V_stack_est = self.N * (self.U_rev + self.R_ohm * I_REF)
        I_target = I_REF if pv_power >= I_REF * V_stack_est else max(0.0, pv_power / V_stack_est)

        # First-order lag on current (τ = 2 s)
        self.I_stack += (I_target - self.I_stack) * min(1.0, dt_seconds / 2.0)

        # ── Stack voltage: activation + concentration + Ohmic ────────────
        v_act  = _activation_overpotential(self.I_stack)
        v_conc = _concentration_overpotential(self.I_stack)
        self.V_stack = self.N * (self.U_rev + v_act + v_conc + self.R_ohm * self.I_stack)
        per_cell = self.V_stack / self.N
        self.cell_voltages = [per_cell + random.uniform(-0.02, 0.02) for _ in range(self.N)]

        # ── Thermal model ────────────────────────────────────────────────
        self.stack_temp += (
            0.01 * (abs(self.I_stack) - 1.5) * (dt_seconds / 60.0)
            + random.uniform(-0.02, 0.02)
        )
        self.stack_pressure += random.uniform(-0.005, 0.005)

        # ── H₂ production (Faraday's law) ────────────────────────────────
        eta_F = 0.95 * self.eff_variation
        n_dot = eta_F * (self.N * self.I_stack) / (2.0 * FARADAY)   # mol/s
        V_molar_m3 = (R_GAS * TANK_TEMP_K) / ATM_PA
        self.h2_flow_Lpm = n_dot * V_molar_m3 * 1000.0 * 60.0
        self.o2_flow_Lpm = self.h2_flow_Lpm / 2.0 * 0.99

        # ── Tank pressure (ideal gas) ────────────────────────────────────
        self.tank_moles  += n_dot * dt_seconds * 0.9
        self.tank_pressure_pa  = (self.tank_moles * R_GAS * TANK_TEMP_K) / TANK_VOLUME_M3
        self.tank_pressure_bar = self.tank_pressure_pa / 1e5

        # Add sensor noise
        self.h2_flow_Lpm       *= random.uniform(0.97, 1.03)
        self.o2_flow_Lpm       *= random.uniform(0.97, 1.03)
        self.tank_pressure_bar *= random.uniform(0.995, 1.005)

        # Water flow scales with current
        self.water_flow = max(0.0, 1.2 * (self.I_stack / I_REF))

        # ── Fault injection ──────────────────────────────────────────────
        self.fault_timer += dt_seconds
        self._apply_faults(dt_seconds)

        # ── Safety checks ────────────────────────────────────────────────
        self._check_safety()

    def _apply_faults(self, dt_seconds: float) -> None:
        fi = self.fault_injector

        if fi.is_active(FAULT_MEMBRANE_PINHOLE):
            self.cell_voltages[0] += 0.5
            if self.N > 1:
                self.cell_voltages[1] += 0.4
            self.h2_flow_Lpm *= 1.2

        if fi.is_active(FAULT_GAS_CROSSOVER):
            self.o2_flow_Lpm = self.h2_flow_Lpm / 2.3

        if fi.is_active(FAULT_CELL_FLOODING):
            self.cell_voltages[2] = 1.35
            self.cell_voltages[3] = 1.38

        if fi.is_active(FAULT_CELL_DRYOUT):
            for i in range(self.N):
                self.cell_voltages[i] = max(self.cell_voltages[i], 2.25)
            self.stack_temp += 5.0 * dt_seconds

        if fi.is_active(FAULT_PUMP_FAILURE):
            self.water_flow = 0.0
            if self.I_stack > 10.0:
                self.stack_temp += 2.0 * dt_seconds

        if fi.is_active(FAULT_DCDC_FAILURE):
            self.I_stack = 0.0
            self.V_stack = self.N * U_REV
            self.cell_voltages = [self.V_stack / self.N] * self.N

        if fi.is_active(FAULT_SOLAR_TRANSIENT):
            if (self.fault_timer % 2.0) < 0.5:
                self.I_stack = 650.0

        if fi.is_active(FAULT_LEVEL_SENSOR):
            self.tank_pressure_bar += random.uniform(-2.0, 2.0)

        if fi.is_active(FAULT_VOLTAGE_SENSOR_DRIFT):
            self.cell_voltages[4] = 0.0

        if fi.is_active(FAULT_TEMP_SENSOR_FAILURE):
            self.stack_temp = 0.0

        if fi.is_active(FAULT_LOOSE_BOLT):
            self.I_stack *= 0.75
            self.V_stack = self.N * (self.U_rev + self.R_ohm * self.I_stack)
            self.cell_voltages = [self.V_stack / self.N] * self.N

        if fi.is_active(FAULT_O2_BLOCKAGE):
            self.o2_flow_Lpm *= 0.2
            self.stack_pressure += 0.5 * dt_seconds

        if fi.is_active(FAULT_OVER_PRESSURE):
            self.tank_pressure_bar = 40.0
            self.stack_pressure    = 40.0

    def _check_safety(self) -> None:
        per_cell = self.V_stack / self.N if self.N > 0 else 0.0
        if per_cell > V_MAX_PER_CELL:
            self.tripped, self.trip_reason = True, "over_voltage"
        if self.water_flow < WATER_FLOW_MIN:
            self.tripped, self.trip_reason = True, "low_water"
        if self.tank_pressure_bar > 30.0:
            self.tripped, self.trip_reason = True, "over_pressure"

    # ── Publish ───────────────────────────────────────────────────────────
    def publish_all(self) -> None:
        """Publish all sensor readings to their respective MQTT topics."""
        if self.fault_injector.is_active(FAULT_TELEMETRY_DROPOUT):
            log.debug("[%s] Telemetry dropout active — skipping publish", self.el)
            return

        ts = time.time()
        plant = "plant-A"

        def _pub(cn: str, topic: str, payload: dict) -> None:
            client = self.clients.get(cn)
            if client:
                _publish_json(client, topic, payload)
            else:
                log.debug("No client for %s", cn)

        # Cell voltages
        for i, v in enumerate(self.cell_voltages, start=1):
            _pub(
                f"sensor-{self.el}-cell_{i}_voltage",
                f"electrolyser/{plant}/{self.el}/cell/{i}/voltage",
                {"el": self.el, "sensor": f"cell_{i}_voltage", "cell": i,
                 "unit": "V", "timestamp": ts, "value": round(v, 4), "sequence_id": self.seq},
            )

        # Stack-level sensors
        stack_readings = [
            ("stack_current",     "stack/current",      "A",   self.I_stack),
            ("stack_temperature", "stack/temperature",  "C",   self.stack_temp),
            ("stack_pressure",    "stack/pressure",     "bar", self.stack_pressure),
        ]
        for sensor_name, path, unit, val in stack_readings:
            _pub(
                f"sensor-{self.el}-{sensor_name}",
                f"electrolyser/{plant}/{self.el}/{path}",
                {"el": self.el, "sensor": sensor_name, "unit": unit,
                 "timestamp": ts, "value": round(val, 3), "sequence_id": self.seq},
            )

        # Gas flow sensors
        for sensor_name, gas, val in [
            ("h2_flow_rate", "h2", self.h2_flow_Lpm),
            ("o2_flow_rate", "o2", self.o2_flow_Lpm),
        ]:
            _pub(
                f"sensor-{self.el}-{sensor_name}",
                f"electrolyser/{plant}/{self.el}/{gas}/flow_rate",
                {"el": self.el, "sensor": sensor_name, "unit": "L/min",
                 "timestamp": ts, "value": round(val, 4), "sequence_id": self.seq},
            )

        # Tank pressure
        _pub(
            f"sensor-{self.el}-tank_pressure",
            f"electrolyser/{plant}/{self.el}/tank/pressure",
            {"el": self.el, "sensor": "tank_pressure", "unit": "bar",
             "timestamp": ts, "value": round(self.tank_pressure_bar, 4), "sequence_id": self.seq},
        )

        # Water flow
        _pub(
            f"sensor-{self.el}-water_flow",
            f"electrolyser/{plant}/{self.el}/water_flow",
            {"el": self.el, "sensor": "water_flow", "unit": "L/min",
             "timestamp": ts, "value": round(self.water_flow, 3), "sequence_id": self.seq},
        )

        # Status
        status_cn = f"sensor-{self.el}-stack_current"
        active_faults = self.fault_injector.active_names()
        _pub(
            status_cn,
            f"electrolyser/{plant}/{self.el}/status",
            {k: v for k, v in {
                "el": self.el, "timestamp": ts,
                "status": "TRIPPED" if self.tripped else "OPERATIONAL",
                "reason": self.trip_reason if self.tripped else None,
                "active_faults": active_faults if active_faults else None,
                "sequence_id": self.seq,
            }.items() if v is not None},
        )

        self.seq += 1


# ── PlantSimulator ────────────────────────────────────────────────────────────
class PlantSimulator:
    """
    Orchestrates two ElectrolyserTwin instances plus shared irradiance sensors.

    Control messages (fault injection / clearing) are received via MQTT on
    topic ``electrolyser/control/faults`` and dispatched to the target twin.
    """

    def __init__(self, dt: float = 1.0, broker_host: str = "127.0.0.1", broker_port: int = 8883) -> None:
        self.dt          = dt
        self.broker_host = broker_host
        self.broker_port = broker_port

        self.electrolysers: Dict[str, ElectrolyserTwin] = {
            "EL1": ElectrolyserTwin("EL1"),
            "EL2": ElectrolyserTwin("EL2"),
        }
        self.irradiance: Dict[int, float] = {1: 800.0, 2: 750.0}
        self.irr_clients: Dict[int, mqtt.Client] = {}
        self.stop_event = Event()
        self.t: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────
    def connect_all(self) -> None:
        """Connect every per-sensor and monitor MQTT client."""
        for el in self.electrolysers.values():
            el.connect_clients(self.broker_host, self.broker_port)
            try:
                mon = _make_mqtt_client(
                    "monitor-local", self.broker_host, self.broker_port,
                    client_id=f"monitor-local-{el.el}",
                )
                el.clients["monitor-local"] = mon
            except Exception:
                log.warning("[%s] monitor-local client unavailable", el.el)

        # Fault control subscriber
        try:
            ctrl = _make_mqtt_client(
                "monitor-local", self.broker_host, self.broker_port,
                client_id="plant-sim-control",
            )
            ctrl.on_message = self.on_control_message
            ctrl.subscribe("electrolyser/control/faults")
            self.control_client = ctrl
            log.info("Control listener subscribed to electrolyser/control/faults")
        except Exception:
            log.exception("Could not create control client")

        # Irradiance sensor clients
        for i in (1, 2):
            cn = f"sensor-plant-A-irradiance_{i}"
            try:
                self.irr_clients[i] = _make_mqtt_client(cn, self.broker_host, self.broker_port)
            except Exception:
                log.exception("Irradiance client %s failed", cn)

    def disconnect_all(self) -> None:
        for el in self.electrolysers.values():
            el.disconnect_clients()
        for c in self.irr_clients.values():
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:
                pass
        if hasattr(self, "control_client"):
            try:
                self.control_client.loop_stop()
                self.control_client.disconnect()
            except Exception:
                pass

    # ── Irradiance ────────────────────────────────────────────────────────
    def update_irradiance(self, dt: float) -> None:
        """Sinusoidal day-cycle (10-minute accelerated day) with random clouds."""
        self.t += dt
        base = 500.0 + 500.0 * max(0.0, math.sin(2.0 * math.pi * (self.t / 600.0)))
        self.irradiance[1] = max(0.0, base + random.uniform(-80, 80))
        self.irradiance[2] = max(0.0, base * 0.95 + random.uniform(-80, 80))

        if self.electrolysers["EL1"].fault_injector.is_active(FAULT_IRRADIANCE_DRIFT):
            self.irradiance[1] += 300.0

    def publish_irradiance(self) -> None:
        ts = time.time()
        for i, c in self.irr_clients.items():
            _publish_json(c, f"electrolyser/plant-A/irradiance/{i}", {
                "el": "PLANT", "sensor": f"irradiance_{i}", "unit": "W/m2",
                "timestamp": ts, "value": round(self.irradiance[i], 2),
                "sequence_id": int(self.t),
            })

    # ── Fault control ─────────────────────────────────────────────────────
    def on_control_message(
        self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage
    ) -> None:
        """Handle incoming fault control messages.

        Expected JSON: ``{"el": "EL1", "fault": "membrane_pinhole", "active": true}``
        """
        try:
            payload = json.loads(msg.payload)
            el_id   = payload.get("el")
            fault   = payload.get("fault")
            active  = payload.get("active", True)

            if el_id in self.electrolysers:
                self.electrolysers[el_id].fault_injector.set_fault(fault, active)
            elif el_id == "PLANT":
                for el in self.electrolysers.values():
                    el.fault_injector.set_fault(fault, active)
            else:
                log.warning("Control message: unknown el_id '%s'", el_id)
        except (json.JSONDecodeError, KeyError) as exc:
            log.error("Malformed control message: %s — %s", msg.payload, exc)

    # ── Main loop ─────────────────────────────────────────────────────────
    def run_loop(self) -> None:
        log.info("Plant simulator starting — connecting to broker %s:%d",
                 self.broker_host, self.broker_port)
        self.connect_all()
        log.info("All device clients connected.")

        try:
            last = time.time()
            while not self.stop_event.is_set():
                now = time.time()
                dt  = max(now - last, self.dt)
                last = now

                self.update_irradiance(dt)
                self.publish_irradiance()

                for idx, el in enumerate(self.electrolysers.values(), start=1):
                    irr = self.irradiance[1] if idx == 1 else self.irradiance[2]
                    el.update_from_pv(irr, dt)
                    el.publish_all()

                time.sleep(self.dt)
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt — shutting down.")
        finally:
            self.disconnect_all()
            log.info("All clients disconnected.")

    def stop(self) -> None:
        self.stop_event.set()


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Electrolyser digital-twin plant simulator")
    parser.add_argument("--dt",     type=float, default=1.0,       help="Simulation timestep in seconds (default 1.0)")
    parser.add_argument("--broker", type=str,   default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port",   type=int,   default=8883,       help="MQTT TLS port")
    args = parser.parse_args()

    sim = PlantSimulator(dt=args.dt, broker_host=args.broker, broker_port=args.port)
    sim.run_loop()


if __name__ == "__main__":
    main()
