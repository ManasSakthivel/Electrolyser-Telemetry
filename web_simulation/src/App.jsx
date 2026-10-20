import React, { useEffect, useState } from 'react';
import mqtt from 'mqtt';
import DigitalTwin from './components/DigitalTwin';
import { createSyntheticFeed } from './synthetic/feed';

// Public demo build: VITE_DEMO_MODE=true replaces the broker with browser-side synthetic telemetry.
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true';

// Initial State
const INITIAL_STATE = {
  EL1: { cells: {}, current: 0, voltage: 0, temp: 0, h2: 0, o2: 0, water: 0, tank: 0 },
  EL2: { cells: {}, current: 0, voltage: 0, temp: 0, h2: 0, o2: 0, water: 0, tank: 0 },
  PLANT: { irr1: 0, irr2: 0 }
};

function App() {
  const [data, setData] = useState(INITIAL_STATE);
  const [status, setStatus] = useState(DEMO_MODE ? 'CONNECTED' : 'CONNECTING');

  // Declared before the effect so the effect can reference it (react-hooks/immutability).
  const handleMessage = (topic, payload) => {
    // Topic: electrolyser/plant-A/<DEVICE>/...
    const parts = topic.split('/');
    const device = parts[2]; // EL1, EL2, irradiance

    setData(prev => {
      const newState = { ...prev };

      if (device === 'EL1' || device === 'EL2') {
        const s = { ...newState[device] };
        const sensor = payload.sensor_id || payload.sensor || '';
        const value = payload.metrics && typeof payload.metrics.value === 'number' ? payload.metrics.value : payload.value;
        const cell = payload.cell;

        if (sensor.startsWith('cell_')) {
          s.cells = { ...s.cells, [cell]: value };
        } else if (sensor === 'stack_current') s.current = value;
        else if (sensor === 'stack_temperature') s.temp = value;
        else if (sensor === 'h2_flow_rate') s.h2 = value;
        else if (sensor === 'o2_flow_rate') s.o2 = value;
        else if (sensor === 'water_flow') s.water = value;
        else if (sensor === 'tank_pressure') s.tank = value;

        // Approx voltage sum
        if (Object.keys(s.cells).length > 0) {
          s.voltage = Object.values(s.cells).reduce((a, b) => a + b, 0);
        }

        newState[device] = s;
      } else if (device === 'irradiance') {
        const p = { ...newState.PLANT };
        const sensor = payload.sensor_id || payload.sensor || '';
        const value = payload.metrics && typeof payload.metrics.value === 'number' ? payload.metrics.value : payload.value;
        if (sensor === 'irradiance_1') p.irr1 = value;
        if (sensor === 'irradiance_2') p.irr2 = value;
        newState.PLANT = p;
      }

      return newState;
    });
  };

  useEffect(() => {
    if (DEMO_MODE) {
      const feed = createSyntheticFeed(handleMessage);
      return () => feed.stop();
    }

    // Connect to Mosquitto over WebSockets (local dev only; see the DEV guard below).
    // The broker's 9001 listener is TLS-only (mosquitto/conf/mosquitto.conf), so the default is wss://.
    const WS_URL      = import.meta.env.VITE_MQTT_WS_URL  || 'wss://localhost:9001';
    // Vite inlines VITE_* values into the client bundle, so the viewer credentials are
    // dev-only. In a production build these are empty and the live path cannot authenticate.
    const WS_USERNAME = import.meta.env.DEV ? (import.meta.env.VITE_MQTT_WS_USER || 'ws_viewer') : '';
    const WS_PASSWORD = import.meta.env.DEV ? (import.meta.env.VITE_MQTT_WS_PASS || '') : '';

    const client = mqtt.connect(WS_URL, {
      clientId: 'react-twin-' + Math.random().toString(16).substr(2, 8),
      username: WS_USERNAME,
      password: WS_PASSWORD,
      keepalive: 60,
      reconnectPeriod: 1000,
    });

    client.on('connect', () => {
      console.log('Connected to MQTT');
      setStatus('CONNECTED');
      client.subscribe('electrolyser/plant-A/#');
    });

    client.on('message', (topic, message) => {
      try {
        const payload = JSON.parse(message.toString());
        handleMessage(topic, payload);
      } catch (e) {
        console.error('Parse error', e);
      }
    });

    client.on('offline', () => setStatus('OFFLINE'));
    client.on('reconnect', () => setStatus('RECONNECTING'));
    client.on('error', (err) => {
      console.error('MQTT Error', err);
      setStatus('ERROR');
    });

    return () => {
      client.end();
    };
  }, []);

  if (status !== 'CONNECTED') {
    const colour = status === 'ERROR' || status === 'OFFLINE' ? 'border-red-500' : 'border-blue-500';
    const label  = {
      CONNECTING:   'Connecting to Plant…',
      RECONNECTING: 'Reconnecting…',
      OFFLINE:      'Broker offline — retrying…',
      ERROR:        'Connection error — retrying…',
    }[status] ?? status;

    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center text-white">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className={`w-12 h-12 border-4 ${colour} border-t-transparent rounded-full animate-spin`}></div>
          <span className="text-xl font-mono">{label}</span>
        </div>
      </div>
    );
  }

  return <DigitalTwin data={data} demo={DEMO_MODE} />;
}

export default App;
