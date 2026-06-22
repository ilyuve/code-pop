import { Client } from 'pg';
import { DatabaseAdapter, RepoAdapter, FileAdapter, SymbolAdapter, EmbeddingAdapter, CallGraphAdapter, Repo, RepoCreate, File, FileCreate, Symbol, SymbolCreate, Embedding, EmbeddingCreate, EmbeddingSearchResult, CallGraphEdge, CallGraphEdgeCreate, SymbolType, CallType } from './adapter';

export class PostgreSQLAdapter implements DatabaseAdapter {
  private client: Client;
  private repoAdapter: PostgresRepoAdapter;
  private fileAdapter: PostgresFileAdapter;
  private symbolAdapter: PostgresSymbolAdapter;
  private embeddingAdapter: PostgresEmbeddingAdapter;
  private callGraphAdapter: PostgresCallGraphAdapter;

  constructor() {
    const connectionString = process.env.DATABASE_URL || 'postgresql://postgres:codepop123@localhost:5432/codepop';
    this.client = new Client({ connectionString });
    this.repoAdapter = new PostgresRepoAdapter(this.client);
    this.fileAdapter = new PostgresFileAdapter(this.client);
    this.symbolAdapter = new PostgresSymbolAdapter(this.client);
    this.embeddingAdapter = new PostgresEmbeddingAdapter(this.client);
    this.callGraphAdapter = new PostgresCallGraphAdapter(this.client);
  }

  async connect(): Promise<void> {
    await this.client.connect();
    await this.initSchema();
  }

  async disconnect(): Promise<void> {
    await this.client.end();
  }

  private async initSchema(): Promise<void> {
    const queries = [
      `CREATE TABLE IF NOT EXISTS repos (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name VARCHAR(255) NOT NULL,
        path TEXT NOT NULL UNIQUE,
        git_url TEXT,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        last_indexed_at TIMESTAMP,
        file_count INTEGER DEFAULT 0,
        symbol_count INTEGER DEFAULT 0
      )`,
      `CREATE TABLE IF NOT EXISTS files (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        path TEXT NOT NULL,
        language VARCHAR(50),
        content_hash VARCHAR(64),
        size_bytes INTEGER,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW(),
        git_modified_at TIMESTAMP,
        git_author TEXT,
        git_commit_msg TEXT,
        UNIQUE(repo_id, path)
      )`,
      `CREATE TABLE IF NOT EXISTS symbols (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        file_id UUID REFERENCES files(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        type VARCHAR(50) NOT NULL,
        kind VARCHAR(100),
        line INTEGER NOT NULL,
        column INTEGER NOT NULL,
        end_line INTEGER,
        end_column INTEGER,
        parent_id UUID REFERENCES symbols(id),
        is_exported BOOLEAN DEFAULT FALSE
      )`,
      `CREATE TABLE IF NOT EXISTS embeddings (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        file_id UUID REFERENCES files(id) ON DELETE CASCADE,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        embedding vector(1536) NOT NULL,
        token_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
      )`,
      `CREATE TABLE IF NOT EXISTS call_graph_edges (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        source_id UUID REFERENCES symbols(id) ON DELETE CASCADE,
        target_id UUID REFERENCES symbols(id) ON DELETE CASCADE,
        repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
        call_type VARCHAR(50) NOT NULL
      )`,
      `CREATE INDEX IF NOT EXISTS idx_files_repo_id ON files(repo_id)`,
      `CREATE INDEX IF NOT EXISTS idx_symbols_file_id ON symbols(file_id)`,
      `CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)`,
      `CREATE INDEX IF NOT EXISTS idx_embeddings_file_id ON embeddings(file_id)`,
      `CREATE INDEX IF NOT EXISTS idx_call_graph_source ON call_graph_edges(source_id)`,
      `CREATE INDEX IF NOT EXISTS idx_call_graph_target ON call_graph_edges(target_id)`,
      `CREATE INDEX IF NOT EXISTS idx_call_graph_repo ON call_graph_edges(repo_id)`
    ];

    for (const query of queries) {
      await this.client.query(query);
    }
  }

  get repo(): RepoAdapter { return this.repoAdapter; }
  get file(): FileAdapter { return this.fileAdapter; }
  get symbol(): SymbolAdapter { return this.symbolAdapter; }
  get embedding(): EmbeddingAdapter { return this.embeddingAdapter; }
  get callGraph(): CallGraphAdapter { return this.callGraphAdapter; }
}

class PostgresRepoAdapter implements RepoAdapter {
  constructor(private client: Client) {}

  async create(repo: RepoCreate): Promise<Repo> {
    const result = await this.client.query(
      `INSERT INTO repos (name, path, git_url) VALUES ($1, $2, $3) RETURNING *`,
      [repo.name, repo.path, repo.gitUrl]
    );
    return this.mapRowToRepo(result.rows[0]);
  }

  async getById(id: string): Promise<Repo | null> {
    const result = await this.client.query(`SELECT * FROM repos WHERE id = $1`, [id]);
    return result.rows.length > 0 ? this.mapRowToRepo(result.rows[0]) : null;
  }

  async getByPath(path: string): Promise<Repo | null> {
    const result = await this.client.query(`SELECT * FROM repos WHERE path = $1`, [path]);
    return result.rows.length > 0 ? this.mapRowToRepo(result.rows[0]) : null;
  }

  async getAll(): Promise<Repo[]> {
    const result = await this.client.query(`SELECT * FROM repos ORDER BY created_at DESC`);
    return result.rows.map(this.mapRowToRepo);
  }

  async update(id: string, updates: Partial<Repo>): Promise<Repo> {
    const entries = Object.entries(updates).filter(([, v]) => v !== undefined);
    const fields = entries.map(([k], i) => `${k.replace(/([A-Z])/g, '_$1').toLowerCase()} = $${i + 1}`);
    const values = entries.map(([, v]) => v);
    values.push(id);

    const result = await this.client.query(
      `UPDATE repos SET ${fields.join(', ')}, updated_at = NOW() WHERE id = $${values.length} RETURNING *`,
      values
    );
    return this.mapRowToRepo(result.rows[0]);
  }

  async delete(id: string): Promise<void> {
    await this.client.query(`DELETE FROM repos WHERE id = $1`, [id]);
  }

  private mapRowToRepo(row: any): Repo {
    return {
      id: row.id,
      name: row.name,
      path: row.path,
      gitUrl: row.git_url,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      lastIndexedAt: row.last_indexed_at,
      fileCount: row.file_count,
      symbolCount: row.symbol_count
    };
  }
}

class PostgresFileAdapter implements FileAdapter {
  constructor(private client: Client) {}

  async create(file: FileCreate): Promise<File> {
    const result = await this.client.query(
      `INSERT INTO files (repo_id, path, language, content_hash, size_bytes, git_modified_at, git_author, git_commit_msg) 
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *`,
      [file.repoId, file.path, file.language, file.contentHash, file.sizeBytes, file.gitModifiedAt, file.gitAuthor, file.gitCommitMsg]
    );
    return this.mapRowToFile(result.rows[0]);
  }

  async getById(id: string): Promise<File | null> {
    const result = await this.client.query(`SELECT * FROM files WHERE id = $1`, [id]);
    return result.rows.length > 0 ? this.mapRowToFile(result.rows[0]) : null;
  }

  async getByRepoId(repoId: string): Promise<File[]> {
    const result = await this.client.query(`SELECT * FROM files WHERE repo_id = $1`, [repoId]);
    return result.rows.map(this.mapRowToFile);
  }

  async getByPath(repoId: string, path: string): Promise<File | null> {
    const result = await this.client.query(`SELECT * FROM files WHERE repo_id = $1 AND path = $2`, [repoId, path]);
    return result.rows.length > 0 ? this.mapRowToFile(result.rows[0]) : null;
  }

  async update(id: string, updates: Partial<File>): Promise<File> {
    const entries = Object.entries(updates).filter(([, v]) => v !== undefined);
    const fields = entries.map(([k], i) => `${k.replace(/([A-Z])/g, '_$1').toLowerCase()} = $${i + 1}`);
    const values = entries.map(([, v]) => v);
    values.push(id);

    const result = await this.client.query(
      `UPDATE files SET ${fields.join(', ')}, updated_at = NOW() WHERE id = $${values.length} RETURNING *`,
      values
    );
    return this.mapRowToFile(result.rows[0]);
  }

  async delete(id: string): Promise<void> {
    await this.client.query(`DELETE FROM files WHERE id = $1`, [id]);
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    await this.client.query(`DELETE FROM files WHERE repo_id = $1`, [repoId]);
  }

  private mapRowToFile(row: any): File {
    return {
      id: row.id,
      repoId: row.repo_id,
      path: row.path,
      language: row.language,
      contentHash: row.content_hash,
      sizeBytes: row.size_bytes,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      gitModifiedAt: row.git_modified_at,
      gitAuthor: row.git_author,
      gitCommitMsg: row.git_commit_msg
    };
  }
}

class PostgresSymbolAdapter implements SymbolAdapter {
  constructor(private client: Client) {}

  async create(symbol: SymbolCreate): Promise<Symbol> {
    const result = await this.client.query(
      `INSERT INTO symbols (file_id, name, type, kind, line, column, end_line, end_column, parent_id, is_exported) 
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING *`,
      [symbol.fileId, symbol.name, symbol.type, symbol.kind, symbol.line, symbol.column, symbol.endLine, symbol.endColumn, symbol.parentId, symbol.isExported]
    );
    return this.mapRowToSymbol(result.rows[0]);
  }

  async getById(id: string): Promise<Symbol | null> {
    const result = await this.client.query(`SELECT * FROM symbols WHERE id = $1`, [id]);
    return result.rows.length > 0 ? this.mapRowToSymbol(result.rows[0]) : null;
  }

  async getByFileId(fileId: string): Promise<Symbol[]> {
    const result = await this.client.query(`SELECT * FROM symbols WHERE file_id = $1`, [fileId]);
    return result.rows.map(this.mapRowToSymbol);
  }

  async getByRepoId(repoId: string): Promise<Symbol[]> {
    const result = await this.client.query(
      `SELECT s.* FROM symbols s JOIN files f ON s.file_id = f.id WHERE f.repo_id = $1`,
      [repoId]
    );
    return result.rows.map(this.mapRowToSymbol);
  }

  async searchByName(repoId: string, name: string): Promise<Symbol[]> {
    const result = await this.client.query(
      `SELECT s.* FROM symbols s JOIN files f ON s.file_id = f.id 
       WHERE f.repo_id = $1 AND s.name ILIKE $2 ORDER BY s.name`,
      [repoId, `%${name}%`]
    );
    return result.rows.map(this.mapRowToSymbol);
  }

  async deleteByFileId(fileId: string): Promise<void> {
    await this.client.query(`DELETE FROM symbols WHERE file_id = $1`, [fileId]);
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    await this.client.query(`DELETE FROM symbols s USING files f WHERE s.file_id = f.id AND f.repo_id = $1`, [repoId]);
  }

  private mapRowToSymbol(row: any): Symbol {
    return {
      id: row.id,
      fileId: row.file_id,
      name: row.name,
      type: row.type as SymbolType,
      kind: row.kind,
      line: row.line,
      column: row.column,
      endLine: row.end_line,
      endColumn: row.end_column,
      parentId: row.parent_id,
      isExported: row.is_exported
    };
  }
}

class PostgresEmbeddingAdapter implements EmbeddingAdapter {
  constructor(private client: Client) {}

  async create(embedding: EmbeddingCreate): Promise<Embedding> {
    const result = await this.client.query(
      `INSERT INTO embeddings (file_id, chunk_index, content, embedding, token_count) 
       VALUES ($1, $2, $3, $4, $5) RETURNING *`,
      [embedding.fileId, embedding.chunkIndex, embedding.content, `[${embedding.embedding.join(',')}]`, embedding.tokenCount]
    );
    return this.mapRowToEmbedding(result.rows[0]);
  }

  async getById(id: string): Promise<Embedding | null> {
    const result = await this.client.query(`SELECT * FROM embeddings WHERE id = $1`, [id]);
    return result.rows.length > 0 ? this.mapRowToEmbedding(result.rows[0]) : null;
  }

  async getByFileId(fileId: string): Promise<Embedding[]> {
    const result = await this.client.query(`SELECT * FROM embeddings WHERE file_id = $1 ORDER BY chunk_index`, [fileId]);
    return result.rows.map(this.mapRowToEmbedding);
  }

  async search(embedding: number[], limit: number, repoId?: string): Promise<EmbeddingSearchResult[]> {
    const query = repoId ? `
      SELECT e.*, 1 - (e.embedding <=> $1) as similarity
      FROM embeddings e
      JOIN files f ON e.file_id = f.id
      WHERE f.repo_id = $2
      ORDER BY similarity DESC
      LIMIT $3
    ` : `
      SELECT e.*, 1 - (e.embedding <=> $1) as similarity
      FROM embeddings e
      ORDER BY similarity DESC
      LIMIT $2
    `;

    const params = repoId ? [`[${embedding.join(',')}]`, repoId, limit] : [`[${embedding.join(',')}]`, limit];
    const result = await this.client.query(query, params);

    return result.rows.map(row => ({
      embedding: this.mapRowToEmbedding(row),
      similarity: parseFloat(row.similarity)
    }));
  }

  async update(id: string, updates: Partial<Embedding>): Promise<Embedding> {
    const entries = Object.entries(updates).filter(([, v]) => v !== undefined);
    const fields = entries.map(([k], i) => `${k.replace(/([A-Z])/g, '_$1').toLowerCase()} = $${i + 1}`);
    const values = entries.map(([, v]) => v);
    values.push(id);

    const result = await this.client.query(
      `UPDATE embeddings SET ${fields.join(', ')} WHERE id = $${values.length} RETURNING *`,
      values
    );
    return this.mapRowToEmbedding(result.rows[0]);
  }

  async deleteByFileId(fileId: string): Promise<void> {
    await this.client.query(`DELETE FROM embeddings WHERE file_id = $1`, [fileId]);
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    await this.client.query(`DELETE FROM embeddings e USING files f WHERE e.file_id = f.id AND f.repo_id = $1`, [repoId]);
  }

  private mapRowToEmbedding(row: any): Embedding {
    return {
      id: row.id,
      fileId: row.file_id,
      chunkIndex: row.chunk_index,
      content: row.content,
      embedding: Array.isArray(row.embedding) ? row.embedding : JSON.parse(row.embedding),
      tokenCount: row.token_count,
      createdAt: row.created_at
    };
  }
}

class PostgresCallGraphAdapter implements CallGraphAdapter {
  constructor(private client: Client) {}

  async create(edge: CallGraphEdgeCreate): Promise<CallGraphEdge> {
    const result = await this.client.query(
      `INSERT INTO call_graph_edges (source_id, target_id, repo_id, call_type) 
       VALUES ($1, $2, $3, $4) RETURNING *`,
      [edge.sourceId, edge.targetId, edge.repoId, edge.callType]
    );
    return this.mapRowToEdge(result.rows[0]);
  }

  async getBySourceId(sourceId: string): Promise<CallGraphEdge[]> {
    const result = await this.client.query(`SELECT * FROM call_graph_edges WHERE source_id = $1`, [sourceId]);
    return result.rows.map(this.mapRowToEdge);
  }

  async getByTargetId(targetId: string): Promise<CallGraphEdge[]> {
    const result = await this.client.query(`SELECT * FROM call_graph_edges WHERE target_id = $1`, [targetId]);
    return result.rows.map(this.mapRowToEdge);
  }

  async getByRepoId(repoId: string): Promise<CallGraphEdge[]> {
    const result = await this.client.query(`SELECT * FROM call_graph_edges WHERE repo_id = $1`, [repoId]);
    return result.rows.map(this.mapRowToEdge);
  }

  async deleteBySymbolId(symbolId: string): Promise<void> {
    await this.client.query(`DELETE FROM call_graph_edges WHERE source_id = $1 OR target_id = $1`, [symbolId]);
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    await this.client.query(`DELETE FROM call_graph_edges WHERE repo_id = $1`, [repoId]);
  }

  private mapRowToEdge(row: any): CallGraphEdge {
    return {
      id: row.id,
      sourceId: row.source_id,
      targetId: row.target_id,
      repoId: row.repo_id,
      callType: row.call_type as CallType
    };
  }
}
