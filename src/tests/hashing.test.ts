import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { hashText, hashJson, normalizePrompt, computePromptHash } from '../utils/hashing.js';

test('hashText produces consistent hashes', async () => {
  const hash1 = hashText('hello world');
  const hash2 = hashText('hello world');

  assert.equal(hash1, hash2);
  assert.equal(hash1.length, 64); // SHA256 hex
});

test('hashText produces different hashes for different inputs', async () => {
  const hash1 = hashText('hello');
  const hash2 = hashText('world');

  assert.notEqual(hash1, hash2);
});

test('hashJson handles objects', async () => {
  const obj = { b: 2, a: 1 };
  const hash = hashJson(obj);

  assert.ok(hash);
  assert.equal(hash.length, 64);
});

test('hashJson is order-independent', async () => {
  const obj1 = { a: 1, b: 2 };
  const obj2 = { b: 2, a: 1 };

  const hash1 = hashJson(obj1);
  const hash2 = hashJson(obj2);

  assert.equal(hash1, hash2);
});

test('normalizePrompt handles whitespace', async () => {
  const prompt = '  Hello   WORLD  ';
  const normalized = normalizePrompt(prompt);

  assert.equal(normalized, 'hello world');
});

test('computePromptHash is stable', async () => {
  const prompt = 'Generate a deployment plan';
  const hash1 = computePromptHash(prompt);
  const hash2 = computePromptHash('GENERATE A DEPLOYMENT PLAN');

  assert.equal(hash1, hash2);
});
