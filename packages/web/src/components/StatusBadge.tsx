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
    className: 'bg-[#fff34d] text-[#2D2D2D] border-2 border-[#2D2D2D]',
    iconClass: 'animate-spin',
  },
  indexed: {
    label: '已索引',
    icon: CheckCircle,
    className: 'bg-[#6effb0] text-[#2D2D2D] border-2 border-[#2D2D2D]',
    iconClass: '',
  },
  completed: {
    label: '已完成',
    icon: CheckCircle,
    className: 'bg-[#6effb0] text-[#2D2D2D] border-2 border-[#2D2D2D]',
    iconClass: '',
  },
  error: {
    label: '错误',
    icon: AlertCircle,
    className: 'bg-[#ff3d8a] text-white border-2 border-[#2D2D2D]',
    iconClass: '',
  },
};

export const StatusBadge = ({ status }: StatusBadgeProps) => {
  const config = statusConfig[status];
  const Icon = config.icon;

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold',
        config.className
      )}
    >
      <Icon className={clsx('w-3.5 h-3.5', config.iconClass)} />
      {config.label}
    </span>
  );
};
