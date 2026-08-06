import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchIndexingLogs, fetchIndexingProgress } from '../api';

export interface StageProgress {
  stage: string;
  current: number;
  total: number;
  percentage: number;
}

export interface IndexingProgress {
  current: number;
  total: number;
  percentage: number;
}

export interface LogEntry {
  timestamp: string;
  level: string;
  message: string;
  stage: string | null;
}

export const STAGE_LABELS: Record<string, string> = {
  git_sync: '代码同步',
  scan: '文件扫描',
  symbols: '符号解析',
  embeddings: '向量生成',
  chinese_enrichment: '中文增强',
  flow_labels: '流程标签',
  call_graph: '调用图构建',
};

export const STAGE_ORDER = [
  'git_sync',
  'scan',
  'chinese_enrichment',
  'symbols',
  'embeddings',
  'flow_labels',
  'call_graph',
];

export interface RepoData {
  status: string;
  indexedFiles: number;
  totalFiles: number;
  errorMessage?: string;
}

export const useIndexing = (repoId: string, repo: RepoData | undefined) => {
  const isIndexing = repo?.status === 'indexing';

  const { data: progressData } = useQuery({
    queryKey: ['indexingProgress', repoId],
    queryFn: () => fetchIndexingProgress(repoId),
    enabled: !!repoId && isIndexing,
    refetchInterval: isIndexing ? 2000 : false,
  });

  const { data: logs } = useQuery({
    queryKey: ['indexingLogs', repoId],
    queryFn: () => fetchIndexingLogs(repoId),
    enabled: !!repoId && (isIndexing || repo?.status === 'error'),
    refetchInterval: isIndexing ? 2000 : false,
  });

  const progress: IndexingProgress | null = useMemo(() => {
    if (!repo) return null;

    if (isIndexing && progressData?.overall_progress !== undefined) {
      return {
        current: 0,
        total: 100,
        percentage: Math.round(progressData.overall_progress),
      };
    }

    if (isIndexing) {
      return {
        current: 0,
        total: 100,
        percentage: 0,
      };
    }

    return {
      current: repo.indexedFiles,
      total: repo.totalFiles,
      percentage: repo.totalFiles > 0
        ? Math.round((repo.indexedFiles / repo.totalFiles) * 100)
        : 0,
    };
  }, [repo, isIndexing, progressData]);

  const stageProgress: StageProgress | null = useMemo(() => {
    if (!isIndexing) return null;

    if (progressData?.current_stage && progressData.stage_progress) {
      const stage = progressData.stage_progress[progressData.current_stage];
      if (stage) {
        return {
          stage: progressData.current_stage,
          current: stage.current,
          total: stage.total,
          percentage: stage.progress,
        };
      }
    }

    return null;
  }, [isIndexing, progressData]);

  const currentStageLabel = useMemo(() => {
    if (!stageProgress) {
      return isIndexing ? '索引中' : null;
    }
    return STAGE_LABELS[stageProgress.stage] ?? stageProgress.stage;
  }, [stageProgress, isIndexing]);

  const timing = useMemo(() => {
    if (!isIndexing || !progressData) return null;
    return {
      elapsedSeconds: progressData.elapsed_seconds ?? null,
      estimatedRemainingSeconds: progressData.estimated_remaining_seconds ?? null,
      startedAt: progressData.indexing_started_at ?? null,
    };
  }, [isIndexing, progressData]);

  return {
    isIndexing,
    progress,
    stageProgress,
    currentStageLabel,
    timing,
    error: repo?.errorMessage,
    logs: logs || [],
  };
};