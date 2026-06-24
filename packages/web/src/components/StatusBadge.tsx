import { clsx } from 'clsx';
import { CheckCircle, Loader2, AlertCircle } from 'lucide-react';
import type { Repo } from '../types';

type Status = Repo['status'];

interface StatusBadgeProps {
  status: Status;
}

const statusConfig: Record<Status, {
  label: string;
  icon: typeof Loader2;
  className: string;
  iconClass: string;
}> = {
  indexing: {
    label: '索引中',
    icon: Loader2,
    className: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    iconClass: 'animate-spin',
  },
  indexed: {
    label: '已索引',
    icon: CheckCircle,
    className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    iconClass: '',
  },
  completed: {
    label: '已完成',
    icon: CheckCircle,
    className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    iconClass: '',
  },
  error: {
    label: '错误',
    icon: AlertCircle,
    className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    iconClass: '',
  },
};

export const StatusBadge = ({ status }: StatusBadgeProps) => {
  const config = statusConfig[status];
  const Icon = config.icon;

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium',
        config.className
      )}
    >
      <Icon className={clsx('w-3.5 h-3.5', config.iconClass)} />
      {config.label}
    </span>
  );
};
