import { useState, useCallback } from 'react';
import { useMutation } from '@tanstack/react-query';
import { searchCode } from '../api';
import { useStore } from '../store';

export const useSearch = () => {
  const [query, setQuery] = useState('');
  const {
    searchResults,
    setSearchResults,
    searchMeta,
    setSearchMeta,
    recentSearches,
    addRecentSearch,
  } = useStore();

  const searchMutation = useMutation({
    mutationFn: ({ query, repoId, branch }: { query: string; repoId?: string; branch?: string }) =>
      searchCode(query, repoId, branch),
    onSuccess: (response) => {
      setSearchResults(response.results);
      setSearchMeta(response.meta || null);
      if (query.trim()) {
        addRecentSearch(query);
      }
    },
  });

  const search = useCallback(
    (searchQuery: string, repoId?: string, branch?: string) => {
      setQuery(searchQuery);
      searchMutation.mutate({ query: searchQuery, repoId, branch });
    },
    [searchMutation]
  );

  const clearResults = useCallback(() => {
    setSearchResults([]);
    setSearchMeta(null);
    setQuery('');
  }, [setSearchResults, setSearchMeta]);

  return {
    query,
    setQuery,
    results: searchResults,
    meta: searchMeta,
    isSearching: searchMutation.isPending,
    error: searchMutation.error,
    search,
    clearResults,
    recentSearches,
  };
};
