import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { buildItem, DynamoDBSpanExporter } from '../aws/dynamodbExporter.js';
import { TraceContext } from '../core/context.js';

const here = dirname(fileURLToPath(import.meta.url));
const CONTRACT = JSON.parse(
  readFileSync(join(here, '..', '..', 'contracts', 'observatory_metrics_item.json'), 'utf8'),
);

const unwrap = (v: unknown): unknown =>
  (v && typeof v === 'object' && 'S' in (v as object)) ? (v as { S: string }).S
  : (v && typeof v === 'object' && 'N' in (v as object)) ? (v as { N: string }).N
  : v;

function span(overrides: Record<string, unknown> = {}) {
  return new TraceContext({ service: 'unit-test', toolName: 'transfer_funds', ...overrides }).toJSON();
}

test('the exporter emits the contract version this package vendors', () => {
  assert.equal(CONTRACT.version, '2.0.0');
});

test('key attributes are lower case (I1)', () => {
  const item = buildItem(span());
  assert.ok('pk' in item && 'sk' in item);
  assert.equal('PK' in item, false);
  assert.equal('SK' in item, false);
});

test('sk leads with the timestamp so range queries work (I3)', () => {
  const item = buildItem(span());
  const sk = String(unwrap(item.sk));
  const [ts, trace] = sk.split('#');
  assert.ok(trace, 'sk must carry the trace id after the timestamp');
  assert.match(ts, /^\d{4}-\d{2}-\d{2}T/);
});

test('the SpanTimelineIndex keys are present and agree (I6, I7)', () => {
  const gsi = CONTRACT.gsi;
  const item = buildItem(span());
  for (const key of [gsi.partition_key, gsi.sort_key]) {
    assert.ok(key in item, `${key} missing: the row would not be in ${gsi.name}`);
  }
  const spanDate = String(unwrap(item[gsi.partition_key]));
  const timestamp = String(unwrap(item[gsi.sort_key]));
  assert.match(spanDate, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(
    timestamp.slice(0, 10), spanDate,
    'span_date and timestamp must come from one clock reading; two can straddle midnight ' +
    'and file a row under a day it did not happen on',
  );
});

test('operation is always present, derived when not supplied (I8)', () => {
  assert.equal(unwrap(buildItem(span()).operation), 'invoke_tool');
  assert.equal(unwrap(buildItem(span({ toolName: undefined, model: 'claude' })).operation), 'invoke_model');
  assert.equal(unwrap(buildItem(span({ operation: 'invoke_agent' })).operation), 'invoke_agent');
});

test('every attribute the contract requires is emitted', () => {
  const item = buildItem(span());
  for (const key of Object.keys(CONTRACT.required_attributes)) {
    assert.ok(key in item, `contract requires '${key}' and the exporter does not emit it`);
  }
});

test('rows expire (I4)', () => {
  const item = buildItem(span());
  assert.ok('ttl' in item);
  assert.ok(Number(unwrap(item.ttl)) > Math.floor(Date.now() / 1000));
});

test('a telemetry write failure never propagates to the caller', async () => {
  const exporter = new DynamoDBSpanExporter({
    tableName: 'unit-test',
    client: { send: async () => { throw new Error('DynamoDB is down'); } },
  });
  // Must resolve, not reject: telemetry cannot be allowed to fail the call it
  // observes. It is logged rather than swallowed silently, which is the part a
  // sibling writer got wrong for the life of its integration.
  await exporter.export(span());
});

test('no table configured is a no-op, not a crash', async () => {
  const exporter = new DynamoDBSpanExporter({ tableName: undefined });
  await exporter.export(span());
});
