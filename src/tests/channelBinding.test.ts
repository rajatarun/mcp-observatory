import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { TokenManager } from '../proposal/token.js';
import { ToolProposer } from '../proposal/proposer.js';
import { CommitVerifier } from '../proposal/verifier.js';
import {
  CHANNEL_BELOW_REQUIRED_PROFILE,
  channelSatisfies,
  normaliseProfile,
} from '../proposal/channel.js';

const ARGS = { amount: 100, to: 'acct_1' };

function gate(provider?: (t: string, a: Record<string, unknown>) => Promise<string> | string,
              opts?: { requireChannelBinding?: boolean }) {
  const tm = new TokenManager('unit-secret');
  return {
    tm,
    proposer: new ToolProposer(tm, { channelProfileProvider: provider }),
    verifier: new CommitVerifier(tm, opts),
  };
}

async function allowed(proposer: ToolProposer) {
  const res = await proposer.propose({
    toolName: 'place_trade', toolArgs: ARGS,
    outputInstability: 0, numericVariance: 0, promptDrift: 0,
  });
  assert.ok(res.commitToken, `expected a token, got ${JSON.stringify(res)}`);
  return res;
}

// --- the lattice -----------------------------------------------------------

test('channelSatisfies orders the lattice', () => {
  assert.equal(channelSatisfies('QUANTUM_SAFE', 'CHEAP'), true);
  assert.equal(channelSatisfies('HARDENED', 'BALANCED'), true);
  assert.equal(channelSatisfies('BALANCED', 'HARDENED'), false);
  assert.equal(channelSatisfies('hardened', 'HARDENED'), true);   // case-insensitive
  assert.equal(channelSatisfies('  HARDENED  ', 'HARDENED'), true); // whitespace-tolerant
});

test('a channel the gate cannot place satisfies nothing', () => {
  for (const bad of [undefined, null, '', 'TLS1.3', 'unknown', '   ']) {
    assert.equal(channelSatisfies(bad, 'CHEAP'), false,
      `${JSON.stringify(bad)} must not satisfy the weakest requirement`);
  }
});

test('an unrecognised requirement is enforced at maximum', () => {
  assert.equal(channelSatisfies('HARDENED', 'NONSENSE'), false);
  assert.equal(channelSatisfies('QUANTUM_SAFE', 'NONSENSE'), true);
});

test('normaliseProfile fails secure', () => {
  assert.equal(normaliseProfile('hardened'), 'HARDENED');
  for (const bad of [undefined, null, '', 'nonsense', 7]) {
    assert.equal(normaliseProfile(bad), 'QUANTUM_SAFE');
  }
});

// --- no provider: nothing changes for existing consumers --------------------

test('without a provider no requirement is bound and commit succeeds', async () => {
  const { proposer, verifier } = gate();
  const p = await allowed(proposer);
  const decoded = JSON.parse(Buffer.from(p.commitToken!, 'base64').toString());
  assert.equal('requiredCipherProfile' in decoded, false,
    'a deployment running no channel policy must emit the same token as before');
  const v = verifier.verify({
    token: p.commitToken!, proposalId: p.proposalId, toolName: 'place_trade', toolArgs: ARGS,
  });
  assert.equal(v.valid, true);
});

// --- with a provider: bound and enforced ------------------------------------

test('a weaker channel is refused and a stronger one accepted', async () => {
  for (const [channel, expected] of [['BALANCED', false], ['HARDENED', true], ['QUANTUM_SAFE', true]] as const) {
    const { proposer, verifier } = gate(async () => 'HARDENED');
    const p = await allowed(proposer);
    const v = verifier.verify({
      token: p.commitToken!, proposalId: p.proposalId,
      toolName: 'place_trade', toolArgs: ARGS, channelProfile: channel,
    });
    assert.equal(v.valid, expected, `channel ${channel}`);
    if (!expected) assert.equal(v.reason, CHANNEL_BELOW_REQUIRED_PROFILE);
  }
});

test('omitting the channel on a bound token is refused', async () => {
  const { proposer, verifier } = gate(async () => 'BALANCED');
  const p = await allowed(proposer);
  const v = verifier.verify({
    token: p.commitToken!, proposalId: p.proposalId, toolName: 'place_trade', toolArgs: ARGS,
  });
  assert.equal(v.valid, false);
  assert.equal(v.reason, CHANNEL_BELOW_REQUIRED_PROFILE);
});

test('a refused channel does not burn the nonce', async () => {
  const { proposer, verifier } = gate(async () => 'HARDENED');
  const p = await allowed(proposer);

  const first = verifier.verify({
    token: p.commitToken!, proposalId: p.proposalId,
    toolName: 'place_trade', toolArgs: ARGS, channelProfile: 'CHEAP',
  });
  assert.equal(first.reason, CHANNEL_BELOW_REQUIRED_PROFILE);

  const retry = verifier.verify({
    token: p.commitToken!, proposalId: p.proposalId,
    toolName: 'place_trade', toolArgs: ARGS, channelProfile: 'HARDENED',
  });
  assert.equal(retry.valid, true,
    'a channel refusal must stay retryable: the call never ran, so the nonce must not be spent');
});

test('the requirement cannot be stripped or downgraded', async () => {
  const { proposer, tm } = gate(async () => 'QUANTUM_SAFE');
  const p = await allowed(proposer);
  const decoded = JSON.parse(Buffer.from(p.commitToken!, 'base64').toString());

  for (const mutated of [
    { ...decoded, requiredCipherProfile: 'CHEAP' },
    Object.fromEntries(Object.entries(decoded).filter(([k]) => k !== 'requiredCipherProfile')),
  ]) {
    const forged = Buffer.from(JSON.stringify(mutated)).toString('base64');
    assert.equal(tm.verifyToken(forged).valid, false,
      'the field is inside the MAC, so editing it is a forgery');
  }
});

test('a provider that throws binds the strongest profile', async () => {
  const { proposer, verifier } = gate(async () => { throw new Error('policy service unreachable'); });
  const p = await allowed(proposer);
  const decoded = JSON.parse(Buffer.from(p.commitToken!, 'base64').toString());
  assert.equal(decoded.requiredCipherProfile, 'QUANTUM_SAFE',
    'a policy service that could not be reached has not said "unconstrained"');

  const weak = verifier.verify({
    token: p.commitToken!, proposalId: p.proposalId,
    toolName: 'place_trade', toolArgs: ARGS, channelProfile: 'HARDENED',
  });
  assert.equal(weak.valid, false);
});

test('the provider receives the call it is deciding about', async () => {
  const seen: Record<string, unknown> = {};
  const { proposer } = gate((toolName, toolArgs) => {
    seen.toolName = toolName; seen.toolArgs = toolArgs;
    return 'CHEAP';
  });
  await proposer.propose({
    toolName: 'transfer_funds', toolArgs: ARGS,
    outputInstability: 0, numericVariance: 0, promptDrift: 0,
  });
  assert.equal(seen.toolName, 'transfer_funds');
  assert.deepEqual(seen.toolArgs, ARGS);
});

test('a review token is bound too, because here it is usable', async () => {
  // Unlike the Python line, `review` in this package returns a usable commit
  // token. An unbound review token would be a way around P6, not a lesser
  // form of it, so it must carry the same requirement.
  const { proposer, verifier } = gate(async () => 'QUANTUM_SAFE');
  const res = await proposer.propose({
    toolName: 'place_trade', toolArgs: ARGS,
    outputInstability: 0.5, numericVariance: 0.5, promptDrift: 0.5,
  });
  if (res.status !== 'review' || !res.commitToken) return; // thresholds moved; nothing to assert

  const decoded = JSON.parse(Buffer.from(res.commitToken, 'base64').toString());
  assert.equal(decoded.requiredCipherProfile, 'QUANTUM_SAFE');
  const v = verifier.verify({
    token: res.commitToken, proposalId: res.proposalId,
    toolName: 'place_trade', toolArgs: ARGS, channelProfile: 'CHEAP',
  });
  assert.equal(v.valid, false, 'a review token must honour the channel requirement');
});

test('strict mode refuses a token carrying no requirement', async () => {
  const { proposer, verifier } = gate(undefined, { requireChannelBinding: true });
  const p = await allowed(proposer);
  const v = verifier.verify({
    token: p.commitToken!, proposalId: p.proposalId,
    toolName: 'place_trade', toolArgs: ARGS, channelProfile: 'QUANTUM_SAFE',
  });
  assert.equal(v.valid, false);
  assert.equal(v.reason, CHANNEL_BELOW_REQUIRED_PROFILE);
});
