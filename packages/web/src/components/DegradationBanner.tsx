import { AlertTriangle, X } from 'lucide-react';

interface DegradationBannerProps {
  degraded: boolean;
  reason?: string;
  onClose?: () => void;
}

export const DegradationBanner = ({ degraded, reason, onClose }: DegradationBannerProps) => {
  if (!degraded) return null;

  return (
    <div className="bg-yellow-50 border border-yellow-200 dark:border-yellow-700 dark:bg-yellow-900/20 px-4 py-3 flex items-center gap-3">
      <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 flex-shrink-0" />
      <div className="flex-1">
        <p className="text-sm font-medium text-yellow-800 dark:text-yellow-200">
          服务降级中
        </p>
        {reason && (
          <p className="text-xs text-yellow-700 dark:text-yellow-300 mt-0.5">
            {reason}
          </p>
        )}
      </div>
      {onClose && (
        <button
          onClick={onClose}
          className="text-yellow-600 dark:text-yellow-400 hover:text-yellow-800 dark:hover:text-yellow-200 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};
