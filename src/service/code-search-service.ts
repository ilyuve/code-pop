import { DatabaseAdapter, EmbeddingSearchResult } from '../data/adapter';
import { initAdapters, AdapterFactory, DatabaseConfig } from '../data/adapter-factory';

export class CodeSearchService {
  private db: DatabaseAdapter;

  constructor(db: DatabaseAdapter) {
    this.db = db;
  }

  static async create(config: DatabaseConfig): Promise<CodeSearchService> {
    await initAdapters();
    const db = await AdapterFactory.create(config);
    await db.connect();
    return new CodeSearchService(db);
  }

  async close(): Promise<void> {
    await this.db.disconnect();
  }

  async createRepo(name: string, path: string, gitUrl?: string) {
    return this.db.repo.create({ name, path, gitUrl });
  }

  async getRepo(id: string) {
    return this.db.repo.getById(id);
  }

  async getAllRepos() {
    return this.db.repo.getAll();
  }

  async deleteRepo(id: string) {
    return this.db.repo.delete(id);
  }

  async createFile(repoId: string, path: string, language?: string, contentHash?: string) {
    return this.db.file.create({ repoId, path, language, contentHash });
  }

  async getFilesByRepo(repoId: string) {
    return this.db.file.getByRepoId(repoId);
  }

  async createSymbol(fileId: string, name: string, type: string, line: number, column: number, isExported: boolean) {
    return this.db.symbol.create({ fileId, name, type: type as any, kind: type, line, column, isExported });
  }

  async searchSymbols(repoId: string, name: string) {
    return this.db.symbol.searchByName(repoId, name);
  }

  async createEmbedding(fileId: string, chunkIndex: number, content: string, embedding: number[], tokenCount: number) {
    return this.db.embedding.create({ fileId, chunkIndex, content, embedding, tokenCount });
  }

  async searchByEmbedding(queryEmbedding: number[], limit: number = 10, repoId?: string): Promise<EmbeddingSearchResult[]> {
    return this.db.embedding.search(queryEmbedding, limit, repoId);
  }

  async createCallGraphEdge(sourceId: string, targetId: string, repoId: string, callType: string) {
    return this.db.callGraph.create({ sourceId, targetId, repoId, callType: callType as any });
  }

  async getCallGraphByRepo(repoId: string) {
    return this.db.callGraph.getByRepoId(repoId);
  }
}
