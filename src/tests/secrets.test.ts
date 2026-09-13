import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { TokenManager } from '../proposal/token.js';
import {
  ALLOW_DEV_SECRET_ENV,
  COMMIT_SECRET_ENV,
  DEV_COMMIT_SECRET,
  InsecureDefaultSecretError,
} from '../utils/secrets.js';

function withEnv<T>(env: Record<string, string | undefined>, fn: () => T): T {
  const saved: Record<string, string | undefined> = {};
  for (const key of Object.keys(env)) {
    saved[key] = process.env[key];
    if (env[key] === undefined) delete process.env[key];
    else process.env[key] = env[key];
  }
  try {
    return fn();
  } finally {
    for (const key of Object.keys(saved)) {
      if (saved[key] === undefined) delete process.env[key];
      else process.env[key] = saved[key];
    }
  }
}

test('TokenManager construction throws when no secret is configured', async () => {
  withEnv(
    { [COMMIT_SECRET_ENV]: undefined, [ALLOW_DEV_SECRET_ENV]: undefined },
    () => {
      assert.throws(
        () => new TokenManager(),
        (error: unknown) => {
          assert.ok(error instanceof InsecureDefaultSecretError);
          assert.equal((error as Error).name, 'InsecureDefaultSecretError');
          // The message must name the configuration that is missing;
          // a bare `bad_signature` at verify time is what this replaces.
          assert.match((error as Error).message, new RegExp(COMMIT_SECRET_ENV));
          return true;
        }
      );
    }
  );
});

test('TokenManager construction throws when the dev secret is passed explicitly', async () => {
  withEnv({ [ALLOW_DEV_SECRET_ENV]: undefined }, () => {
    assert.throws(
      () => new TokenManager(DEV_COMMIT_SECRET),
      InsecureDefaultSecretError
    );
  });
});

test('TokenManager reads the secret from the environment', async () => {
  const token = withEnv(
    { [COMMIT_SECRET_ENV]: 'env-provided-secret', [ALLOW_DEV_SECRET_ENV]: undefined },
    () => {
      const manager = new TokenManager();
      return manager.issueToken({
        proposalId: 'p1',
        toolName: 'transfer_funds',
        toolArgsHash: 'hash',
        compositeScore: 0.1,
      }).token;
    }
  );

  // A second manager built from the same environment verifies the token:
  // this is what a restart or a second replica does, and what a
  // per-instance random secret made impossible.
  const verified = withEnv(
    { [COMMIT_SECRET_ENV]: 'env-provided-secret', [ALLOW_DEV_SECRET_ENV]: undefined },
    () => new TokenManager().verifyToken(token)
  );
  assert.equal(verified.valid, true);
});

test('TokenManager construction succeeds under the dev-secret override', async () => {
  withEnv(
    { [COMMIT_SECRET_ENV]: undefined, [ALLOW_DEV_SECRET_ENV]: '1' },
    () => {
      const a = new TokenManager();
      const b = new TokenManager();
      const { token } = a.issueToken({
        proposalId: 'p1',
        toolName: 'transfer_funds',
        toolArgsHash: 'hash',
        compositeScore: 0.1,
      });
      // Two independently constructed managers now agree on the key.
      assert.equal(b.verifyToken(token).valid, true);
    }
  );
});

test('demo server completes the commit phase it previously failed', async () => {
  const { MCPServer } = await import('../demo/server.js');

  const server = await withEnv(
    { [COMMIT_SECRET_ENV]: undefined, [ALLOW_DEV_SECRET_ENV]: '1' },
    () => new MCPServer()
  );

  const proposal = (await server.handleToolCall({
    toolName: 'transfer_funds_propose',
    args: { amount: 1000, to: 'acct_bob' },
  })) as { status: string; proposalId: string; commitToken?: string };

  assert.notEqual(proposal.status, 'blocked');

  const commit = (await server.handleToolCall({
    toolName: 'transfer_funds_commit',
    proposalId: proposal.proposalId,
    commitToken: proposal.commitToken!,
    args: { amount: 1000, to: 'acct_bob' },
  })) as { success: boolean; reason?: string };

  // Before the fix this was `{ success: false, reason: 'bad_signature' }`,
  // because the proposer and the verifier each held their own random key.
  assert.equal(commit.reason, undefined);
  assert.equal(commit.success, true);
});
