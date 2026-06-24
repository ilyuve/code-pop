import axios from 'axios';
import type { Repo, SearchResult, Stats, AddRepoForm } from '../types';

const DEFAULT_API_ENDPOINT = 'http://localhost:8080/api';

const getApiEndpoint = () => {
  return localStorage.getItem('codepop-api-endpoint') || DEFAULT_API_ENDPOINT;
};

const apiClient = axios.create({
  baseURL: getApiEndpoint(),
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error);
    return Promise.reject(error);
  }
);

// Backend status -> frontend status mapping
const mapStatus = (status: string): Repo['status'] => {
  if (status === 'indexed') return 'completed';
  if (status === 'indexing') return 'indexing';
  if (status === 'error') return 'error';
  return 'indexing';
};

const mapRepo = (data: any): Repo => ({
  id: data.id,
  name: data.name,
  path: data.local_path || data.path || '',
  gitUrl: data.git_url || data.gitUrl,
  status: mapStatus(data.status),
  totalFiles: data.total_files || 0,
  indexedFiles: data.indexed_files || 0,
  fileCount: data.total_files || 0,
  symbolCount: 0,
  createdAt: data.created_at || data.createdAt,
  lastIndexedAt: data.last_indexed_at || data.lastIndexedAt,
});

const mapSearchResult = (data: any): SearchResult => ({
  repoId: data.repo_id,
  repoName: data.repo_name || '',
  filePath: data.file_path,
  lineNumber: data.line,
  code: data.content,
  score: data.score,
});

// Repository APIs
export const fetchRepos = async (): Promise<Repo[]> => {
  const response = await apiClient.get('/repos');
  return response.data.map(mapRepo);
};

export const fetchRepo = async (id: string): Promise<Repo> => {
  const response = await apiClient.get(`/repos/${id}`);
  return mapRepo(response.data);
};

export const addRepo = async (data: AddRepoForm): Promise<Repo> => {
  const response = await apiClient.post('/repos', {
    name: data.name || data.gitUrl?.split('/').pop()?.replace(/\.git$/, '') || 'repo',
    git_url: data.gitUrl,
  });
  return mapRepo(response.data);
};

export const updateRepo = async (id: string, data: Partial<AddRepoForm>): Promise<Repo> => {
  const response = await apiClient.patch(`/repos/${id}`, data);
  return mapRepo(response.data);
};

export const deleteRepo = async (id: string): Promise<void> => {
  await apiClient.delete(`/repos/${id}`);
};

export const reindexRepo = async (id: string): Promise<void> => {
  await apiClient.post(`/repos/${id}/index`);
};

export const fetchRepoFiles = async (id: string): Promise<any[]> => {
  const response = await apiClient.get(`/repos/${id}/files`);
  return response.data;
};

export const fetchRepoSymbols = async (id: string, filePath?: string): Promise<any[]> => {
  const url = filePath ? `/repos/${id}/symbols?file_path=${encodeURIComponent(filePath)}` : `/repos/${id}/symbols`;
  const response = await apiClient.get(url);
  return response.data;
};

// Search APIs
export const searchCode = async (query: string, repoId?: string, limit: number = 20): Promise<SearchResult[]> => {
  const response = await apiClient.post('/search', { query, repo_id: repoId, limit });
  return response.data.map(mapSearchResult);
};

export const searchSymbol = async (query: string, repoId?: string): Promise<any[]> => {
  const response = await apiClient.post('/search/symbol', { query, repo_id: repoId });
  return response.data;
};

export const fetchSearchHistory = async (limit: number = 10): Promise<any[]> => {
  const response = await apiClient.get(`/search/history?limit=${limit}`);
  return response.data;
};

// Health APIs
export const fetchHealth = async (): Promise<any> => {
  const response = await apiClient.get('/health');
  return response.data;
};

export default apiClient;
