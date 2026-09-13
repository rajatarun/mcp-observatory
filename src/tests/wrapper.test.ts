import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { InvocationWrapper } from '../core/wrapper.js';
import { Tracer } from '../core/tracer.js';
import { TraceContext } from '../core/context.js';
import { hashText } from '../utils/hashing.js';
import { estimateTokens } from '../cost/tokenizer.js';

class BoomError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'BoomError';
  }
}

/**
 * `invoke()` never hands its internal span back out on the failure path (it
 * only throws), so to assert on span state after a rejection we spy on
 * `Tracer.prototype.startSpan` and capture every span it creates.
 */
function captureSpans() {
  const original = Tracer.prototype.startSpan;
  const spans: TraceContext[] = [];
  Tracer.prototype.startSpan = function (
    this: Tracer,
    ...args: Parameters<Tracer['startSpan']>
  ): TraceContext {
    const span = original.apply(this, args);
    spans.push(span);
    return span;
  };
  return {
    spans,
    restore: () => {
      Tracer.prototype.startSpan = original;
    },
  };
}

test('a rejecting sync call() propagates the original error unchanged', async () => {
  const wrapper = new InvocationWrapper('test-service');
  const original = new BoomError('tool exploded');

  await assert.rejects(
    () =>
      wrapper.invoke({
        source: 'model',
        prompt: 'do the thing',
        call: () => {
          throw original;
        },
      }),
    (error: unknown) => {
      // Must be the exact same error instance -- not a TypeError from
      // hashText(undefined) replacing it in the `finally` block.
      assert.equal(error, original);
      assert.ok(error instanceof BoomError);
      assert.equal((error as Error).message, 'tool exploded');
      return true;
    }
  );
});

test('a rejecting async call() propagates the original error unchanged', async () => {
  const wrapper = new InvocationWrapper('test-service');
  const original = new Error('async rejection');

  await assert.rejects(
    () =>
      wrapper.invoke({
        source: 'model',
        prompt: 'do the thing',
        call: async () => {
          throw original;
        },
      }),
    (error: unknown) => {
      assert.equal(error, original);
      assert.equal((error as Error).message, 'async rejection');
      return true;
    }
  );
});

test('failed call: span is still finished with statusCode 500, no output hash, zero output tokens', async () => {
  const wrapper = new InvocationWrapper('test-service');
  const capture = captureSpans();

  try {
    await assert.rejects(() =>
      wrapper.invoke({
        source: 'model',
        prompt: 'do the thing',
        call: () => {
          throw new Error('boom');
        },
      })
    );

    assert.equal(capture.spans.length, 1);
    const [span] = capture.spans;

    assert.equal(span.statusCode, 500);
    assert.ok(span.endTime, 'span.finish() should have been called');
    assert.equal(span.outputHash, undefined);
    assert.equal(span.outputTokens, 0);
    assert.equal(span.totalTokens, span.inputTokens || 0);
    assert.equal(typeof span.costUsd, 'number');
  } finally {
    capture.restore();
  }
});

test('successful call still produces the pre-fix outputHash and outputTokens', async () => {
  const wrapper = new InvocationWrapper('test-service');
  const output = { result: 'ok', count: 3 };

  const result = await wrapper.invoke({
    source: 'model',
    prompt: 'do the thing',
    call: () => output,
  });

  const expectedText = JSON.stringify(output);
  assert.equal(result.span.outputHash, hashText(expectedText));
  assert.equal(result.span.outputTokens, estimateTokens(expectedText, undefined));
  assert.equal(result.span.totalTokens, (result.span.inputTokens || 0) + result.span.outputTokens!);
  assert.equal(result.output, output);
  assert.notEqual(result.span.endTime, undefined);
});

test('invoke() does not throw when a successful output contains a BigInt (JSON.stringify would throw)', async () => {
  const wrapper = new InvocationWrapper('test-service');
  const output = { big: 10n };

  const result = await wrapper.invoke({
    source: 'model',
    prompt: 'do the thing',
    call: () => output,
  });

  assert.ok(result.span.outputHash);
  assert.equal(typeof result.span.outputTokens, 'number');
  assert.equal(result.decision.action, 'allow');
});

test('invoke() does not throw when a successful output is circular (JSON.stringify would throw)', async () => {
  const wrapper = new InvocationWrapper('test-service');
  const output: Record<string, unknown> = { name: 'circular' };
  output.self = output;

  const result = await wrapper.invoke({
    source: 'model',
    prompt: 'do the thing',
    call: () => output,
  });

  assert.ok(result.span.outputHash);
  assert.equal(typeof result.span.outputTokens, 'number');
  assert.equal(result.decision.action, 'allow');
});

test('invoke() does not throw when a successful output is undefined (JSON.stringify returns the value undefined)', async () => {
  const wrapper = new InvocationWrapper('test-service');

  const result = await wrapper.invoke({
    source: 'model',
    prompt: 'do the thing',
    call: () => undefined,
  });

  // Empty/undefined output is a legitimate 'blocked' decision, not a crash.
  assert.equal(result.decision.action, 'block');
  assert.equal(result.output, undefined);
});
