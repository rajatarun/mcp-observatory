import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { Tracer } from '../core/tracer.js';

test('Tracer creates spans with unique IDs', async () => {
  const tracer = new Tracer('test-service');
  const span1 = tracer.startSpan({ model: 'gpt-4' });
  const span2 = tracer.startSpan({ model: 'gpt-4' });

  assert.notEqual(span1.spanId, span2.spanId);
  assert.equal(span1.service, 'test-service');
  assert.equal(span1.model, 'gpt-4');
});

test('Tracer span inheritance', async () => {
  const tracer = new Tracer('test-service');
  const parent = tracer.startSpan();
  const child = tracer.startSpan({ parent });

  assert.equal(child.traceId, parent.traceId);
  assert.equal(child.parentSpanId, parent.spanId);
});

test('Span can be finished', async () => {
  const tracer = new Tracer('test-service');
  const span = tracer.startSpan();
  assert.equal(span.endTime, undefined);

  tracer.endSpan(span);
  assert.notEqual(span.endTime, undefined);
});

test('withSpan context manager works', async () => {
  const tracer = new Tracer('test-service');
  let spanClosed = false;

  await tracer.withSpan(async (span) => {
    assert.equal(span.endTime, undefined);
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve(true);
      }, 10);
    });
  });
});
