import { Pool } from 'pg';

export interface Proposal {
  id: string;
  toolName: string;
  toolArgsHash: string;
  status: 'allowed' | 'blocked' | 'review';
  createdAt: Date;
  expiresAt: Date;
}

export interface Commit {
  id: string;
  proposalId: string;
  executed: boolean;
  executedAt?: Date;
}

export class InMemoryProposalStorage {
  private proposals: Map<string, Proposal> = new Map();
  private commits: Map<string, Commit> = new Map();

  async saveProposal(proposal: Proposal): Promise<void> {
    this.proposals.set(proposal.id, proposal);
  }

  async getProposal(id: string): Promise<Proposal | null> {
    const proposal = this.proposals.get(id);
    if (!proposal) return null;

    if (proposal.expiresAt < new Date()) {
      this.proposals.delete(id);
      return null;
    }

    return proposal;
  }

  async saveCommit(commit: Commit): Promise<void> {
    this.commits.set(commit.id, commit);
  }

  async getCommit(id: string): Promise<Commit | null> {
    return this.commits.get(id) || null;
  }

  async saveNonce(nonce: string): Promise<void> {
    // In-memory storage for nonce tracking
  }

  async hasNonce(nonce: string): Promise<boolean> {
    // Would need separate nonce tracking
    return false;
  }

  async cleanup(): Promise<void> {
    const now = new Date();
    for (const [id, proposal] of this.proposals.entries()) {
      if (proposal.expiresAt < now) {
        this.proposals.delete(id);
      }
    }
  }
}

export class PostgresProposalStorage {
  private pool: Pool;

  constructor(dsn: string) {
    this.pool = new Pool({ connectionString: dsn });
  }

  async saveProposal(proposal: Proposal): Promise<void> {
    const query = `
      INSERT INTO proposals (id, tool_name, tool_args_hash, status, created_at, expires_at)
      VALUES ($1, $2, $3, $4, $5, $6)
      ON CONFLICT (id) DO UPDATE SET status = $4, expires_at = $6
    `;
    await this.pool.query(query, [
      proposal.id,
      proposal.toolName,
      proposal.toolArgsHash,
      proposal.status,
      proposal.createdAt,
      proposal.expiresAt,
    ]);
  }

  async getProposal(id: string): Promise<Proposal | null> {
    const result = await this.pool.query(
      'SELECT * FROM proposals WHERE id = $1 AND expires_at > NOW()',
      [id]
    );
    if (result.rows.length === 0) return null;
    const row = result.rows[0];
    return {
      id: row.id,
      toolName: row.tool_name,
      toolArgsHash: row.tool_args_hash,
      status: row.status,
      createdAt: row.created_at,
      expiresAt: row.expires_at,
    };
  }

  async saveCommit(commit: Commit): Promise<void> {
    const query = `
      INSERT INTO commits (id, proposal_id, executed, executed_at)
      VALUES ($1, $2, $3, $4)
    `;
    await this.pool.query(query, [
      commit.id,
      commit.proposalId,
      commit.executed,
      commit.executedAt,
    ]);
  }

  async getCommit(id: string): Promise<Commit | null> {
    const result = await this.pool.query('SELECT * FROM commits WHERE id = $1', [id]);
    if (result.rows.length === 0) return null;
    const row = result.rows[0];
    return {
      id: row.id,
      proposalId: row.proposal_id,
      executed: row.executed,
      executedAt: row.executed_at,
    };
  }

  async saveNonce(nonce: string): Promise<void> {
    await this.pool.query(
      'INSERT INTO nonces (nonce, created_at) VALUES ($1, NOW())',
      [nonce]
    );
  }

  async hasNonce(nonce: string): Promise<boolean> {
    const result = await this.pool.query('SELECT 1 FROM nonces WHERE nonce = $1', [
      nonce,
    ]);
    return result.rows.length > 0;
  }

  async cleanup(): Promise<void> {
    await this.pool.query('DELETE FROM proposals WHERE expires_at < NOW()');
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}
