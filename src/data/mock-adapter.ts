import { DatabaseAdapter, RepoAdapter, FileAdapter, SymbolAdapter, EmbeddingAdapter, CallGraphAdapter, Repo, RepoCreate, File, FileCreate, Symbol, SymbolCreate, Embedding, EmbeddingCreate, EmbeddingSearchResult, CallGraphEdge, CallGraphEdgeCreate, SymbolType, CallType } from './adapter';

export class MockAdapter implements DatabaseAdapter {
  private repoAdapter: MockRepoAdapter;
  private fileAdapter: MockFileAdapter;
  private symbolAdapter: MockSymbolAdapter;
  private embeddingAdapter: MockEmbeddingAdapter;
  private callGraphAdapter: MockCallGraphAdapter;

  constructor() {
    this.repoAdapter = new MockRepoAdapter();
    this.fileAdapter = new MockFileAdapter();
    this.symbolAdapter = new MockSymbolAdapter();
    this.embeddingAdapter = new MockEmbeddingAdapter();
    this.callGraphAdapter = new MockCallGraphAdapter();
  }

  async connect(): Promise<void> {}
  async disconnect(): Promise<void> {}

  get repo(): RepoAdapter { return this.repoAdapter; }
  get file(): FileAdapter { return this.fileAdapter; }
  get symbol(): SymbolAdapter { return this.symbolAdapter; }
  get embedding(): EmbeddingAdapter { return this.embeddingAdapter; }
  get callGraph(): CallGraphAdapter { return this.callGraphAdapter; }
}

class MockRepoAdapter implements RepoAdapter {
  private repos: Map<string, Repo> = new Map();

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(repo: RepoCreate): Promise<Repo> {
    const id = this.generateId();
    const now = new Date();
    const newRepo: Repo = {
      id,
      name: repo.name,
      path: repo.path,
      gitUrl: repo.gitUrl,
      createdAt: now,
      updatedAt: now,
      lastIndexedAt: undefined,
      fileCount: 0,
      symbolCount: 0
    };
    this.repos.set(id, newRepo);
    return newRepo;
  }

  async getById(id: string): Promise<Repo | null> {
    return this.repos.get(id) || null;
  }

  async getByPath(path: string): Promise<Repo | null> {
    for (const repo of this.repos.values()) {
      if (repo.path === path) return repo;
    }
    return null;
  }

  async getAll(): Promise<Repo[]> {
    return Array.from(this.repos.values()).sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime());
  }

  async update(id: string, updates: Partial<Repo>): Promise<Repo> {
    const repo = this.repos.get(id);
    if (!repo) throw new Error('Repo not found');
    
    const updated: Repo = { ...repo, ...updates, updatedAt: new Date() };
    this.repos.set(id, updated);
    return updated;
  }

  async delete(id: string): Promise<void> {
    this.repos.delete(id);
  }
}

class MockFileAdapter implements FileAdapter {
  private files: Map<string, File> = new Map();

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(file: FileCreate): Promise<File> {
    const id = this.generateId();
    const now = new Date();
    const newFile: File = {
      id,
      repoId: file.repoId,
      path: file.path,
      language: file.language,
      contentHash: file.contentHash,
      sizeBytes: file.sizeBytes,
      createdAt: now,
      updatedAt: now,
      gitModifiedAt: file.gitModifiedAt,
      gitAuthor: file.gitAuthor,
      gitCommitMsg: file.gitCommitMsg
    };
    this.files.set(id, newFile);
    return newFile;
  }

  async getById(id: string): Promise<File | null> {
    return this.files.get(id) || null;
  }

  async getByRepoId(repoId: string): Promise<File[]> {
    return Array.from(this.files.values()).filter(f => f.repoId === repoId);
  }

  async getByPath(repoId: string, path: string): Promise<File | null> {
    for (const file of this.files.values()) {
      if (file.repoId === repoId && file.path === path) return file;
    }
    return null;
  }

  async update(id: string, updates: Partial<File>): Promise<File> {
    const file = this.files.get(id);
    if (!file) throw new Error('File not found');
    
    const updated: File = { ...file, ...updates, updatedAt: new Date() };
    this.files.set(id, updated);
    return updated;
  }

  async delete(id: string): Promise<void> {
    this.files.delete(id);
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    for (const [id, file] of this.files) {
      if (file.repoId === repoId) {
        this.files.delete(id);
      }
    }
  }
}

class MockSymbolAdapter implements SymbolAdapter {
  private symbols: Map<string, Symbol> = new Map();

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(symbol: SymbolCreate): Promise<Symbol> {
    const id = this.generateId();
    const newSymbol: Symbol = {
      id,
      fileId: symbol.fileId,
      name: symbol.name,
      type: symbol.type,
      kind: symbol.kind,
      line: symbol.line,
      column: symbol.column,
      endLine: symbol.endLine,
      endColumn: symbol.endColumn,
      parentId: symbol.parentId,
      isExported: symbol.isExported
    };
    this.symbols.set(id, newSymbol);
    return newSymbol;
  }

  async getById(id: string): Promise<Symbol | null> {
    return this.symbols.get(id) || null;
  }

  async getByFileId(fileId: string): Promise<Symbol[]> {
    return Array.from(this.symbols.values()).filter(s => s.fileId === fileId);
  }

  async getByRepoId(repoId: string): Promise<Symbol[]> {
    return Array.from(this.symbols.values()).filter(s => s.fileId.startsWith(repoId));
  }

  async searchByName(repoId: string, name: string): Promise<Symbol[]> {
    return Array.from(this.symbols.values())
      .filter(s => s.fileId.startsWith(repoId) && s.name.toLowerCase().includes(name.toLowerCase()))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  async deleteByFileId(fileId: string): Promise<void> {
    for (const [id, symbol] of this.symbols) {
      if (symbol.fileId === fileId) {
        this.symbols.delete(id);
      }
    }
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    for (const [id, symbol] of this.symbols) {
      if (symbol.fileId.startsWith(repoId)) {
        this.symbols.delete(id);
      }
    }
  }
}

class MockEmbeddingAdapter implements EmbeddingAdapter {
  private embeddings: Map<string, Embedding> = new Map();

  private generateId(): string {
    return crypto.randomUUID();
  }

  private calculateSimilarity(a: number[], b: number[]): number {
    const dotProduct = a.reduce((sum, val, i) => sum + val * (b[i] || 0), 0);
    const magA = Math.sqrt(a.reduce((sum, val) => sum + val * val, 0));
    const magB = Math.sqrt(b.reduce((sum, val) => sum + val * val, 0));
    return magA && magB ? dotProduct / (magA * magB) : 0;
  }

  async create(embedding: EmbeddingCreate): Promise<Embedding> {
    const id = this.generateId();
    const newEmbedding: Embedding = {
      id,
      fileId: embedding.fileId,
      chunkIndex: embedding.chunkIndex,
      content: embedding.content,
      embedding: embedding.embedding,
      tokenCount: embedding.tokenCount,
      createdAt: new Date()
    };
    this.embeddings.set(id, newEmbedding);
    return newEmbedding;
  }

  async getById(id: string): Promise<Embedding | null> {
    return this.embeddings.get(id) || null;
  }

  async getByFileId(fileId: string): Promise<Embedding[]> {
    return Array.from(this.embeddings.values())
      .filter(e => e.fileId === fileId)
      .sort((a, b) => a.chunkIndex - b.chunkIndex);
  }

  async search(embedding: number[], limit: number, repoId?: string): Promise<EmbeddingSearchResult[]> {
    let results = Array.from(this.embeddings.values());
    
    if (repoId) {
      results = results.filter(e => e.fileId.startsWith(repoId));
    }

    const scored = results.map(e => ({
      embedding: e,
      similarity: this.calculateSimilarity(embedding, e.embedding)
    }));

    return scored.sort((a, b) => b.similarity - a.similarity).slice(0, limit);
  }

  async update(id: string, updates: Partial<Embedding>): Promise<Embedding> {
    const embedding = this.embeddings.get(id);
    if (!embedding) throw new Error('Embedding not found');
    
    const updated: Embedding = { ...embedding, ...updates };
    this.embeddings.set(id, updated);
    return updated;
  }

  async deleteByFileId(fileId: string): Promise<void> {
    for (const [id, embedding] of this.embeddings) {
      if (embedding.fileId === fileId) {
        this.embeddings.delete(id);
      }
    }
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    for (const [id, embedding] of this.embeddings) {
      if (embedding.fileId.startsWith(repoId)) {
        this.embeddings.delete(id);
      }
    }
  }
}

class MockCallGraphAdapter implements CallGraphAdapter {
  private edges: Map<string, CallGraphEdge> = new Map();

  private generateId(): string {
    return crypto.randomUUID();
  }

  async create(edge: CallGraphEdgeCreate): Promise<CallGraphEdge> {
    const id = this.generateId();
    const newEdge: CallGraphEdge = {
      id,
      sourceId: edge.sourceId,
      targetId: edge.targetId,
      repoId: edge.repoId,
      callType: edge.callType
    };
    this.edges.set(id, newEdge);
    return newEdge;
  }

  async getById(id: string): Promise<CallGraphEdge | null> {
    return this.edges.get(id) || null;
  }

  async getBySourceId(sourceId: string): Promise<CallGraphEdge[]> {
    return Array.from(this.edges.values()).filter(e => e.sourceId === sourceId);
  }

  async getByTargetId(targetId: string): Promise<CallGraphEdge[]> {
    return Array.from(this.edges.values()).filter(e => e.targetId === targetId);
  }

  async getByRepoId(repoId: string): Promise<CallGraphEdge[]> {
    return Array.from(this.edges.values()).filter(e => e.repoId === repoId);
  }

  async deleteBySymbolId(symbolId: string): Promise<void> {
    for (const [id, edge] of this.edges) {
      if (edge.sourceId === symbolId || edge.targetId === symbolId) {
        this.edges.delete(id);
      }
    }
  }

  async deleteByRepoId(repoId: string): Promise<void> {
    for (const [id, edge] of this.edges) {
      if (edge.repoId === repoId) {
        this.edges.delete(id);
      }
    }
  }
}
