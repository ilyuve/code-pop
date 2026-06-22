import { DatabaseAdapter } from './adapter';

export type DatabaseType = 'postgresql' | 'sqlite' | 'mock';

export interface DatabaseConfig {
  type: DatabaseType;
  connectionString: string;
  options?: Record<string, unknown>;
}

export class AdapterFactory {
  private static adapters: Map<DatabaseType, () => Promise<DatabaseAdapter>> = new Map();

  static register(type: DatabaseType, factory: () => Promise<DatabaseAdapter>): void {
    this.adapters.set(type, factory);
  }

  static async create(config: DatabaseConfig): Promise<DatabaseAdapter> {
    const factory = this.adapters.get(config.type);
    if (!factory) {
      throw new Error(`Unsupported database type: ${config.type}`);
    }
    return factory();
  }
}

export const initAdapters = async (): Promise<void> => {
  AdapterFactory.register('postgresql', async () => {
    const { PostgreSQLAdapter } = await import('./postgresql-adapter');
    return new PostgreSQLAdapter();
  });

  AdapterFactory.register('sqlite', async () => {
    const { SQLiteAdapter } = await import('./sqlite-adapter');
    return new SQLiteAdapter();
  });

  AdapterFactory.register('mock', async () => {
    const { MockAdapter } = await import('./mock-adapter');
    return new MockAdapter();
  });
};
