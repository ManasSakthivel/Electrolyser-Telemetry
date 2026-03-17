"""
Telemetry Publisher Module
Handles MQTT publishing of simulation data
"""

import json
import ssl
import time
import logging
import pathlib
from typing import Dict, Optional
from paho.mqtt import client as mqtt

from .simulation_engine import ElectrolyserState

logger = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TelemetryPublisher:
    """
    Publishes electrolyser telemetry data to MQTT broker
    Decoupled from simulation logic
    """
    
    def __init__(self, el_id: str, config: Dict, cert_prefix: str = "sensor"):
        """
        Initialize telemetry publisher
        
        Args:
            el_id: Electrolyser ID (e.g., 'EL1', 'EL2')
            config: MQTT configuration dictionary
            cert_prefix: Prefix for certificate directory names
        """
        self.el_id = el_id
        self.config = config
        self.cert_prefix = cert_prefix
        self.clients: Dict[str, mqtt.Client] = {}
        self.topic_prefix = config.get('topic_prefix', 'electrolyser/plant-A')
        
        logger.info(f"TelemetryPublisher initialized for {el_id}")
    
    def connect_clients(self, n_cells: int):
        """
        Create and connect MQTT clients for each sensor
        
        Args:
            n_cells: Number of cells in the stack
        """
        broker_host = self.config.get('broker_host', '127.0.0.1')
        broker_port = self.config.get('broker_port', 8883)
        
        # Define sensors
        sensors = []
        
        # Cell voltage sensors
        for i in range(1, n_cells + 1):
            sensors.append(('cell', i))
        
        # Stack sensors
        sensors.extend([
            ('stack_current', None),
            ('stack_temperature', None),
            ('stack_pressure', None),
            ('h2_flow_rate', None),
            ('o2_flow_rate', None),
            ('tank_pressure', None),
            ('water_flow', None),
        ])
        
        # Create clients
        for sensor_name, cell_no in sensors:
            if sensor_name == 'cell':
                cn = f"sensor-{self.el_id}-cell_{cell_no}_voltage"
            else:
                cn = f"sensor-{self.el_id}-{sensor_name}"
            
            try:
                client = self._make_mqtt_client(cn, broker_host, broker_port)
                self.clients[cn] = client
                logger.debug(f"Connected client: {cn}")
            except Exception as e:
                logger.error(f"Failed to create client {cn}: {e}")
        
        logger.info(f"Connected {len(self.clients)} MQTT clients for {self.el_id}")
    
    def _make_mqtt_client(self, cn: str, broker_host: str, broker_port: int) -> mqtt.Client:
        """Create and connect an MQTT client with mTLS"""
        ca = ROOT / "certs/ca/ca.crt"
        cert = ROOT / f"certs/clients/{cn}/client.crt"
        key = ROOT / f"certs/clients/{cn}/client.key"
        
        client = mqtt.Client(client_id=cn, protocol=mqtt.MQTTv5)
        client.tls_set(
            ca_certs=str(ca),
            certfile=str(cert),
            keyfile=str(key),
            tls_version=ssl.PROTOCOL_TLS_CLIENT
        )
        client.tls_insecure_set(False)
        client.connect(broker_host, broker_port, keepalive=self.config.get('keepalive', 30))
        client.loop_start()
        
        return client
    
    def publish_state(self, state: ElectrolyserState, check_dropout: bool = True):
        """
        Publish electrolyser state to MQTT
        
        Args:
            state: Current electrolyser state
            check_dropout: Whether to check for telemetry dropout fault
        """
        # Check for telemetry dropout (if fault injector active)
        if check_dropout:
            # This would be checked by the caller if fault injector is available
            pass
        
        ts = time.time()
        qos = self.config.get('qos', 1)
        
        # Publish cell voltages
        for i, v in enumerate(state.cell_voltages, start=1):
            cn = f"sensor-{self.el_id}-cell_{i}_voltage"
            client = self.clients.get(cn)
            if client:
                topic = f"{self.topic_prefix}/{self.el_id}/cell/{i}/voltage"
                payload = {
                    "el": self.el_id,
                    "sensor": f"cell_{i}_voltage",
                    "cell": i,
                    "unit": "V",
                    "timestamp": ts,
                    "value": round(v, 4),
                    "sequence_id": state.sequence_id
                }
                self._publish_json(client, topic, payload, qos)
        
        # Publish stack current
        cn = f"sensor-{self.el_id}-stack_current"
        client = self.clients.get(cn)
        if client:
            topic = f"{self.topic_prefix}/{self.el_id}/stack/current"
            payload = {
                "el": self.el_id,
                "sensor": "stack_current",
                "unit": "A",
                "timestamp": ts,
                "value": round(state.I_stack, 4),
                "sequence_id": state.sequence_id
            }
            self._publish_json(client, topic, payload, qos)
        
        # Publish stack temperature
        cn = f"sensor-{self.el_id}-stack_temperature"
        client = self.clients.get(cn)
        if client:
            topic = f"{self.topic_prefix}/{self.el_id}/stack/temperature"
            payload = {
                "el": self.el_id,
                "sensor": "stack_temperature",
                "unit": "C",
                "timestamp": ts,
                "value": round(state.stack_temp, 3),
                "sequence_id": state.sequence_id
            }
            self._publish_json(client, topic, payload, qos)
        
        # Publish stack pressure
        cn = f"sensor-{self.el_id}-stack_pressure"
        client = self.clients.get(cn)
        if client:
            topic = f"{self.topic_prefix}/{self.el_id}/stack/pressure"
            payload = {
                "el": self.el_id,
                "sensor": "stack_pressure",
                "unit": "bar",
                "timestamp": ts,
                "value": round(state.stack_pressure, 3),
                "sequence_id": state.sequence_id
            }
            self._publish_json(client, topic, payload, qos)
        
        # Publish H2 flow
        cn = f"sensor-{self.el_id}-h2_flow_rate"
        client = self.clients.get(cn)
        if client:
            topic = f"{self.topic_prefix}/{self.el_id}/h2/flow_rate"
            payload = {
                "el": self.el_id,
                "sensor": "h2_flow_rate",
                "unit": "L/min",
                "timestamp": ts,
                "value": round(state.h2_flow_Lpm, 4),
                "sequence_id": state.sequence_id
            }
            self._publish_json(client, topic, payload, qos)
        
        # Publish O2 flow
        cn = f"sensor-{self.el_id}-o2_flow_rate"
        client = self.clients.get(cn)
        if client:
            topic = f"{self.topic_prefix}/{self.el_id}/o2/flow_rate"
            payload = {
                "el": self.el_id,
                "sensor": "o2_flow_rate",
                "unit": "L/min",
                "timestamp": ts,
                "value": round(state.o2_flow_Lpm, 4),
                "sequence_id": state.sequence_id
            }
            self._publish_json(client, topic, payload, qos)
        
        # Publish tank pressure
        cn = f"sensor-{self.el_id}-tank_pressure"
        client = self.clients.get(cn)
        if client:
            topic = f"{self.topic_prefix}/{self.el_id}/tank/pressure"
            payload = {
                "el": self.el_id,
                "sensor": "tank_pressure",
                "unit": "bar",
                "timestamp": ts,
                "value": round(state.tank_pressure_bar, 4),
                "sequence_id": state.sequence_id
            }
            self._publish_json(client, topic, payload, qos)
        
        # Publish water flow
        cn = f"sensor-{self.el_id}-water_flow"
        client = self.clients.get(cn)
        if client:
            topic = f"{self.topic_prefix}/{self.el_id}/water_flow"
            payload = {
                "el": self.el_id,
                "sensor": "water_flow",
                "unit": "L/min",
                "timestamp": ts,
                "value": round(state.water_flow, 3),
                "sequence_id": state.sequence_id
            }
            self._publish_json(client, topic, payload, qos)
        
        # Publish status
        status_cn = f"sensor-{self.el_id}-stack_current"
        status_client = self.clients.get(status_cn)
        if status_client:
            status_topic = f"{self.topic_prefix}/{self.el_id}/status"
            status_payload = {
                "el": self.el_id,
                "timestamp": ts,
                "status": "TRIPPED" if state.tripped else "OPERATIONAL",
                "sequence_id": state.sequence_id
            }
            if state.trip_reason:
                status_payload["reason"] = state.trip_reason
            self._publish_json(status_client, status_topic, status_payload, qos)
    
    def _publish_json(self, client: mqtt.Client, topic: str, payload: Dict, qos: int):
        """Publish JSON payload to MQTT topic"""
        try:
            json_payload = json.dumps(payload)
            client.publish(topic, json_payload, qos=qos)
        except Exception as e:
            logger.error(f"Failed to publish to {topic}: {e}")
    
    def disconnect_all(self):
        """Disconnect all MQTT clients"""
        for cn, client in self.clients.items():
            try:
                client.loop_stop()
                client.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting client {cn}: {e}")
        
        self.clients.clear()
        logger.info(f"Disconnected all clients for {self.el_id}")

# Made with Bob
