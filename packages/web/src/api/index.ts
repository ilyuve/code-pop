import axios from 'axios';
import type { Repo, SearchResult, Stats, AddRepoForm } from '../types';

const DEFAULT_API_ENDPOINT = 'http://localhost:3000/api';

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

// Repository APIs
export const fetchRepos = async (): Promise<Repo[]> => {
  const response = await apiClient.get('/repos');
  return response.data;
};

export const fetchRepo = async (id: string): Promise<Repo> => {
  const response = await apiClient.get(`/repos/${id}`);
  return response.data;
};

export const addRepo = async (data: AddRepoForm): Promise<Repo> => {
  const response = await apiClient.post('/repos', data);
  return response.data;
};

export const updateRepo = async (id: string, data: Partial<AddRepoForm>): Promise<Repo> => {
  const response = await apiClient.patch(`/repos/${id}`, data);
  return response.data;
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

export const fetchRepoSymbols = async (id: string): Promise<any[]> => {
  const response = await apiClient.get(`/repos/${id}/symbols`);
  return response.data;
};

// Search APIs
export const searchCode = async (query: string, repoId?: string, limit: number = 20): Promise<SearchResult[]> => {
  const response = await apiClient.post('/search', { query, repoId, limit });
  return response.data;
};

export const searchSymbol = async (query: string, repoId?: string): Promise<any[]> => {
  const response = await apiClient.post('/search/symbol', { query, repoId });
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
