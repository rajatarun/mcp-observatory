# MCP Observatory - Node.js Edition

A modern TypeScript/Node.js implementation of an observability and APM toolkit for MCP (Model Context Protocol) servers, featuring a two-phase execution pattern for high-risk tool calls.

## Overview

MCP Observatory provides:

1. **Tracer & Observability**: Track spans, tokens, costs, and latency for every operation
2. **Proposal/Commit Pattern**: Two-phase execution for high-risk operations with deterministic fallbacks
3. **Risk Assessment**: Hallucination scoring, tool risk categorization, and numeric variance detection
4. **Cost Tracking**: Token estimation and model-aware pricing for various AI providers
5. **Storage Options**: In-memory or PostgreSQL-backed proposal/commit storage

## Architecture

```
┌─ Core Layer
│  ├─ Tracer: Span creation and lifecycle management
│  ├─ TraceContext: Span data model with metrics
│  └─ InvocationWrapper: Policy-driven execution wrapper
│
├─ Proposal/Commit Layer
│  ├─ ToolProposer: Risk scoring and proposal generation
│  ├─ TokenManager: HMAC-signed token issue/verify
│  ├─ CommitVerifier: Multi-stage verification with replay protection
│  └─ Storage: In-memory or PostgreSQL backends
│
├─ Assessment Layer
│  ├─ Hallucination Scoring: Output instability, grounding, variance
│  ├─ Risk Scoring: Tool classification by destructiveness/scope
│  └─ Hashing: Stable canonical JSON and prompt normalization
│
└─ Demo Layer
   ├─ MCPServer: Example server with propose/commit handlers
   └─ MCPClient: Example client with dual-measurement support
```

## Quick Start

### Installation

```bash
npm install
npm run build
```

### Running the Demo

```bash
# Without database
npm run demo

# With PostgreSQL (optional)
export MCP_OBSERVATORY_PG_DSN='postgresql://user:pass@localhost:5432/postgres'
psql "$MCP_OBSERVATORY_PG_DSN" -f sql/schema.sql
npm run demo
```

### Running Tests

```bash
npm test
```

## Core Concepts

### Spans & Tracing

Track execution metrics for any operation:

```typescript
import { Tracer } from 'mcp-observatory';

const tracer = new Tracer('my-service');

await tracer.withSpan(async (span) => {
  span.inputTokens = 150;
  span.outputTokens = 250;
  span.costUsd = 0.0045;
  
  // Your async operation here
}, { model: 'gpt-4o' });
```

### Two-Phase Execution

For high-risk operations, use propose/commit pattern:

```typescript
import { ToolProposer, CommitVerifier } from 'mcp-observatory';

const proposer = new ToolProposer();
const verifier = new CommitVerifier();

// Phase 1: Propose (no side effects)
const proposal = await proposer.propose({
  toolName: 'transfer_funds',
  toolArgs: { amount: 1000, to: 'account_456' },
  outputInstability: 0.3,
});

// Response includes commit token
console.log(proposal.status); // 'allowed' | 'blocked' | 'review'

// Phase 2: Commit (only if proposal token is valid)
if (proposal.commitToken) {
  const verification = verifier.verify({
    token: proposal.commitToken,
    proposalId: proposal.proposalId,
    toolName: 'transfer_funds',
    toolArgs: { amount: 1000, to: 'account_456' },
  });

  if (verification.canExecute) {
    // Execute the operation
  }
}
```

### Risk Assessment

Compute composite risk scores from multiple signals:

```typescript
import {
  computeHallucinationRiskScore,
  computeRiskScore,
  categorizeRisk,
} from 'mcp-observatory';

// Hallucination risk
const hallucScore = computeHallucinationRiskScore({
  outputInstability: 0.4,
  groundingScore: 0.7,
  numericVarianceScore: 0.1,
  selfConsistencyScore: 0.9,
  toolClaimMismatch: false,
});

// Tool risk categorization
const signals = categorizeRisk('delete_user', {});
const riskScore = computeRiskScore(signals);
```

### Cost Tracking

Estimate tokens and costs across models:

```typescript
import { estimateTokens, estimateCost, getPricing } from 'mcp-observatory';

const text = 'Generate a deployment plan';
const tokens = estimateTokens(text, 'gpt-4o');
const cost = estimateCost(tokens, 'gpt-4o', 'model');

console.log(`Tokens: ${tokens}, Cost: $${cost.toFixed(4)}`);
```

## Advanced Features

### Dual Measurement (Shadow Runs)

Compare two execution paths:

```typescript
import { InvocationWrapper } from 'mcp-observatory';

const wrapper = new InvocationWrapper('my-service');

const result = await wrapper.invoke({
  source: 'agent',
  model: 'gpt-4o',
  prompt: 'Analyze this request',
  call: () => primaryCall(),
  dualInvoke: true,
  shadowCall: () => shadowCall(),
});

console.log(`Primary cost: $${result.span.costUsd}`);
console.log(`Shadow cost: $${result.shadowSpan?.costUsd}`);
```

### Storage Options

#### In-Memory (Default)

```typescript
import { InMemoryProposalStorage } from 'mcp-observatory';

const storage = new InMemoryProposalStorage();
```

#### PostgreSQL

```typescript
import { PostgresProposalStorage } from 'mcp-observatory';

const storage = new PostgresProposalStorage(
  process.env.MCP_OBSERVATORY_PG_DSN!
);

// Later
await storage.close();
```

## Module Reference

### Core (`src/core`)

- **`tracer.ts`**: Span creation and lifecycle
- **`context.ts`**: TraceContext data model with metrics
- **`wrapper.ts`**: InvocationWrapper with policy decisioning

### Proposal/Commit (`src/proposal`)

- **`token.ts`**: TokenManager for HMAC-signed token issue/verify
- **`proposer.ts`**: ToolProposer with risk-based decisioning
- **`verifier.ts`**: CommitVerifier with replay protection
- **`storage.ts`**: In-memory and PostgreSQL storage backends

### Assessment (`src/hallucination`, `src/risk`)

- **`scoring.ts`** (hallucination): Risk scoring from instability, grounding, variance
- **`scoring.ts`** (risk): Tool risk categorization by destructiveness/scope

### Utilities (`src/utils`, `src/cost`)

- **`hashing.ts`**: Stable canonical JSON and prompt normalization
- **`time.ts`**: Time utilities
- **`tokenizer.ts`**: Token estimation with model-specific limits
- **`pricing.ts`**: Cost estimation for GPT and Claude models

### Demo (`src/demo`)

- **`server.ts`**: Example MCP server with propose/commit handlers
- **`client.ts`**: Example client with dual-measurement support

## Testing

```bash
npm test
```

Tests include:

- Tracer span creation and inheritance
- Token issuance, verification, and expiry
- Proposal scoring and status determination
- Hash stability and prompt normalization
- Risk and hallucination scoring

## API Endpoints (Demo Server)

The demo server exposes:

- `transfer_funds_propose(amount, to)` → {proposalId, status, commitToken?}
- `transfer_funds_commit(proposalId, commitToken, amount, to)` → {success, transactionId?}

## Security Rules

Commit verification enforces:

1. ✅ Token signature is valid
2. ✅ Token not expired (5-minute default)
3. ✅ Proposal exists and matches proposal_id
4. ✅ Tool name matches token payload
5. ✅ Args hash matches token payload (prevents tampering)
6. ✅ Nonce not already used (replay protection)

## Database Setup (Optional)

Apply schema to existing PostgreSQL database:

```bash
export MCP_OBSERVATORY_PG_DSN='postgresql://user:pass@localhost:5432/postgres'
psql "$MCP_OBSERVATORY_PG_DSN" -f sql/schema.sql
```

Schema includes:

- `proposals`: Proposal records with status and expiration
- `commits`: Execution tracking with timestamps
- `nonces`: Used nonces for replay prevention
- `tool_prompt_baselines`: Prompt drift baseline storage
- `traces`: Full execution traces with span hierarchy
- `cleanup_expired_proposals()`: Automated cleanup function

## Environment Variables

- `MCP_OBSERVATORY_PG_DSN`: PostgreSQL connection string (optional)
- `NODE_ENV`: Set to `production` for optimized builds

## Build & Development

```bash
npm run build      # Compile TypeScript
npm run dev        # Watch mode
npm run lint       # Lint with ESLint
npm test           # Run tests
npm run demo       # Run demo
```

## License

Apache License 2.0 (see LICENSE file)

## Architecture Preservation

This Node.js rewrite preserves the original Python architecture:

- ✅ Core tracer and span model
- ✅ Two-phase proposal/commit pattern
- ✅ HMAC-signed token verification
- ✅ Multi-stage risk scoring
- ✅ Storage abstraction (in-memory + PostgreSQL)
- ✅ Hallucination detection signals
- ✅ Cost and token tracking
- ✅ Demo applications
- ✅ Test coverage

The module structure and API interfaces remain consistent, enabling code reuse and knowledge transfer between Python and Node.js implementations.
