import { ToolProposer } from '../proposal/proposer.js';
import { CommitVerifier } from '../proposal/verifier.js';
import { Tracer } from '../core/tracer.js';

interface ToolCall {
  toolName: string;
  proposalId?: string;
  commitToken?: string;
  args: Record<string, unknown>;
}

export class MCPServer {
  private proposer: ToolProposer;
  private verifier: CommitVerifier;
  private tracer: Tracer;

  constructor() {
    this.proposer = new ToolProposer();
    this.verifier = new CommitVerifier();
    this.tracer = new Tracer('mcp-server');
  }

  async handleToolCall(call: ToolCall): Promise<unknown> {
    return await this.tracer.withSpan(async (span) => {
      if (call.toolName.includes('propose')) {
        return await this.handleProposal(call, span);
      }

      if (call.toolName.includes('commit')) {
        return await this.handleCommit(call, span);
      }

      return await this.executeTool(call, span);
    });
  }

  private async handleProposal(
    call: ToolCall,
    span: any
  ): Promise<unknown> {
    const baseName = call.toolName.replace('_propose', '');
    const result = await this.proposer.propose({
      toolName: baseName,
      toolArgs: call.args,
      outputInstability: Math.random() * 0.5,
    });

    span.tags['proposal_id'] = result.proposalId;
    span.tags['proposal_status'] = result.status;

    return {
      proposalId: result.proposalId,
      status: result.status,
      commitToken: result.commitToken,
      fallbackResponse: result.fallbackResponse,
    };
  }

  private async handleCommit(
    call: ToolCall,
    span: any
  ): Promise<unknown> {
    if (!call.proposalId || !call.commitToken) {
      return {
        success: false,
        reason: 'missing_proposal_or_token',
      };
    }

    const baseName = call.toolName.replace('_commit', '');
    const verification = this.verifier.verify({
      token: call.commitToken,
      proposalId: call.proposalId,
      toolName: baseName,
      toolArgs: call.args,
    });

    span.tags['verification_valid'] = verification.valid;

    if (!verification.canExecute) {
      return {
        success: false,
        reason: verification.reason,
      };
    }

    return await this.executeTool(
      { ...call, toolName: baseName },
      span
    );
  }

  private async executeTool(
    call: ToolCall,
    span: any
  ): Promise<unknown> {
    span.toolName = call.toolName;

    const amount = call.args.amount as number;
    const to = call.args.to as string;

    if (call.toolName === 'transfer_funds') {
      return {
        success: true,
        transactionId: Math.random().toString(36).slice(2),
        from: 'acct_main',
        to,
        amount,
        timestamp: new Date().toISOString(),
      };
    }

    return {
      success: true,
      result: `Executed ${call.toolName}`,
    };
  }
}

export async function runServerDemo(): Promise<void> {
  const server = new MCPServer();

  console.log('=== MCP Server Demo ===\n');

  const proposalResult = await server.handleToolCall({
    toolName: 'transfer_funds_propose',
    args: { amount: 1000, to: 'acct_bob' },
  }) as any;

  console.log('1. Proposal Phase:');
  console.log(JSON.stringify(proposalResult, null, 2));

  if (proposalResult.status === 'allowed' || proposalResult.status === 'review') {
    const commitResult = await server.handleToolCall({
      toolName: 'transfer_funds_commit',
      proposalId: proposalResult.proposalId,
      commitToken: proposalResult.commitToken,
      args: { amount: 1000, to: 'acct_bob' },
    });

    console.log('\n2. Commit Phase:');
    console.log(JSON.stringify(commitResult, null, 2));
  }
}
