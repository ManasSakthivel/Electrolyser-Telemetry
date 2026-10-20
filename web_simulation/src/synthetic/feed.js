// Synthetic telemetry for the public demo. Topics and payload fields mirror what the
// Python sensor clients publish (clients/python/sensor_client.py resolve_topic), so the
// dashboard's message handler consumes them unchanged.

const BASE = 'electrolyser/plant-A';
const MEAN_REVERSION = 0.2; // fraction of the gap to nominal closed each tick

const CELL_NOMINAL = [1.95, 1.96, 1.94, 1.95, 1.97];

const STACK_CHANNELS = [
  { sensor_id: 'stack_current', path: 'stack/current', unit: 'A', nominal: 1.85, spread: 0.02 },
  { sensor_id: 'stack_temperature', path: 'stack/temperature', unit: 'degC', nominal: 48.5, spread: 0.5 },
  { sensor_id: 'stack_pressure', path: 'stack/pressure', unit: 'bar', nominal: 1.25, spread: 0.02 },
  { sensor_id: 'h2_flow_rate', path: 'h2/flow_rate', unit: 'L/min', nominal: 0.41, spread: 0.01 },
  { sensor_id: 'o2_flow_rate', path: 'o2/flow_rate', unit: 'L/min', nominal: 0.205, spread: 0.005 },
  { sensor_id: 'tank_pressure', path: 'tank/pressure', unit: 'bar', nominal: 16.2, spread: 0.2 },
  { sensor_id: 'water_flow', path: 'water_flow', unit: 'L/min', nominal: 1.15, spread: 0.02 },
];

// Every synthetic channel: 12 per electrolyser stack plus 2 irradiance sensors.
export const CHANNELS = [
  ...['EL1', 'EL2'].flatMap((stack) => [
    ...CELL_NOMINAL.map((nominal, i) => ({
      stack_id: stack,
      sensor_id: `cell_${i + 1}_voltage`,
      cell: i + 1,
      topic: `${BASE}/${stack}/cell/${i + 1}/voltage`,
      unit: 'V',
      nominal,
      spread: 0.01,
    })),
    ...STACK_CHANNELS.map((c) => ({
      stack_id: stack,
      sensor_id: c.sensor_id,
      cell: null,
      topic: `${BASE}/${stack}/${c.path}`,
      unit: c.unit,
      nominal: c.nominal,
      spread: c.spread,
    })),
  ]),
  ...[1, 2].map((i) => ({
    stack_id: 'PLANT',
    sensor_id: `irradiance_${i}`,
    cell: null,
    topic: `${BASE}/irradiance/${i}`,
    unit: 'W/m2',
    nominal: 820,
    spread: 20,
  })),
];

export function createSyntheticState() {
  return CHANNELS.map((c) => c.nominal);
}

// Advances every channel one step (mean-reverting random walk) and returns the messages to emit.
// `state` is updated in place; `random` and `now` are injectable so tests are deterministic.
export function generateTick(state, random = Math.random, now = new Date()) {
  const ts = now.toISOString();
  return CHANNELS.map((channel, i) => {
    const value = state[i] + (channel.nominal - state[i]) * MEAN_REVERSION + (random() - 0.5) * channel.spread;
    state[i] = value;
    const payload = {
      ts,
      site_id: 'plant-A',
      stack_id: channel.stack_id,
      sensor_id: channel.sensor_id,
      cell: channel.cell,
      metrics: { value: Number(value.toFixed(4)), unit: channel.unit, raw: null },
      fault_active: false,
    };
    return [channel.topic, payload];
  });
}

// Calls onMessage(topic, payload) for each synthetic message, once immediately and then every intervalMs.
export function createSyntheticFeed(onMessage, { intervalMs = 1000, random = Math.random } = {}) {
  const state = createSyntheticState();
  const tick = () => generateTick(state, random).forEach(([topic, payload]) => onMessage(topic, payload));
  tick();
  const timer = setInterval(tick, intervalMs);
  return { stop: () => clearInterval(timer) };
}
