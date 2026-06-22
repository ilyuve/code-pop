import { EventEmitter } from 'events';
import { parseFile, SupportedLanguage, getLanguageFromExtension } from './parser';
import { embedText, EmbeddingConfig } from './embedder';
import { DatabaseAdapter, FileCreate } from '../data/adapter';
import { createHash } from 'crypto';
import { readdir, stat, readFile } from 'fs/promises';
import { join, relative } from 'path';
import { glob } from 'glob';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

export interface IndexerConfig {
  db: DatabaseAdapter;
  embeddingConfig: EmbeddingConfig;
  maxConcurrent?: number;
  maxFileSize?: number;
  skipPatterns?: string[];
}

export interface IndexProgress {
  total: number;
  current: number;
  currentFile: string;
  status: 'indexing' | 'completed' | 'error';
  error?: string;
}

export class CodeIndexer extends EventEmitter {
  private db: DatabaseAdapter;
  private embeddingConfig: EmbeddingConfig;
  private maxConcurrent: number;
  private maxFileSize: number;
  private skipPatterns: string[];
  private isIndexing: boolean = false;
  private shouldCancel: boolean = false;

  constructor(config: IndexerConfig) {
    super();
    this.db = config.db;
    this.embeddingConfig = config.embeddingConfig;
    this.maxConcurrent = config.maxConcurrent || 4;
    this.maxFileSize = config.maxFileSize || 1024 * 1024; // 1MB
    this.skipPatterns = config.skipPatterns || [
      '**/node_modules/**',
      '**/.git/**',
      '**/dist/**',
      '**/build/**',
      '**/*.min.js',
      '**/*.map',
      '**/.DS_Store',
      '**/package-lock.json',
      '**/yarn.lock',
      '**/pnpm-lock.yaml',
    ];
  }

  /**
   * Index an entire repository
   */
  async indexRepo(repoId: string, repoPath: string): Promise<{ totalIndexed: number; duration: number }> {
    if (this.isIndexing) {
      throw new Error('Indexing already in progress');
    }

    this.isIndexing = true;
    this.shouldCancel = false;
    const startTime = Date.now();
    let totalIndexed = 0;

    try {
      // Get git commit info if available
      const gitInfo = await this.getGitInfo(repoPath);

      // Find all files to index
      const files = await this.findFiles(repoPath);

      this.emit('progress', {
        total: files.length,
        current: 0,
        currentFile: '',
        status: 'indexing' as const,
      });

      // Process files in batches for better performance
      for (let i = 0; i < files.length; i += this.maxConcurrent * 10) {
        if (this.shouldCancel) {
          this.emit('complete', { cancelled: true, totalIndexed });
          break;
        }

        const batch = files.slice(i, i + this.maxConcurrent * 10);
        const results = await Promise.allSettled(
          batch.map(file => this.indexFile(repoId, file, gitInfo))
        );

        results.forEach((result, idx) => {
          if (result.status === 'fulfilled' && result.value) {
            totalIndexed += result.value;
          }
        });

        this.emit('progress', {
          total: files.length,
          current: Math.min(i + batch.length, files.length),
          currentFile: batch[batch.length - 1] || '',
          status: 'indexing' as const,
        });
      }

      const duration = Date.now() - startTime;
      this.emit('complete', { totalIndexed, duration });

      return { totalIndexed, duration };
    } finally {
      this.isIndexing = false;
    }
  }

  /**
   * Index a single file
   */
  async indexFile(repoId: string, filePath: string, gitInfo?: Record<string, string>): Promise<number> {
    try {
      const fileStat = await stat(filePath);

      // Skip large files
      if (fileStat.size > this.maxFileSize) {
        return 0;
      }

      const content = await readFile(filePath, 'utf-8').catch(() => null);
      if (!content) {
        return 0;
      }

      const ext = filePath.split('.').pop()?.toLowerCase() || '';
      const language = getLanguageFromExtension(ext);

      if (!language) {
        return 0;
      }

      // Calculate content hash for deduplication
      const contentHash = createHash('sha256').update(content).digest('hex');

      // Check if file already indexed with same hash
      const existingFile = await this.db.file.getByPath(repoId, filePath);
      if (existingFile && existingFile.contentHash === contentHash) {
        return 0;
      }

      // Parse file to get symbols
      const symbols = parseFile(content, language, filePath);

      // Create or update file record
      const fileCreate: FileCreate = {
        repoId,
        path: filePath,
        language,
        contentHash,
        sizeBytes: fileStat.size,
        gitModifiedAt: gitInfo?.modified ? new Date(gitInfo.modified) : undefined,
        gitAuthor: gitInfo?.author,
        gitCommitMsg: gitInfo?.message,
      };

      const file = existingFile
        ? await this.db.file.update(existingFile.id, fileCreate)
        : await this.db.file.create(fileCreate);

      // Delete old symbols and embeddings
      await this.db.symbol.deleteByFileId(file.id);
      await this.db.embedding.deleteByFileId(file.id);

      // Create symbols
      for (const symbol of symbols) {
        await this.db.symbol.create({
          fileId: file.id,
          name: symbol.name,
          type: symbol.type,
          kind: symbol.kind,
          line: symbol.location.startLine,
          column: symbol.location.startColumn,
          endLine: symbol.location.endLine,
          endColumn: symbol.location.endColumn,
          parentId: symbol.parentId,
          isExported: symbol.isExported,
        });
      }

      // Create embeddings with batching for large files
      const chunks = this.chunkContent(content, 1000); // 1000 lines per chunk
      let chunkIndex = 0;

      for (const chunk of chunks) {
        const embedding = await embedText(chunk, this.embeddingConfig);
        const tokenCount = Math.ceil(chunk.length / 4); // Approximate token count

        await this.db.embedding.create({
          fileId: file.id,
          chunkIndex: chunkIndex++,
          content: chunk,
          embedding,
          tokenCount,
        });
      }

      return chunks.length;
    } catch (error) {
      console.error(`Error indexing file ${filePath}:`, error);
      return 0;
    }
  }

  /**
   * Find all indexable files in a directory
   */
  private async findFiles(repoPath: string): Promise<string[]> {
    const patterns = this.skipPatterns.map(p => join(repoPath, p));

    const files: string[] = [];
    const queue = [repoPath];

    while (queue.length > 0) {
      const currentDir = queue.shift()!;

      try {
        const entries = await readdir(currentDir);

        for (const entry of entries) {
          const fullPath = join(currentDir, entry);

          // Check if should skip
          const relPath = relative(repoPath, fullPath);
          if (this.shouldSkip(relPath)) {
            continue;
          }

          try {
            const stat = await stat(fullPath);

            if (stat.isDirectory()) {
              queue.push(fullPath);
            } else if (stat.isFile()) {
              files.push(fullPath);
            }
          } catch {
            // Skip inaccessible files
          }
        }
      } catch {
        // Skip inaccessible directories
      }
    }

    return files;
  }

  /**
   * Check if a path should be skipped
   */
  private shouldSkip(path: string): boolean {
    const normalizedPath = path.replace(/\\/g, '/');

    for (const pattern of this.skipPatterns) {
      const normalizedPattern = pattern.replace(/\\/g, '/');
      if (this.matchPattern(normalizedPath, normalizedPattern)) {
        return true;
      }
    }

    return false;
  }

  /**
   * Simple glob pattern matching
   */
  private matchPattern(path: string, pattern: string): boolean {
    const regexPattern = pattern
      .replace(/\*\*/g, '.*')
      .replace(/\*/g, '[^/]*')
      .replace(/\?/g, '.');

    return new RegExp(`^${regexPattern}$`).test(path);
  }

  /**
   * Chunk content for embedding
   */
  private chunkContent(content: string, linesPerChunk: number): string[] {
    const lines = content.split('\n');
    const chunks: string[] = [];

    for (let i = 0; i < lines.length; i += linesPerChunk) {
      chunks.push(lines.slice(i, i + linesPerChunk).join('\n'));
    }

    return chunks.length > 0 ? chunks : [content];
  }

  /**
   * Get git commit info for a file
   */
  private async getGitInfo(repoPath: string): Promise<Record<string, string>> {
    try {
      const { stdout } = await execAsync(
        `git log -1 --format="%H|%an|%ae|%ad|%s" --date=iso`,
        { cwd: repoPath }
      );

      const [hash, author, email, date, message] = stdout.trim().split('|');

      return {
        hash: hash || '',
        author: author || '',
        email: email || '',
        modified: date || '',
        message: message || '',
      };
    } catch {
      return {};
    }
  }

  /**
   * Cancel ongoing indexing
   */
  cancel(): void {
    this.shouldCancel = true;
  }

  /**
   * Check if currently indexing
   */
  getIsIndexing(): boolean {
    return this.isIndexing;
  }
}

/**
 * Factory function to create a configured indexer
 */
export function createIndexer(config: IndexerConfig): CodeIndexer {
  return new CodeIndexer(config);
}
