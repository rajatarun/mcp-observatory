/**
 * Writes finished spans to the shared OBSERVATORY_METRICS DynamoDB table.
 *
 * This did not exist on the JS side, so every Node consumer hand-rolled its
 * own writer — which is exactly how the table ended up with several mutually
 * incompatible row shapes, one of them rejected outright by DynamoDB for two
 * years without anyone noticing. The item shape is a cross-repository
 * interface pinned in `contracts/observatory_metrics_item.json`; this exporter
 * implements it so consumers can stop re-deriving it.
 *
 * The AWS SDK is imported lazily and is an optional peer dependency: most
 * consumers of this package never write to DynamoDB, and requiring the SDK for
 * all of them to serve some of them is the coupling this package avoids
 * elsewhere too.
 */
import type { TraceSpan } from '../core/context.js';

/**
 * The slice of @aws-sdk/client-dynamodb this file uses.
 *
 * Declared structurally and loaded through a non-literal specifier so
 * TypeScript does not try to resolve the package at build time. That keeps the
 * SDK a genuinely optional runtime dependency: consumers that never write to
 * DynamoDB neither install it nor pay for it, and this file still typechecks
 * in a tree where it is absent.
 */
interface DynamoModule {
  DynamoDBClient: new (config?: unknown) => { send: (command: unknown) => Promise<unknown> };
  PutItemCommand: new (input: unknown) => unknown;
}

const AWS_SDK_SPECIFIER = '@aws-sdk/client-dynamodb';

async function loadAwsSdk(): Promise<DynamoModule> {
  return (await import(AWS_SDK_SPECIFIER)) as unknown as DynamoModule;
}

export const TABLE_NAME_ENV = 'OBSERVATORY_METRICS_TABLE';
const DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60; // 90 days, matching the Python exporter

export interface DynamoDBExporterOptions {
  tableName?: string;
  ttlSeconds?: number;
  region?: string;
  /** Injected for tests, and for a consumer that already holds a configured client. */
  client?: { send: (command: unknown) => Promise<unknown> };
}

/** Build the item for a span. Exported so a conformance test can check it without AWS. */
export function buildItem(span: TraceSpan, ttlSeconds = DEFAULT_TTL_SECONDS): Record<string, unknown> {
  // One clock reading, not two. Deriving span_date from a second `new Date()`
  // can straddle midnight and file a row under a day it did not happen on,
  // which contract invariant I7 explicitly refuses.
  const started = (span.startTime instanceof Date ? span.startTime : new Date()).toISOString();
  const partition = span.toolName || span.model || 'unknown';
  const operation = span.operation
    || (span.toolName ? 'invoke_tool' : span.model ? 'invoke_model' : 'unknown');

  const item: Record<string, unknown> = {
    // Lower case, because the table's key schema is lower case and DynamoDB
    // attribute names are case sensitive. A writer in this portfolio spelled
    // these `PK`/`SK`; every PutItem was rejected and swallowed by a bare
    // catch, so it wrote nothing at all and reported success.
    pk: { S: `SPAN#${partition}` },
    sk: { S: `${started}#${span.traceId}` },

    // SpanTimelineIndex keys. A GSI indexes only items carrying BOTH of them,
    // so omitting either makes the row invisible to every dashboard exactly as
    // a mismatched pk prefix used to (contract I6-I8).
    span_date: { S: started.slice(0, 10) },
    timestamp: { S: started },
    operation: { S: operation },

    service: { S: span.service },
    trace_id: { S: span.traceId },
    ttl: { N: String(Math.floor(Date.now() / 1000) + ttlSeconds) },
  };

  if (span.model) item.model_id = { S: span.model };
  if (span.toolName) item.tool_name = { S: span.toolName };
  if (typeof span.costUsd === 'number') item.cost_usd = { N: String(span.costUsd) };
  if (typeof span.inputTokens === 'number') item.prompt_tokens = { N: String(span.inputTokens) };
  if (typeof span.outputTokens === 'number') item.completion_tokens = { N: String(span.outputTokens) };
  if (typeof span.statusCode === 'number') item.status_code = { N: String(span.statusCode) };

  return item;
}

export class DynamoDBSpanExporter {
  private tableName?: string;
  private ttlSeconds: number;
  private region?: string;
  private client?: { send: (command: unknown) => Promise<unknown> };

  constructor(options: DynamoDBExporterOptions = {}) {
    this.tableName = options.tableName || process.env[TABLE_NAME_ENV];
    this.ttlSeconds = options.ttlSeconds ?? DEFAULT_TTL_SECONDS;
    this.region = options.region;
    this.client = options.client;
  }

  private async getClient(): Promise<{ send: (c: unknown) => Promise<unknown> }> {
    if (this.client) return this.client;
    const mod = await loadAwsSdk();
    this.client = new mod.DynamoDBClient(this.region ? { region: this.region } : {});
    return this.client!;
  }

  /**
   * Export one span. Never throws: telemetry must not be able to fail the call
   * it is observing. The failure IS logged, unlike the bare `catch {}` that let
   * a sibling writer fail silently for the life of the integration.
   */
  async export(span: TraceSpan): Promise<void> {
    if (!this.tableName) return;
    try {
      const { PutItemCommand } = await loadAwsSdk();
      const client = await this.getClient();
      await client.send(new PutItemCommand({ TableName: this.tableName, Item: buildItem(span, this.ttlSeconds) as never }));
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn(
        `[mcp-observatory] OBSERVATORY_METRICS write failed (table=${this.tableName}): ` +
        `${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }
}
