export interface DatabaseAdapter {
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  
  repo: RepoAdapter;
  file: FileAdapter;
  symbol: SymbolAdapter;
  embedding: EmbeddingAdapter;
  callGraph: CallGraphAdapter;
}

export interface RepoAdapter {
  create(repo: RepoCreate): Promise<Repo>;
  getById(id: string): Promise<Repo | null>;
  getByPath(path: string): Promise<Repo | null>;
  getAll(): Promise<Repo[]>;
  update(id: string, updates: Partial<Repo>): Promise<Repo>;
  delete(id: string): Promise<void>;
}

export interface FileAdapter {
  create(file: FileCreate): Promise<File>;
  getById(id: string): Promise<File | null>;
  getByRepoId(repoId: string): Promise<File[]>;
  getByPath(repoId: string, path: string): Promise<File | null>;
  update(id: string, updates: Partial<File>): Promise<File>;
  delete(id: string): Promise<void>;
  deleteByRepoId(repoId: string): Promise<void>;
}

export interface SymbolAdapter {
  create(symbol: SymbolCreate): Promise<Symbol>;
  getById(id: string): Promise<Symbol | null>;
  getByFileId(fileId: string): Promise<Symbol[]>;
  getByRepoId(repoId: string): Promise<Symbol[]>;
  searchByName(repoId: string, name: string): Promise<Symbol[]>;
  deleteByFileId(fileId: string): Promise<void>;
  deleteByRepoId(repoId: string): Promise<void>;
}

export interface EmbeddingAdapter {
  create(embedding: EmbeddingCreate): Promise<Embedding>;
  getById(id: string): Promise<Embedding | null>;
  getByFileId(fileId: string): Promise<Embedding[]>;
  search(embedding: number[], limit: number, repoId?: string): Promise<EmbeddingSearchResult[]>;
  update(id: string, updates: Partial<Embedding>): Promise<Embedding>;
  deleteByFileId(fileId: string): Promise<void>;
  deleteByRepoId(repoId: string): Promise<void>;
}

export interface CallGraphAdapter {
  create(edge: CallGraphEdgeCreate): Promise<CallGraphEdge>;
  getBySourceId(sourceId: string): Promise<CallGraphEdge[]>;
  getByTargetId(targetId: string): Promise<CallGraphEdge[]>;
  getByRepoId(repoId: string): Promise<CallGraphEdge[]>;
  deleteBySymbolId(symbolId: string): Promise<void>;
  deleteByRepoId(repoId: string): Promise<void>;
}

export interface Repo {
  id: string;
  name: string;
  path: string;
  gitUrl?: string;
  createdAt: Date;
  updatedAt: Date;
  lastIndexedAt?: Date;
  fileCount: number;
  symbolCount: number;
}

export interface RepoCreate {
  name: string;
  path: string;
  gitUrl?: string;
}

export interface File {
  id: string;
  repoId: string;
  path: string;
  language?: string;
  contentHash?: string;
  sizeBytes?: number;
  createdAt: Date;
  updatedAt: Date;
  gitModifiedAt?: Date;
  gitAuthor?: string;
  gitCommitMsg?: string;
}

export interface FileCreate {
  repoId: string;
  path: string;
  language?: string;
  contentHash?: string;
  sizeBytes?: number;
  gitModifiedAt?: Date;
  gitAuthor?: string;
  gitCommitMsg?: string;
}

export interface Symbol {
  id: string;
  fileId: string;
  name: string;
  type: SymbolType;
  kind: string;
  line: number;
  column: number;
  endLine?: number;
  endColumn?: number;
  parentId?: string;
  isExported: boolean;
}

export type SymbolType = 'function' | 'class' | 'interface' | 'variable' | 'type' | 'enum' | 'method' | 'property';

export interface SymbolCreate {
  fileId: string;
  name: string;
  type: SymbolType;
  kind: string;
  line: number;
  column: number;
  endLine?: number;
  endColumn?: number;
  parentId?: string;
  isExported: boolean;
}

export interface Embedding {
  id: string;
  fileId: string;
  chunkIndex: number;
  content: string;
  embedding: number[];
  tokenCount: number;
  createdAt: Date;
}

export interface EmbeddingCreate {
  fileId: string;
  chunkIndex: number;
  content: string;
  embedding: number[];
  tokenCount: number;
}

export interface EmbeddingSearchResult {
  embedding: Embedding;
  similarity: number;
}

export interface CallGraphEdge {
  id: string;
  sourceId: string;
  targetId: string;
  repoId: string;
  callType: CallType;
}

export type CallType = 'direct' | 'indirect' | 'inheritance' | 'implementation';

export interface CallGraphEdgeCreate {
  sourceId: string;
  targetId: string;
  repoId: string;
  callType: CallType;
}
