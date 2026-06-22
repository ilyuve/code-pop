import * as sqlite3 from 'sqlite3';
import { DatabaseAdapter, RepoAdapter, FileAdapter, SymbolAdapter, EmbeddingAdapter, CallGraphAdapter, Repo, RepoCreate, File, FileCreate, Symbol, SymbolCreate, Embedding, EmbeddingCreate, EmbeddingSearchResult, CallGraphEdge, CallGraphEdgeCreate, SymbolType, CallType } from './adapter';

export class SQLiteAdapter implements DatabaseAdapter {
  private db: sqlite3.Database;
  private repoAdapter: SQLiteRepoAdapter;
  private fileAdapter: SQLiteFileAdapter;
  private symbolAdapter: SQLiteSymbolAdapter;
  private embeddingAdapter: SQLiteEmbeddingAdapter;
  private callGraphAdapter: SQLiteCallGraphAdapter;

  constructor() {
    this.db = new sqlite3.Database(':memory:');
    this.repoAdapter = new SQLiteRepoAdapter(this.db);
    this.fileAdapter = new SQLiteFileAdapter(this.db);
    this.symbolAdapter = new SQLiteSymbolAdapter(this.db);
    this.embeddingAdapter = new SQLiteEmbeddingAdapter(this.db);
    this.callGraphAdapter = new SQLiteCallGraphAdapter(this.db);
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.serialize(() => {
        this.initSchema((err) => {
          if (err) reject(err);
          else resolve();
        });
      });
    });
  }

  async disconnect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.close((err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  private initSchema(callback: (err?: Error) => void): void {
    const queries = [
      `CREATE TABLE IF NOT EXISTS repos (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        path TEXT NOT NULL UNIQUE,
        git_url TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        last_indexed_at TEXT,
        file_count INTEGER DEFAULT 0,
        symbol_count INTEGER DEFAULT 0
      )`,
      `CREATE TABLE IF NOT EXISTS files (
        id TEXT PRIMARY KEY,
        repo_id TEXT,
        path TEXT NOT NULL,
        language TEXT,
        content_hash TEXT,
        size_bytes INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        git_modified_at TEXT,
        git_author TEXT,
        git_commit_msg TEXT,
        UNIQUE(repo_id, path),
        FOREIGN KEY(repo_id) REFERENCES repos(id) ON DELETE CASCADE
      )`,
      `CREATE TABLE IF NOT EXISTS symbols (
        id TEXT PRIMARY KEY,
        file_id TEXT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        kind TEXT,
        line INTEGER NOT NULL,
        column INTEGER NOT NULL,
        end_line INTEGER,
        end_column INTEGER,
        parent_id TEXT,
        is_exported INTEGER DEFAULT 0,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE,
        FOREIGN KEY(parent_id) REFERENCES symbols(id)
      )`,
      `CREATE TABLE IF NOT EXISTS embeddings (
        id TEXT PRIMARY KEY,
        file_id TEXT,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        embedding TEXT NOT NULL,
        token_count INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
      )`,
      `CREATE TABLE IF NOT EXISTS call_graph_edges (
        id TEXT PRIMARY KEY,
        source_id TEXT,
        target_id TEXT,
        repo_id TEXT,
        call_type TEXT NOT NULL,
        FOREIGN KEY(source_id) REFERENCES symbols(id) ON DELETE CASCADE,
        FOREIGN KEY(target_id) REFERENCES symbols(id) ON DELETE CASCADE,
        FOREIGN KEY(repo_id) REFERENCES repos(id) ON DELETE CASCADE
      )`,
      `CREATE INDEX IF NOT EXISTS idx_files_repo_id ON files(repo_id)`,
      `CREATE INDEX IF NOT EXISTS idx_symbols_file_id ON symbols(file_id)`,
      `CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name)`,
      `CREATE INDEX IF NOT EXISTS idx_embeddings_file_id ON embeddings(file_id)`,
      `CREATE INDEX IF NOT EXISTS idx_call_graph_source ON call_graph_edges(source_id)`,
      `CREATE INDEX IF NOT EXISTS idx_call_graph_target ON call_graph_edges(target_id)`,
      `CREATE INDEX IF NOT EXISTS idx_call_graph_repo ON call_graph_edges(repo_id)`
    ];

    let completed = 0;
    for (const query of queries) {
      this.db.run(query, (err) => {
        if (err) return callback(err);
        completed++;
        if (completed === queries.length) callback();
      });
    }
  }

  get repo(): RepoAdapter { return this.repoAdapter; }
  get file(): FileAdapter { return this.fileAdapter; }
  get symbol(): SymbolAdapter { return this.symbolAdapter; }
  get embedding(): EmbeddingAdapter { return this.embeddingAdapter; }
  get callGraph(): CallGraphAdapter { return this.callGraphAdapter; }
}

class SQLiteRepoAdapter implements RepoAdapter {
  constructor(private db: sqlite3.Database) {}

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(repo: RepoCreate): Promise<Repo> {
    const id = this.generateId();
    const now = new Date().toISOString();
    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO repos (id, name, path, git_url, created_at, updated_at, file_count, symbol_count)
         VALUES (?, ?, ?, ?, ?, ?, 0, 0)`,
        [id, repo.name, repo.path, repo.gitUrl || null, now, now],
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to create repo'));
          }
        }
      );
    });
  }

  async getById(id: string): Promise<Repo | null> {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM repos WHERE id = ?`, [id], (err, row) => {
        if (err) reject(err);
        else resolve(row ? this.mapRowToRepo(row) : null);
      });
    });
  }

  async getByPath(path: string): Promise<Repo | null> {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM repos WHERE path = ?`, [path], (err, row) => {
        if (err) reject(err);
        else resolve(row ? this.mapRowToRepo(row) : null);
      });
    });
  }

  async getAll(): Promise<Repo[]> {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM repos ORDER BY created_at DESC`, (err, rows) => {
        if (err) reject(err);
        else resolve(rows.map(this.mapRowToRepo));
      });
    });
  }

  async update(id: string, updates: Partial<Repo>): Promise<Repo> {
    const fields: string[] = [];
    const values: unknown[] = [];
    
    if (updates.name !== undefined) { fields.push('name = ?'); values.push(updates.name); }
    if (updates.path !== undefined) { fields.push('path = ?'); values.push(updates.path); }
    if (updates.gitUrl !== undefined) { fields.push('git_url = ?'); values.push(updates.gitUrl); }
    if (updates.lastIndexedAt !== undefined) { fields.push('last_indexed_at = ?'); values.push(updates.lastIndexedAt.toISOString()); }
    if (updates.fileCount !== undefined) { fields.push('file_count = ?'); values.push(updates.fileCount); }
    if (updates.symbolCount !== undefined) { fields.push('symbol_count = ?'); values.push(updates.symbolCount); }
    
    fields.push('updated_at = ?');
    values.push(new Date().toISOString());
    values.push(id);

    return new Promise((resolve, reject) => {
      this.db.run(
        `UPDATE repos SET ${fields.join(', ')} WHERE id = ?`,
        values,
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to update repo'));
          }
        }
      );
    });
  }

  async delete(id: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM repos WHERE id = ?`, [id], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  private mapRowToRepo(row: any): Repo {
    return {
      id: row.id,
      name: row.name,
      path: row.path,
      gitUrl: row.git_url || undefined,
      createdAt: new Date(row.created_at),
      updatedAt: new Date(row.updated_at),
      lastIndexedAt: row.last_indexed_at ? new Date(row.last_indexed_at) : undefined,
      fileCount: row.file_count,
      symbolCount: row.symbol_count
    };
  }
}

class SQLiteFileAdapter implements FileAdapter {
  constructor(private db: sqlite3.Database) {}

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(file: FileCreate): Promise<File> {
    const id = this.generateId();
    const now = new Date().toISOString();
    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO files (id, repo_id, path, language, content_hash, size_bytes, created_at, updated_at, git_modified_at, git_author, git_commit_msg)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [id, file.repoId, file.path, file.language || null, file.contentHash || null, file.sizeBytes || null, now, now, file.gitModifiedAt?.toISOString() || null, file.gitAuthor || null, file.gitCommitMsg || null],
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to create file'));
          }
        }
      );
    });
  }

  async getById(id: string): Promise<File | null> {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM files WHERE id = ?`, [id], (err, row) => {
        if (err) reject(err);
        else resolve(row ? this.mapRowToFile(row) : null);
      });
    });
  }

  async getByRepoId(repoId: string): Promise<File[]> {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM files WHERE repo_id = ?`, [repoId], (err, rows) => {
        if (err) reject(err);
        else resolve(rows.map(this.mapRowToFile));
      });
    });
  }

  async getByPath(repoId: string, path: string): Promise<File | null> {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM files WHERE repo_id = ? AND path = ?`, [repoId, path], (err, row) => {
        if (err) reject(err);
        else resolve(row ? this.mapRowToFile(row) : null);
      });
    });
  }

  async update(id: string, updates: Partial<File>): Promise<File> {
    const fields: string[] = [];
    const values: unknown[] = [];
    
    if (updates.language !== undefined) { fields.push('language = ?'); values.push(updates.language); }
    if (updates.contentHash !== undefined) { fields.push('content_hash = ?'); values.push(updates.contentHash); }
    if (updates.sizeBytes !== undefined) { fields.push('size_bytes = ?'); values.push(updates.sizeBytes); }
    if (updates.gitModifiedAt !== undefined) { fields.push('git_modified_at = ?'); values.push(updates.gitModifiedAt.toISOString()); }
    if (updates.gitAuthor !== undefined) { fields.push('git_author = ?'); values.push(updates.gitAuthor); }
    if (updates.gitCommitMsg !== undefined) { fields.push('git_commit_msg = ?'); values.push(updates.gitCommitMsg); }
    
    fields.push('updated_at = ?');
    values.push(new Date().toISOString());
    values.push(id);

    return new Promise((resolve, reject) => {
      this.db.run(
        `UPDATE files SET ${fields.join(', ')} WHERE id = ?`,
        values,
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to create file'));
          }
        }
      );
    });
  }

  async delete(id: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM files WHERE id = ?`, [id], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM files WHERE repo_id = ?`, [repoId], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  private mapRowToFile(row: any): File {
    return {
      id: row.id,
      repoId: row.repo_id,
      path: row.path,
      language: row.language || undefined,
      contentHash: row.content_hash || undefined,
      sizeBytes: row.size_bytes || undefined,
      createdAt: new Date(row.created_at),
      updatedAt: new Date(row.updated_at),
      gitModifiedAt: row.git_modified_at ? new Date(row.git_modified_at) : undefined,
      gitAuthor: row.git_author || undefined,
      gitCommitMsg: row.git_commit_msg || undefined
    };
  }
}

class SQLiteSymbolAdapter implements SymbolAdapter {
  constructor(private db: sqlite3.Database) {}

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(symbol: SymbolCreate): Promise<Symbol> {
    const id = this.generateId();
    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO symbols (id, file_id, name, type, kind, line, column, end_line, end_column, parent_id, is_exported)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        [id, symbol.fileId, symbol.name, symbol.type, symbol.kind, symbol.line, symbol.column, symbol.endLine || null, symbol.endColumn || null, symbol.parentId || null, symbol.isExported ? 1 : 0],
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to create file'));
          }
        }
      );
    });
  }

  async getById(id: string): Promise<Symbol | null> {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM symbols WHERE id = ?`, [id], (err, row) => {
        if (err) reject(err);
        else resolve(row ? this.mapRowToSymbol(row) : null);
      });
    });
  }

  async getByFileId(fileId: string): Promise<Symbol[]> {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM symbols WHERE file_id = ?`, [fileId], (err, rows) => {
        if (err) reject(err);
        else resolve(rows.map(this.mapRowToSymbol));
      });
    });
  }

  async getByRepoId(repoId: string): Promise<Symbol[]> {
    return new Promise((resolve, reject) => {
      this.db.all(
        `SELECT s.* FROM symbols s JOIN files f ON s.file_id = f.id WHERE f.repo_id = ?`,
        [repoId],
        (err, rows) => {
          if (err) reject(err);
          else resolve(rows.map(this.mapRowToSymbol));
        }
      );
    });
  }

  async searchByName(repoId: string, name: string): Promise<Symbol[]> {
    return new Promise((resolve, reject) => {
      this.db.all(
        `SELECT s.* FROM symbols s JOIN files f ON s.file_id = f.id 
         WHERE f.repo_id = ? AND s.name LIKE ? ORDER BY s.name`,
        [repoId, `%${name}%`],
        (err, rows) => {
          if (err) reject(err);
          else resolve(rows.map(this.mapRowToSymbol));
        }
      );
    });
  }

  async deleteByFileId(fileId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM symbols WHERE file_id = ?`, [fileId], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM symbols WHERE file_id IN (SELECT id FROM files WHERE repo_id = ?)`, [repoId], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
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
      endLine: row.end_line || undefined,
      endColumn: row.end_column || undefined,
      parentId: row.parent_id || undefined,
      isExported: row.is_exported === 1
    };
  }
}

class SQLiteEmbeddingAdapter implements EmbeddingAdapter {
  constructor(private db: sqlite3.Database) {}

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(embedding: EmbeddingCreate): Promise<Embedding> {
    const id = this.generateId();
    const now = new Date().toISOString();
    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO embeddings (id, file_id, chunk_index, content, embedding, token_count, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [id, embedding.fileId, embedding.chunkIndex, embedding.content, JSON.stringify(embedding.embedding), embedding.tokenCount, now],
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to create file'));
          }
        }
      );
    });
  }

  async getById(id: string): Promise<Embedding | null> {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM embeddings WHERE id = ?`, [id], (err, row) => {
        if (err) reject(err);
        else resolve(row ? this.mapRowToEmbedding(row) : null);
      });
    });
  }

  async getByFileId(fileId: string): Promise<Embedding[]> {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM embeddings WHERE file_id = ? ORDER BY chunk_index`, [fileId], (err, rows) => {
        if (err) reject(err);
        else resolve(rows.map(this.mapRowToEmbedding));
      });
    });
  }

  async search(embedding: number[], limit: number, repoId?: string): Promise<EmbeddingSearchResult[]> {
    return new Promise((resolve, reject) => {
      const query = repoId ? `
        SELECT e.* FROM embeddings e
        JOIN files f ON e.file_id = f.id
        WHERE f.repo_id = ?
        ORDER BY (embedding) DESC
        LIMIT ?
      ` : `
        SELECT e.* FROM embeddings e
        ORDER BY (embedding) DESC
        LIMIT ?
      `;

      const params = repoId ? [repoId, limit] : [limit];
      this.db.all(query, params, (err, rows: any[]) => {
        if (err) reject(err);
        else {
          const results = rows.map((row: any) => ({
            embedding: this.mapRowToEmbedding(row),
            similarity: this.calculateSimilarity(embedding, JSON.parse(row.embedding))
          }));
          results.sort((a, b) => b.similarity - a.similarity);
          resolve(results.slice(0, limit));
        }
      });
    });
  }

  private calculateSimilarity(a: number[], b: number[]): number {
    const dotProduct = a.reduce((sum, val, i) => sum + val * (b[i] || 0), 0);
    const magA = Math.sqrt(a.reduce((sum, val) => sum + val * val, 0));
    const magB = Math.sqrt(b.reduce((sum, val) => sum + val * val, 0));
    return magA && magB ? dotProduct / (magA * magB) : 0;
  }

  async update(id: string, updates: Partial<Embedding>): Promise<Embedding> {
    const fields: string[] = [];
    const values: unknown[] = [];
    
    if (updates.chunkIndex !== undefined) { fields.push('chunk_index = ?'); values.push(updates.chunkIndex); }
    if (updates.content !== undefined) { fields.push('content = ?'); values.push(updates.content); }
    if (updates.embedding !== undefined) { fields.push('embedding = ?'); values.push(JSON.stringify(updates.embedding)); }
    if (updates.tokenCount !== undefined) { fields.push('token_count = ?'); values.push(updates.tokenCount); }
    
    values.push(id);

    return new Promise((resolve, reject) => {
      this.db.run(
        `UPDATE embeddings SET ${fields.join(', ')} WHERE id = ?`,
        values,
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to create file'));
          }
        }
      );
    });
  }

  async deleteByFileId(fileId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM embeddings WHERE file_id = ?`, [fileId], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM embeddings WHERE file_id IN (SELECT id FROM files WHERE repo_id = ?)`, [repoId], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  private mapRowToEmbedding(row: any): Embedding {
    return {
      id: row.id,
      fileId: row.file_id,
      chunkIndex: row.chunk_index,
      content: row.content,
      embedding: JSON.parse(row.embedding),
      tokenCount: row.token_count,
      createdAt: new Date(row.created_at)
    };
  }
}

class SQLiteCallGraphAdapter implements CallGraphAdapter {
  constructor(private db: sqlite3.Database) {}

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(edge: CallGraphEdgeCreate): Promise<CallGraphEdge> {
    const id = this.generateId();
    return new Promise((resolve, reject) => {
      this.db.run(
        `INSERT INTO call_graph_edges (id, source_id, target_id, repo_id, call_type)
         VALUES (?, ?, ?, ?, ?)`,
        [id, edge.sourceId, edge.targetId, edge.repoId, edge.callType],
        async (err) => {
          if (err) reject(err);
          else {
            const result = await this.getById(id);
            if (result) resolve(result);
            else reject(new Error('Failed to create file'));
          }
        }
      );
    });
  }

  async getById(id: string): Promise<CallGraphEdge | null> {
    return new Promise((resolve, reject) => {
      this.db.get(`SELECT * FROM call_graph_edges WHERE id = ?`, [id], (err, row) => {
        if (err) reject(err);
        else resolve(row ? this.mapRowToEdge(row) : null);
      });
    });
  }

  async getBySourceId(sourceId: string): Promise<CallGraphEdge[]> {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM call_graph_edges WHERE source_id = ?`, [sourceId], (err, rows) => {
        if (err) reject(err);
        else resolve(rows.map(this.mapRowToEdge));
      });
    });
  }

  async getByTargetId(targetId: string): Promise<CallGraphEdge[]> {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM call_graph_edges WHERE target_id = ?`, [targetId], (err, rows) => {
        if (err) reject(err);
        else resolve(rows.map(this.mapRowToEdge));
      });
    });
  }

  async getByRepoId(repoId: string): Promise<CallGraphEdge[]> {
    return new Promise((resolve, reject) => {
      this.db.all(`SELECT * FROM call_graph_edges WHERE repo_id = ?`, [repoId], (err, rows) => {
        if (err) reject(err);
        else resolve(rows.map(this.mapRowToEdge));
      });
    });
  }

  async deleteBySymbolId(symbolId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM call_graph_edges WHERE source_id = ? OR target_id = ?`, [symbolId, symbolId], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.db.run(`DELETE FROM call_graph_edges WHERE repo_id = ?`, [repoId], (err) => {
        if (err) reject(err);
        else resolve();
      });
    });
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
