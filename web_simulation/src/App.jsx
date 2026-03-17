import React, { useEffect, useState } from 'react';
import mqtt from 'mqtt';
import DigitalTwin from './components/DigitalTwin';

// Initial State
const INITIAL_STATE = {
  EL1: { cells: {}, current: 0, voltage: 0, temp: 0, h2: 0, o2: 0, water: 0, tank: 0 },
  EL2: { cells: {}, current: 0, voltage: 0, temp: 0, h2: 0, o2: 0, water: 0, tank: 0 },
  PLANT: { irr1: 0, irr2: 0 }
};

function App() {
  const [data, setData] = useState(INITIAL_STATE);
  const [status, setStatus] = useState('CONNECTING');

  useEffect(() => {
    // Connect to Mosquitto over WebSockets
    const client = mqtt.connect('ws://localhost:9001', {
      clientId: 'react-twin-' + Math.random().toString(16).substr(2, 8),
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
    client.on('error', (err) => console.error('MQTT Error', err));

    return () => {
      client.end();
    };
  }, []);

  const handleMessage = (topic, payload) => {
    // Topic: electrolyser/plant-A/<DEVICE>/...
    const parts = topic.split('/');
    const device = parts[2]; // EL1, EL2, irradiance

    setData(prev => {
      const newState = { ...prev };

      if (device === 'EL1' || device === 'EL2') {
        const s = { ...newState[device] };
        const { sensor, value, cell } = payload;

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
        if (payload.sensor === 'irradiance_1') p.irr1 = payload.value;
        if (payload.sensor === 'irradiance_2') p.irr2 = payload.value;
        newState.PLANT = p;
      }

      return newState;
    });
  };

  if (status === 'CONNECTING') {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center text-white">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
          <span className="text-xl font-mono">Connecting to Plant...</span>
        </div>
      </div>
    );
  }

  return <DigitalTwin data={data} />;
}

export default App;
