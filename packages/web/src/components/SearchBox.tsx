import { useState, useCallback } from 'react';
import { Search, X } from 'lucide-react';
import { clsx } from 'clsx';

interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
  onSearch: (value: string) => void;
  placeholder?: string;
  isSearching?: boolean;
  recentSearches?: string[];
}

export const SearchBox = ({
  value,
  onChange,
  onSearch,
  placeholder = '搜索代码...',
  isSearching,
  recentSearches = [],
}: SearchBoxProps) => {
  const [isFocused, setIsFocused] = useState(false);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (value.trim()) {
        onSearch(value);
      }
    },
    [value, onSearch]
  );

  const handleClear = useCallback(() => {
    onChange('');
    onSearch('');
  }, [onChange, onSearch]);

  const handleQuickSearch = useCallback(
    (searchTerm: string) => {
      onChange(searchTerm);
      onSearch(searchTerm);
    },
    [onChange, onSearch]
  );

  return (
    <div className="relative">
      <form onSubmit={handleSubmit}>
        <div
          className={clsx(
            'relative flex items-center transition-all duration-200',
            isFocused && 'transform scale-[1.02]'
          )}
        >
          <Search
            className={clsx(
              'absolute left-4 w-5 h-5 transition-colors z-10',
              isFocused ? 'text-indigo-500' : 'text-slate-400'
            )}
          />
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder={placeholder}
            className={clsx(
              'flex-1 pl-12 pr-20 py-3 bg-white dark:bg-slate-800 border-2 rounded-l-xl',
              'text-slate-900 dark:text-white placeholder-slate-400',
              'transition-all duration-200',
              isFocused
                ? 'border-indigo-500 shadow-lg shadow-indigo-500/20'
                : 'border-slate-200 dark:border-slate-700'
            )}
          />
          {value && (
            <button
              type="button"
              onClick={handleClear}
              className="absolute right-18 p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full transition-colors"
            >
              <X className="w-4 h-4 text-slate-400" />
            </button>
          )}
          <button
            type="submit"
            disabled={isSearching || !value.trim()}
            className={clsx(
              'px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400',
              'text-white font-medium rounded-r-xl transition-colors',
              'border-2 border-indigo-600 border-l-0',
              isFocused && !isSearching && value.trim() && 'shadow-lg shadow-indigo-500/20'
            )}
          >
            {isSearching ? (
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
            ) : (
              <Search className="w-5 h-5" />
            )}
          </button>
        </div>
      </form>

      {isFocused && recentSearches.length > 0 && !value && (
        <div className="absolute top-full left-0 right-0 mt-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-xl overflow-hidden z-50">
          <div className="px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400 uppercase">
            最近搜索
          </div>
          {recentSearches.slice(0, 5).map((term, index) => (
            <button
              key={index}
              onClick={() => handleQuickSearch(term)}
              className="w-full px-4 py-2.5 text-left hover:bg-slate-50 dark:hover:bg-slate-700/50 text-slate-700 dark:text-slate-200 transition-colors"
            >
              {term}
            </button>
          ))}
        </div>
      )}

      {isSearching && (
        <div className="absolute top-full left-0 right-0 mt-2 px-4 py-3 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 text-sm rounded-lg">
          搜索中...
        </div>
      )}
    </div>
  );
};