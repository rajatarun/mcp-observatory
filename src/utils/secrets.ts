/**
 * Fail-closed resolution for the HMAC signing secret used by commit tokens.
 *
 * `TokenManager` used to fall back to `randomBytes(32)` whenever no secret
 * was passed. That is worse than a hardcoded default rather than better:
 * the key is unguessable, but it is also unshareable. Two `TokenManager`
 * instances in one process (the bundled demo builds one inside
 * `ToolProposer` and another inside `CommitVerifier`) never agreed on a
 * key, so every commit failed with `bad_signature`; and a process that
 * restarted, or a second replica behind a load balancer, could not verify
 * a token it had itself issued moments earlier. The failure surfaced as
 * `bad_signature` — indistinguishable from an actual forgery — with
 * nothing pointing at the missing configuration that caused it.
 *
 * `resolveSecret` makes the development key explicit and opt-in instead:
 * the secret comes from the caller or the environment, and anything else
 * throws at construction time, where the cause is obvious, rather than at
 * verification time, where it is not.
 */

export const COMMIT_SECRET_ENV = 'MCP_OBSERVATORY_COMMIT_SECRET';
export const ALLOW_DEV_SECRET_ENV = 'MCP_OBSERVATORY_ALLOW_DEV_SECRET';

/**
 * The documented development secret. It is public — it is in this file and
 * in every clone of the repository — and is only ever used when
 * `MCP_OBSERVATORY_ALLOW_DEV_SECRET=1` asks for it explicitly.
 */
export const DEV_COMMIT_SECRET = 'dev-commit-secret';

/** Raised when a signing secret would fall back to a known-insecure default. */
export class InsecureDefaultSecretError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'InsecureDefaultSecretError';
    // Required for `instanceof` to work when compiled to ES2020 targets.
    Object.setPrototypeOf(this, InsecureDefaultSecretError.prototype);
  }
}

let devSecretWarned = false;

export interface ResolveSecretOptions {
  envVar: string;
  devDefault: string;
  label: string;
}

/**
 * Resolve a signing secret, refusing to silently use a development default.
 *
 * Returns `explicit` when given, otherwise `process.env[envVar]`. If neither
 * is set, or the resolved value is the known development default (someone
 * copied it out of an example), the secret is treated as insecure: this
 * throws unless `MCP_OBSERVATORY_ALLOW_DEV_SECRET=1`, in which case
 * `devDefault` is returned and a warning is emitted once per process.
 */
export function resolveSecret(
  explicit: string | undefined,
  options: ResolveSecretOptions
): string {
  const fromEnv = process.env[options.envVar];
  const value = explicit !== undefined ? explicit : fromEnv;

  if (value === undefined || value === '' || value === options.devDefault) {
    if (process.env[ALLOW_DEV_SECRET_ENV] === '1') {
      if (!devSecretWarned) {
        devSecretWarned = true;
        console.warn(
          `[mcp-observatory] ${ALLOW_DEV_SECRET_ENV}=1: signing commit tokens ` +
            `with the public development secret. Tokens issued by this process ` +
            `can be forged by anyone. Set ${options.envVar} for any real deployment.`
        );
      }
      return options.devDefault;
    }
    throw new InsecureDefaultSecretError(
      `${options.label} is unset (or set to the known development default). ` +
        `Set ${options.envVar} to a strong, private secret shared by every ` +
        `process that issues or verifies commit tokens, or set ` +
        `${ALLOW_DEV_SECRET_ENV}=1 for local development, demos, and tests ` +
        `only — never in production.`
    );
  }

  return value;
}
