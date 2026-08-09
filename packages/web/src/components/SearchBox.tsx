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
              isFocused ? 'text-[#ff3d8a]' : 'text-[#999]'
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
              'flex-1 pl-12 pr-20 py-3 bg-white border-2 rounded-l-xl',
              'text-[#2D2D2D] placeholder-[#999] font-medium',
              'transition-all duration-200',
              isFocused
                ? 'border-[#2ad4ff] shadow-[4px_4px_0_#2ad4ff]'
                : 'border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D]'
            )}
          />
          {value && (
            <button
              type="button"
              onClick={handleClear}
              className="absolute right-18 p-1 hover:bg-[#F5F5F0] rounded-full transition-colors"
            >
              <X className="w-4 h-4 text-[#666]" />
            </button>
          )}
          <button
            type="submit"
            disabled={isSearching || !value.trim()}
            className={clsx(
              'px-6 py-3 bg-[#ff3d8a] hover:bg-[#ff5c9d] disabled:bg-slate-200',
              'text-white font-bold rounded-r-xl transition-all duration-200',
              'border-2 border-[#2D2D2D] border-l-0',
              !isSearching && value.trim() && 'shadow-[4px_4px_0_#2D2D2D] hover:translate-y-[-2px]'
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
        <div className="absolute top-full left-0 right-0 mt-2 bg-white border-2 border-[#2D2D2D] rounded-xl shadow-[6px_6px_0_rgba(45,45,45,0.3)] overflow-hidden z-50">
          <div className="px-4 py-2 text-xs font-bold text-[#666] uppercase border-b-2 border-[#2D2D2D] bg-[#F5F5F0]">
            最近搜索
          </div>
          {recentSearches.slice(0, 5).map((term, index) => (
            <button
              key={index}
              onClick={() => handleQuickSearch(term)}
              className="w-full px-4 py-2.5 text-left hover:bg-[#fff34d] text-[#2D2D2D] transition-colors font-medium"
            >
              {term}
            </button>
          ))}
        </div>
      )}

      {isSearching && (
        <div className="absolute top-full left-0 right-0 mt-2 px-4 py-3 bg-[#2ad4ff] text-[#2D2D2D] text-sm rounded-lg border-2 border-[#2D2D2D] font-bold">
          搜索中...
        </div>
      )}
    </div>
  );
};