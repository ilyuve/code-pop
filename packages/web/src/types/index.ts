// Repository types
export interface Repo {
  id: string;
  name: string;
  path: string;
  gitUrl?: string;
  status: 'indexing' | 'indexed' | 'completed' | 'error';
  totalFiles: number;
  indexedFiles: number;
  fileCount?: number;
  symbolCount?: number;
  createdAt: string;
  lastIndexedAt: string;
}

// Search types
export interface SearchResult {
  repoId: string;
  repoName: string;
  filePath: string;
  lineNumber: number;
  code: string;
  score: number;
}

// Settings types
export interface Settings {
  apiEndpoint: string;
  embeddingProvider: 'openai' | 'local';
  theme: 'light' | 'dark';
}

// Stats types
export interface Stats {
  totalRepos: number;
  totalFiles: number;
  recentSearches: string[];
}

// API response types
export interface ApiResponse<T> {
  data: T;
  error?: string;
}

// Form types
export interface AddRepoForm {
  name?: string;
  path?: string;
  gitUrl?: string;
}
