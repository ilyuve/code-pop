import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchRepos, fetchRepo, addRepo, updateRepo, deleteRepo, reindexRepo } from '../api';
import { useStore } from '../store';
import type { AddRepoForm } from '../types';

export const useRepos = () => {
  const queryClient = useQueryClient();
  const { repos, setRepos, addRepo: addRepoToStore, removeRepo, clearIndexingLogs } = useStore();

  const reposQuery = useQuery({
    queryKey: ['repos'],
    queryFn: fetchRepos,
    initialData: repos,
  });

  const addRepoMutation = useMutation({
    mutationFn: (data: { form: AddRepoForm; onSuccess?: () => void; onError?: (error: any) => void }) => 
      addRepo(data.form),
    onSuccess: (newRepo, variables) => {
      addRepoToStore(newRepo);
      queryClient.invalidateQueries({ queryKey: ['repos'] });
      variables.onSuccess?.();
    },
    onError: (error, variables) => {
      variables.onError?.(error);
    },
  });

  const deleteRepoMutation = useMutation({
    mutationFn: (id: string) => deleteRepo(id),
    onSuccess: (_, id) => {
      removeRepo(id);
      clearIndexingLogs(id);
      queryClient.invalidateQueries({ queryKey: ['repos'] });
    },
    onError: (error) => {
      const detail = (error as any)?.response?.data?.detail || error?.message || '删除仓库失败';
      alert(`删除失败: ${detail}`);
    },
  });

  const reindexMutation = useMutation({
    mutationFn: (id: string) => reindexRepo(id),
    onSuccess: (_, id) => {
      clearIndexingLogs(id);
      queryClient.invalidateQueries({ queryKey: ['repos'] });
      queryClient.invalidateQueries({ queryKey: ['repo', id, 'indexing'] });
      queryClient.invalidateQueries({ queryKey: ['indexingLogs', id] });
    },
  });

  const updateRepoMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<AddRepoForm> }) => updateRepo(id, data),
    onSuccess: (updatedRepo) => {
      queryClient.invalidateQueries({ queryKey: ['repos'] });
      queryClient.invalidateQueries({ queryKey: ['repo', updatedRepo.id] });
    },
    onError: (error) => {
      const detail = (error as any)?.response?.data?.detail || error?.message || '更新仓库失败';
      alert(`更新失败: ${detail}`);
    },
  });

  const addRepoWithCallbacks = (form: AddRepoForm, options?: { onSuccess?: () => void; onError?: (error: any) => void }) => {
    addRepoMutation.mutate({ form, ...options });
  };

  return {
    repos: reposQuery.data || repos,
    isLoading: reposQuery.isLoading,
    error: reposQuery.error,
    refetch: reposQuery.refetch,
    addRepo: addRepoWithCallbacks,
    updateRepo: updateRepoMutation.mutate,
    deleteRepo: deleteRepoMutation.mutate,
    reindex: reindexMutation.mutate,
    isAdding: addRepoMutation.isPending,
    isUpdating: updateRepoMutation.isPending,
    isDeleting: deleteRepoMutation.isPending,
    isReindexing: reindexMutation.isPending,
  };
};

export const useRepo = (id: string) => {
  const { repos } = useStore();
  const localRepo = repos.find((r) => r.id === id);

  return useQuery({
    queryKey: ['repo', id],
    queryFn: () => fetchRepo(id),
    initialData: localRepo,
    enabled: !!id,
  });
};
