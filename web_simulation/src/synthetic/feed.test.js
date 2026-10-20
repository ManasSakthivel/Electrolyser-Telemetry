import { test } from 'node:test';
import assert from 'node:assert/strict';
import { CHANNELS, createSyntheticState, createSyntheticFeed, generateTick } from './feed.js';

// Deterministic PRNG (mulberry32) so the range assertions are reproducible.
function seeded(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test('emits 26 messages per tick: 12 per stack and 2 irradiance sensors', () => {
  const messages = generateTick(createSyntheticState(), seeded(1));
  assert.equal(messages.length, 26);
  assert.equal(messages.filter(([, p]) => p.stack_id === 'EL1').length, 12);
  assert.equal(messages.filter(([, p]) => p.stack_id === 'EL2').length, 12);
  assert.equal(messages.filter(([, p]) => p.stack_id === 'PLANT').length, 2);
});

test('topics match the Python sensor client topic mapping', () => {
  const topics = new Set(CHANNELS.map((c) => c.topic));
  for (const expected of [
    'electrolyser/plant-A/EL1/cell/1/voltage',
    'electrolyser/plant-A/EL2/cell/5/voltage',
    'electrolyser/plant-A/EL1/stack/current',
    'electrolyser/plant-A/EL1/stack/temperature',
    'electrolyser/plant-A/EL1/h2/flow_rate',
    'electrolyser/plant-A/EL2/o2/flow_rate',
    'electrolyser/plant-A/EL1/tank/pressure',
    'electrolyser/plant-A/EL1/water_flow',
    'electrolyser/plant-A/irradiance/1',
  ]) {
    assert.ok(topics.has(expected), `missing topic ${expected}`);
  }
});

test('payloads carry the fields the dashboard handler reads', () => {
  for (const [topic, payload] of generateTick(createSyntheticState(), seeded(2))) {
    assert.equal(typeof payload.sensor_id, 'string', topic);
    assert.equal(typeof payload.metrics.value, 'number', topic);
    assert.ok(Number.isFinite(payload.metrics.value), topic);
    assert.equal(payload.cell !== null, payload.sensor_id.startsWith('cell_'), topic);
  }
});

test('values stay in healthy ranges and near nominal over a long run', () => {
  const state = createSyntheticState();
  const random = seeded(3);
  for (let t = 0; t < 2000; t++) {
    for (const [topic, payload] of generateTick(state, random)) {
      const v = payload.metrics.value;
      if (payload.sensor_id.startsWith('cell_')) assert.ok(v > 1.3 && v < 2.3, `${topic} cell voltage ${v}`);
      if (payload.sensor_id === 'stack_temperature') assert.ok(v < 80, `${topic} temperature ${v}`);
      if (payload.sensor_id === 'tank_pressure') assert.ok(v < 35, `${topic} tank pressure ${v}`);
    }
  }
  CHANNELS.forEach((c, i) => {
    assert.ok(Math.abs(state[i] - c.nominal) <= 3 * c.spread + 1e-9 || c.spread === 0, `${c.topic} drifted to ${state[i]}`);
  });
});

test('createSyntheticFeed emits immediately and stops when asked', async () => {
  let count = 0;
  const feed = createSyntheticFeed(() => { count += 1; }, { intervalMs: 5, random: seeded(4) });
  assert.equal(count, 26, 'first tick emitted synchronously');
  await new Promise((resolve) => setTimeout(resolve, 30));
  feed.stop();
  const atStop = count;
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.ok(atStop > 26, 'interval ticks were emitted');
  assert.equal(count, atStop, 'no ticks after stop()');
});
