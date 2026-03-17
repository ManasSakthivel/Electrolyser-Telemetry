#!/usr/bin/env python3
"""
plant_sim.py
Professional digital twin for two-electrolyser plant (EL1, EL2) + 2 irradiance sensors.

Features:
- PV irradiance day-cycle (sine) + optional random weather events
- Buck converter "controller" that aims to drive a reference current (I_ref) while keeping V_stack <= V_max
- Electrolyser stack simplified model: V_stack = N*(U_rev + R_ohm * I_stack)
- H2 production via Faraday's law; integrator -> tank pressure using ideal gas law
- Per-device MQTT connections using existing certs/clients CN directories
- Publishes sensor JSON payloads to topics:
  electrolyser/plant-A/ELx/cell/<n>/voltage
  electrolyser/plant-A/ELx/stack/current
  electrolyser/plant-A/ELx/stack/temperature
  electrolyser/plant-A/ELx/stack/pressure
  electrolyser/plant-A/ELx/h2/flow_rate
  electrolyser/plant-A/ELx/o2/flow_rate
  electrolyser/plant-A/ELx/tank/pressure
  electrolyser/plant-A/ELx/water_flow
  electrolyser/plant-A/ELx/...
  electrolyser/plant-A/irradiance/1, /2
- Safety rules and trip events published to electrolyser/plant-A/<EL>/status

Run:
  python3 clients/python/plant_sim.py
"""

import math
import time
import json
import ssl
import pathlib
import random
import argparse
from threading import Thread, Event, Lock
from paho.mqtt import client as mqtt

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Fault Definitions
FAULT_NONE = 0
FAULT_MEMBRANE_PINHOLE = 1
FAULT_GAS_CROSSOVER = 2
FAULT_CELL_FLOODING = 3
FAULT_CELL_DRYOUT = 4
FAULT_PUMP_FAILURE = 5
FAULT_DCDC_FAILURE = 6
FAULT_SOLAR_TRANSIENT = 7
FAULT_LEVEL_SENSOR = 8
FAULT_IRRADIANCE_DRIFT = 9
FAULT_VOLTAGE_SENSOR_DRIFT = 10
FAULT_TEMP_SENSOR_FAILURE = 11
FAULT_LOOSE_BOLT = 12
FAULT_O2_BLOCKAGE = 13
FAULT_TELEMETRY_DROPOUT = 14
FAULT_OVER_PRESSURE = 15

FAULT_NAMES = {
    "none": FAULT_NONE,
    "membrane_pinhole": FAULT_MEMBRANE_PINHOLE,
    "gas_crossover": FAULT_GAS_CROSSOVER,
    "cell_flooding": FAULT_CELL_FLOODING,
    "cell_dryout": FAULT_CELL_DRYOUT,
    "pump_failure": FAULT_PUMP_FAILURE,
    "dcdc_failure": FAULT_DCDC_FAILURE,
    "solar_transient": FAULT_SOLAR_TRANSIENT,
    "level_sensor": FAULT_LEVEL_SENSOR,
    "irradiance_drift": FAULT_IRRADIANCE_DRIFT,
    "voltage_sensor_drift": FAULT_VOLTAGE_SENSOR_DRIFT,
    "temp_sensor_failure": FAULT_TEMP_SENSOR_FAILURE,
    "loose_bolt": FAULT_LOOSE_BOLT,
    "o2_blockage": FAULT_O2_BLOCKAGE,
    "telemetry_dropout": FAULT_TELEMETRY_DROPOUT,
    "over_pressure": FAULT_OVER_PRESSURE
}

class FaultInjector:
    def __init__(self):
        self.active_faults = set()
        self.lock = Lock()
        self.params = {} # Store fault-specific params if needed

    def set_fault(self, fault_name, active=True):
        fid = FAULT_NAMES.get(fault_name)
        if fid is None:
            print(f"Unknown fault: {fault_name}")
            return
        with self.lock:
            if active:
                self.active_faults.add(fid)
                print(f"Fault activated: {fault_name}")
            else:
                self.active_faults.discard(fid)
                print(f"Fault cleared: {fault_name}")

    def is_active(self, fault_id):
        with self.lock:
            return fault_id in self.active_faults

    def clear_all(self):
        with self.lock:
            self.active_faults.clear()

# Constants (tweakable)
FARADAY = 96485.33212  # C/mol
U_REV = 1.23  # V per cell
N_CELLS = 5
R_OHM = 0.4  # ohm per cell (tweak to match V~2.0 at I~1.8A)
TANK_VOLUME_M3 = 0.05  # 50 liters = 0.05 m3 (example)
TANK_TEMPERATURE_K = 298.15  # 25 °C
R_GAS = 8.31446261815324  # J/(mol·K)
H2_MOLAR_MASS = 2.01588  # g/mol (not used directly)
ATM_PRESSURE_PA = 101325.0  # Pa

# default control params
I_REF = 1.8  # desired stack current A (can be scaled by PV availability)
V_MAX_PER_CELL = 2.2  # trip if per-cell > this
WATER_FLOW_MIN = 0.5  # L/min

# mapping of sensors (same as your topic layout)
SENSORS_PER_EL = [
    ("cell", 1),
    ("cell", 2),
    ("cell", 3),
    ("cell", 4),
    ("cell", 5),
    ("stack_current", None),
    ("stack_temperature", None),
    ("stack_pressure", None),
    ("h2_flow_rate", None),
    ("o2_flow_rate", None),
    ("tank_pressure", None),
    ("water_flow", None),
]

# MQTT helper: create a client for each CN
def make_mqtt_client(cn: str, broker_host="127.0.0.1", broker_port=8883, client_id=None):
    ca = ROOT / "certs/ca/ca.crt"
    cert = ROOT / f"certs/clients/{cn}/client.crt"
    key = ROOT / f"certs/clients/{cn}/client.key"

    if client_id is None:
        client_id = cn
    
    client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv5)
    client.tls_set(ca_certs=str(ca), certfile=str(cert), keyfile=str(key),
                   tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.tls_insecure_set(False)
    client.connect(broker_host, broker_port, keepalive=30)
    client.loop_start()
    return client

# helper: publish a JSON payload with qos=1
def publish_json(client, topic, obj):
    payload = json.dumps(obj)
    client.publish(topic, payload, qos=1)

class ElectrolyserTwin:
    def __init__(self, el_id, cert_cn_prefix="sensor", initial_irradiance=800.0):
        self.el = el_id  # "EL1" or "EL2" or "PLANT"
        self.cell_count = N_CELLS
        self.N = N_CELLS
        self.U_rev = U_REV * random.uniform(0.98, 1.02)
        self.R_ohm = R_OHM * random.uniform(0.95, 1.05)
        self.I_stack = 0.0
        self.V_stack = self.N * (self.U_rev + self.R_ohm * 0.0)
        self.cell_voltages = [self.V_stack / self.N] * self.N
        self.stack_temp = 45.0 + random.uniform(-1.0, 1.0)
        self.stack_pressure = 1.2 + random.uniform(-0.05, 0.05)
        self.h2_flow_Lpm = 0.0
        self.o2_flow_Lpm = 0.0
        self.water_flow = 1.2 * random.uniform(0.9, 1.1)
        self.eff_variation = random.uniform(0.95, 1.05)
        self.tank_moles = 0.0  # moles in tank
        # start with ambient or small pressure
        self.tank_pressure_pa = ATM_PRESSURE_PA
        self.cert_prefix = cert_cn_prefix
        self.clients = {}  # per-device mqtt clients keyed by CN
        self.seq = 0
        # state flags
        self.tripped = False
        self.trip_reason = None
        
        self.fault_injector = FaultInjector()
        self.fault_timer = 0.0 # For time-based fault effects

        # compute initial tank moles from pressure using ideal gas (n = PV/RT)
        self.tank_moles = (self.tank_pressure_pa * TANK_VOLUME_M3) / (R_GAS * TANK_TEMPERATURE_K)

    def connect_clients(self, broker_host="127.0.0.1", broker_port=8883):
        # create a client for each sensor CN (one per sensor type)
        # CN naming MUST match your cert dir names
        for sensor_name, cell_no in SENSORS_PER_EL:
            # build CN
            if sensor_name == "cell":
                cn = f"sensor-{self.el}-cell_{cell_no}_voltage"
            else:
                cn = f"sensor-{self.el}-{sensor_name}"
            try:
                c = make_mqtt_client(cn, broker_host=broker_host, broker_port=broker_port)
                self.clients[cn] = c
            except Exception as e:
                print(f"[{self.el}] Error creating client {cn}: {e}")

    def disconnect_clients(self):
        for c in self.clients.values():
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:
                pass

    def update_from_pv(self, irradiance_wpm2, dt_seconds):
        """
        Determine available PV power roughly proportional to irradiance.
        Then run a simple control:
         - if PV available power >= required (I_ref * V_stack) run CC to I_ref
         - else reduce current proportionally
        Also simulate small PV coupling losses.
        """
        # PV model: current capability scales with irradiance
        # Simplified: I_sc scales linearly to irradiance; assume panel array short-circuit ~5A@1000W/m2
        panel_isc_per_panel = 5.0  # A at 1000 W/m2
        isc = panel_isc_per_panel * (irradiance_wpm2 / 1000.0)
        # assume usable PV voltage around 40V and we step-down to 10V, so available power:
        pv_voltage = 40.0
        pv_power = isc * pv_voltage * 0.9  # derate 10%
        # required stack power for I_ref
        # compute V_stack for last known I (approx)
        V_stack_est = self.N * (self.U_rev + self.R_ohm * I_REF)
        required_power = I_REF * V_stack_est

        # control decision
        if pv_power >= required_power:
            # enough PV — set current to reference (but guard by voltage limit)
            I_target = I_REF
        else:
            # scale current proportionally to available power
            if V_stack_est > 0.01:
                I_target = max(0.0, pv_power / V_stack_est)
            else:
                I_target = 0.0

        # simple first-order approach to change I_stack towards I_target
        tau = 2.0
        self.I_stack += (I_target - self.I_stack) * min(1.0, dt_seconds / tau)

        # compute V_stack
        self.V_stack = self.N * (self.U_rev + self.R_ohm * self.I_stack)
        # update cell voltages
        per_cell = self.V_stack / self.N
        self.cell_voltages = [per_cell + random.uniform(-0.02, 0.02) for _ in range(self.N)]

        # temperature rises slightly with current
        self.stack_temp += 0.01 * (abs(self.I_stack) - 1.5) * (dt_seconds / 60.0) + random.uniform(-0.02, 0.02)
        # stack pressure small random drift
        self.stack_pressure += random.uniform(-0.005, 0.005)

        # H2 production via Faraday: molar flow (mol/s)
        eta_F = 0.95 * self.eff_variation
        n_dot = eta_F * (self.N * self.I_stack) / (2.0 * FARADAY)  # mol/s
        # Convert mol/s to L/min at conditions: V_molar (m3/mol) = RT/P; convert to liters
        V_molar_m3 = (R_GAS * TANK_TEMPERATURE_K) / (ATM_PRESSURE_PA)
        # flow in liters per minute
        flow_m3_per_s = n_dot * V_molar_m3
        self.h2_flow_Lpm = flow_m3_per_s * 1000.0 * 60.0

        # oxygen is roughly stoichiometric (half molar to H2)
        self.o2_flow_Lpm = self.h2_flow_Lpm / 2.0 * 0.99  # small inefficiency

        # integrate tank moles (assume some fraction of H2 goes to tank)
        # convert mol/s (n_dot) to mol per dt
        mol_added = n_dot * dt_seconds  # mol added during dt
        # assume fraction f_capture goes to tank (some released to vent, leaks)
        f_capture = 0.9
        self.tank_moles += mol_added * f_capture

        # recompute tank pressure (ideal gas)
        self.tank_pressure_pa = (self.tank_moles * R_GAS * TANK_TEMPERATURE_K) / TANK_VOLUME_M3

        # convert tank pressure to bar for telemetry
        self.tank_pressure_bar = self.tank_pressure_pa / 1e5

        # Add noise to flows & pressure
        self.h2_flow_Lpm *= random.uniform(0.97, 1.03)
        self.o2_flow_Lpm *= random.uniform(0.97, 1.03)
        self.tank_pressure_bar *= random.uniform(0.995, 1.005)

        # water flow: if PV insufficient, reduce water pump duty
        self.water_flow = max(0.0, 1.2 * (self.I_stack / I_REF))

        # --- FAULT INJECTION LOGIC ---
        self.fault_timer += dt_seconds
        
        # 1. Membrane pinhole
        if self.fault_injector.is_active(FAULT_MEMBRANE_PINHOLE):
            # One or two cell voltages jump 300–800 mV higher
            # H2 flow rate becomes higher than expected (simulated by boosting flow calc)
            self.cell_voltages[0] += 0.5 
            if self.N > 1: self.cell_voltages[1] += 0.4
            self.h2_flow_Lpm *= 1.2

        # 2. Gas crossover
        if self.fault_injector.is_active(FAULT_GAS_CROSSOVER):
            # H2/O2 flow ratio deviation (>2.1 or <1.9)
            # Normal is ~2.0. Let's make it 2.3
            self.o2_flow_Lpm = self.h2_flow_Lpm / 2.3

        # 3. Cell flooding
        if self.fault_injector.is_active(FAULT_CELL_FLOODING):
            # One or more cells drop to <1.4 V, high cell-to-cell spread
            self.cell_voltages[2] = 1.35
            self.cell_voltages[3] = 1.38
            # Others normal-ish

        # 4. Cell dry-out
        if self.fault_injector.is_active(FAULT_CELL_DRYOUT):
            # All cells climb >2.2 V, temp rising
            for i in range(self.N):
                self.cell_voltages[i] = max(self.cell_voltages[i], 2.25)
            self.stack_temp += 5.0 * dt_seconds # Fast rise

        # 5. Water pump failure
        if self.fault_injector.is_active(FAULT_PUMP_FAILURE):
            self.water_flow = 0.0
            # Temp rises fast if current is high
            if self.I_stack > 10.0:
                self.stack_temp += 2.0 * dt_seconds

        # 6. DC-DC converter / MPPT failure
        if self.fault_injector.is_active(FAULT_DCDC_FAILURE):
            self.I_stack = 0.0
            self.V_stack = self.N * U_REV # Open circuit voltage approx
            self.cell_voltages = [self.V_stack / self.N] * self.N

        # 7. Sudden solar transient damage
        if self.fault_injector.is_active(FAULT_SOLAR_TRANSIENT):
            # Spikes > 600 A for < 1 s repeatedly
            if (self.fault_timer % 2.0) < 0.5:
                self.I_stack = 650.0
            # This would likely trip safety immediately, but we simulate the value first

        # 8. Gas separator liquid level too high/low
        if self.fault_injector.is_active(FAULT_LEVEL_SENSOR):
            # tank_pressure erratic
            noise = random.uniform(-2.0, 2.0)
            self.tank_pressure_bar += noise

        # 9. Irradiance sensor drift (Handled in PlantSimulator or here if local)
        # 10. Individual cell voltage sensor drift
        if self.fault_injector.is_active(FAULT_VOLTAGE_SENSOR_DRIFT):
            self.cell_voltages[4] = 0.000 # Stuck at 0

        # 11. Stack temperature sensor failure
        if self.fault_injector.is_active(FAULT_TEMP_SENSOR_FAILURE):
            self.stack_temp = 0.0

        # 12. Loose or corroded high-current bolt
        if self.fault_injector.is_active(FAULT_LOOSE_BOLT):
            # 20-30% lower current than expected
            self.I_stack *= 0.75
            # Recalculate V_stack based on new I
            self.V_stack = self.N * (self.U_rev + self.R_ohm * self.I_stack)
            self.cell_voltages = [self.V_stack / self.N] * self.N

        # 13. O2-side blockage
        if self.fault_injector.is_active(FAULT_O2_BLOCKAGE):
            self.o2_flow_Lpm *= 0.2
            # Pressure rises? (Simulated locally)
            self.stack_pressure += 0.5 * dt_seconds

        # 14. MQTT / telemetry dropout (Handled in publish_all)
        
        # 15. Over-pressure event
        if self.fault_injector.is_active(FAULT_OVER_PRESSURE):
            self.tank_pressure_bar = 40.0 # Instant spike
            self.stack_pressure = 40.0

        # --- END FAULT INJECTION ---

        # safety checks
        self.check_safety()

    def check_safety(self):
        # over voltage per cell -> trip
        per_cell = self.V_stack / self.N
        if per_cell > V_MAX_PER_CELL:
            self.tripped = True
            self.trip_reason = "over_voltage"
        if self.water_flow < WATER_FLOW_MIN:
            self.tripped = True
            self.trip_reason = "low_water"
        # overpressure
        if self.tank_pressure_bar > 30.0:
            self.tripped = True
            self.trip_reason = "over_pressure"

    def publish_all(self):
        # 14. MQTT / telemetry dropout
        if self.fault_injector.is_active(FAULT_TELEMETRY_DROPOUT):
            return # Do not publish anything

        # publish per-sensor payloads using the clients dict
        ts = time.time()
        # cell voltages
        for i, v in enumerate(self.cell_voltages, start=1):
            cn = f"sensor-{self.el}-cell_{i}_voltage"
            client = self.clients.get(cn)
            if client:
                topic = f"electrolyser/plant-A/{self.el}/cell/{i}/voltage"
                payload = {
                    "el": self.el,
                    "sensor": f"cell_{i}_voltage",
                    "cell": i,
                    "unit": "V",
                    "timestamp": ts,
                    "value": round(v, 4),
                    "sequence_id": self.seq
                }
                publish_json(client, topic, payload)
        # stack current
        cn = f"sensor-{self.el}-stack_current"
        client = self.clients.get(cn)
        if client:
            topic = f"electrolyser/plant-A/{self.el}/stack/current"
            payload = {"el": self.el, "sensor": "stack_current", "unit": "A", "timestamp": ts, "value": round(self.I_stack, 4), "sequence_id": self.seq}
            publish_json(client, topic, payload)
        # stack temp/pressure
        for name, val in [("stack_temperature", self.stack_temp), ("stack_pressure", self.stack_pressure)]:
            cn = f"sensor-{self.el}-{name}"
            client = self.clients.get(cn)
            if client:
                topic = f"electrolyser/plant-A/{self.el}/stack/{name.split('_')[-1]}"
                payload = {"el": self.el, "sensor": name, "unit": "C" if "temp" in name else "bar", "timestamp": ts, "value": round(val, 3), "sequence_id": self.seq}
                publish_json(client, topic, payload)
        # gas flows
        for name, val, unit in [("h2_flow_rate", self.h2_flow_Lpm, "L/min"), ("o2_flow_rate", self.o2_flow_Lpm, "L/min")]:
            cn = f"sensor-{self.el}-{name}"
            client = self.clients.get(cn)
            if client:
                topic = f"electrolyser/plant-A/{self.el}/{ 'h2' if name.startswith('h2') else 'o2'}/flow_rate"
                payload = {"el": self.el, "sensor": name, "unit": "L/min", "timestamp": ts, "value": round(val, 4), "sequence_id": self.seq}
                publish_json(client, topic, payload)
        # tank pressure
        cn = f"sensor-{self.el}-tank_pressure"
        client = self.clients.get(cn)
        if client:
            topic = f"electrolyser/plant-A/{self.el}/tank/pressure"
            payload = {"el": self.el, "sensor": "tank_pressure", "unit": "bar", "timestamp": ts, "value": round(self.tank_pressure_bar, 4), "sequence_id": self.seq}
            publish_json(client, topic, payload)
        # water_flow
        cn = f"sensor-{self.el}-water_flow"
        client = self.clients.get(cn)
        if client:
            topic = f"electrolyser/plant-A/{self.el}/water_flow"
            payload = {"el": self.el, "sensor": "water_flow", "unit": "L/min", "timestamp": ts, "value": round(self.water_flow, 3), "sequence_id": self.seq}
            publish_json(client, topic, payload)

        # publish status topic
        cn = f"monitor-local"
        mon_client = self.clients.get(cn)
        # We do NOT require monitor-local for per-EL status here; instead publish status via the EL stack_current client to a status topic
        status_cn = f"sensor-{self.el}-stack_current"
        status_client = self.clients.get(status_cn)
        if status_client:
            status_topic = f"electrolyser/plant-A/{self.el}/status"
            status_payload = {
                "el": self.el,
                "timestamp": ts,
                "status": "TRIPPED" if self.tripped else "OPERATIONAL",
                "reason": self.trip_reason if self.tripped else None,
                "sequence_id": self.seq
            }
            # prune None fields
            status_payload = {k: v for k, v in status_payload.items() if v is not None}
            publish_json(status_client, status_topic, status_payload)

        self.seq += 1

class PlantSimulator:
    def __init__(self, dt=1.0, broker_host="127.0.0.1", broker_port=8883):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.dt = dt
        self.electrolysers = {
            "EL1": ElectrolyserTwin("EL1"),
            "EL2": ElectrolyserTwin("EL2")
        }
        # separate two irradiance sensors
        self.irradiance = {1: 800.0, 2: 750.0}
        self.irr_clients = {}
        self.stop_event = Event()
        # global time-of-day phase for sine irradiance
        self.t = 0.0

    def connect_all(self):
        # connect electrolyser device clients (pass broker args through)
        # connect electrolyser device clients (pass broker args through)
        for el in self.electrolysers.values():
            el.connect_clients(broker_host=self.broker_host, broker_port=self.broker_port)
            # also create a "monitor-local" client mapping to existing cert monitor-local if present
            try:
                # Use unique client ID to avoid conflicts
                mon = make_mqtt_client("monitor-local", broker_host=self.broker_host, broker_port=self.broker_port, client_id=f"monitor-local-{el.el}")
                el.clients["monitor-local"] = mon
            except Exception:
                pass
        
        # Connect control listener for faults
        try:
            # Use monitor-local certs but unique client ID
            ctrl = make_mqtt_client("monitor-local", broker_host=self.broker_host, broker_port=self.broker_port, client_id="plant-sim-control")
            ctrl.on_message = self.on_control_message
            ctrl.subscribe("electrolyser/control/faults")
            self.control_client = ctrl
        except Exception as e:
            print(f"Control client error: {e}")

        # create irradiance sensor clients
        for i in (1, 2):
            cn = f"sensor-plant-A-irradiance_{i}"
            try:
                c = make_mqtt_client(cn, broker_host=self.broker_host, broker_port=self.broker_port)
                self.irr_clients[i] = c
            except Exception as e:
                print("Irr client error", e)

    def disconnect_all(self):
        for el in self.electrolysers.values():
            el.disconnect_clients()
        for c in self.irr_clients.values():
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:
                pass
        if hasattr(self, 'control_client'):
            self.control_client.loop_stop()
            self.control_client.disconnect()

    def update_irradiance(self, dt):
        # a daily sine cycle (period 24*60*60 seconds scaled down)
        # use a fast cycle for testing (period 600 seconds -> simulate a day fast)
        day_period = 600.0
        self.t += dt
        base = 500.0 + 500.0 * max(0.0, math.sin(2.0 * math.pi * (self.t / day_period)))
        # small random fluctuation
        self.irradiance[1] = max(0.0, base + random.uniform(-80, 80))
        self.irradiance[2] = max(0.0, base * 0.95 + random.uniform(-80, 80))

        # 9. Irradiance sensor drift
        # We need a way to know if this fault is active. 
        # Since faults are per-EL, we can check EL1's injector for global faults or just pick one.
        # Let's assume if EL1 has FAULT_IRRADIANCE_DRIFT, we drift sensor 1
        if self.electrolysers["EL1"].fault_injector.is_active(FAULT_IRRADIANCE_DRIFT):
             self.irradiance[1] += 300.0 # Diverge > 200

    def publish_irradiance(self):
        ts = time.time()
        for i, c in self.irr_clients.items():
            payload = {"el": "PLANT", "sensor": f"irradiance_{i}", "unit": "W/m2", "timestamp": ts, "value": round(self.irradiance[i], 2), "sequence_id": int(self.t)}
            topic = f"electrolyser/plant-A/irradiance/{i}"
            publish_json(c, topic, payload)

    def on_control_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload)
            # Format: {"el": "EL1", "fault": "membrane_pinhole", "active": true}
            el_id = payload.get("el")
            fault = payload.get("fault")
            active = payload.get("active", True)
            
            if el_id in self.electrolysers:
                self.electrolysers[el_id].fault_injector.set_fault(fault, active)
            elif el_id == "PLANT":
                # Apply to all or specific plant sensors
                # For now apply to EL1 for simplicity if it's a plant-wide thing that affects EL1 logic
                # Or iterate all
                for el in self.electrolysers.values():
                    el.fault_injector.set_fault(fault, active)
            else:
                print(f"Unknown EL ID in control msg: {el_id}")
        except Exception as e:
            print(f"Error parsing control msg: {e}")

    def run_loop(self):
        print("Plant simulator starting, connecting to broker...")
        self.connect_all()
        print("Connected clients for all devices.")
        try:
            last = time.time()
            while not self.stop_event.is_set():
                now = time.time()
                dt = now - last
                if dt <= 0:
                    dt = self.dt
                last = now

                # update irradiance (fast-day)
                self.update_irradiance(dt)
                self.publish_irradiance()

                # update each electrolyser with irradiance (we give each same plant-level irradiance for simplicity)
                for idx, el in enumerate(self.electrolysers.values(), start=1):
                    # optionally vary irradiance slightly per electrolyser
                    irr = self.irradiance[1] if idx == 1 else self.irradiance[2]
                    el.update_from_pv(irr, dt)
                    el.publish_all()

                time.sleep(self.dt)
        except KeyboardInterrupt:
            print("Stopping plant simulator (KeyboardInterrupt)")
        finally:
            self.disconnect_all()
            print("Disconnected all clients.")

    def stop(self):
        self.stop_event.set()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dt", type=float, default=1.0, help="simulation timestep (s)")
    parser.add_argument("--broker", default="127.0.0.1", help="MQTT broker host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8883, help="MQTT broker port")
    args = parser.parse_args()

    sim = PlantSimulator(dt=args.dt, broker_host=args.broker, broker_port=args.port)
    sim.run_loop()

if __name__ == "__main__":
    main()
