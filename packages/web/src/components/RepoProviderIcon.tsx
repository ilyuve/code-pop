import { FolderGit2, Github } from 'lucide-react';
import { clsx } from 'clsx';

export type RepoProvider = 'github' | 'gitee' | 'other';

/** 根据 git_url 判断仓库托管平台。 */
export const getRepoProvider = (gitUrl?: string): RepoProvider => {
  const url = (gitUrl || '').toLowerCase();
  if (url.includes('github.com')) return 'github';
  if (url.includes('gitee.com')) return 'gitee';
  return 'other';
};

interface RepoProviderIconProps {
  gitUrl?: string;
  className?: string;
  /** 图标容器样式（默认复用列表卡片的 indigo 圆角底）。 */
  containerClassName?: string;
}

/**
 * 仓库托管平台图标：GitHub / Gitee / 默认文件夹。
 * lucide-react 无 Gitee 图标，使用近似 Gitee 视觉的内联 SVG。
 */
export const RepoProviderIcon = ({
  gitUrl,
  className,
  containerClassName,
}: RepoProviderIconProps) => {
  const provider = getRepoProvider(gitUrl);

  if (provider === 'other') {
    return (
      <div className={clsx('p-2 bg-indigo-100 dark:bg-indigo-900/30 rounded-lg', containerClassName)}>
        <FolderGit2 className={clsx('w-5 h-5 text-indigo-600 dark:text-indigo-400', className)} />
      </div>
    );
  }

  if (provider === 'github') {
    return (
      <div className={clsx('p-2 bg-slate-100 dark:bg-slate-700 rounded-lg', containerClassName)}>
        <Github className={clsx('w-5 h-5 text-slate-900 dark:text-white', className)} />
      </div>
    );
  }

  // Gitee：红底白色 g 标（近似官方视觉）
  return (
    <div className={clsx('p-2 bg-red-50 dark:bg-red-900/20 rounded-lg', containerClassName)}>
      <svg viewBox="0 0 24 24" className={clsx('w-5 h-5', className)} aria-label="Gitee">
        <circle cx="12" cy="12" r="11" fill="#C71D23" />
        <path
          d="M12 3.6c-4.6 0-8.4 3.8-8.4 8.4S7.4 20.4 12 20.4s8.4-3.8 8.4-8.4S16.6 3.6 12 3.6zm0 2.4a6 6 0 1 1 0 12 6 6 0 0 1 0-12zm-3.2 4.2c-.9 0-1.6.7-1.6 1.6v.6c0 .9.7 1.6 1.6 1.6h3.2v1.2c0 .4-.3.6-.6.6-.4 0-.7.3-.7.6v.6c0 .4.3.6.6.6h.6c1.4 0 2.5-1.1 2.5-2.5V12c0-1.1-.9-2-2-2h-3.2z"
          fill="#fff"
        />
      </svg>
    </div>
  );
};

export default RepoProviderIcon;
