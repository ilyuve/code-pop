export interface LanguageConfig {
  name: string;
  extensions: string[];
  treeSitterLanguage: string;
  commentPattern?: RegExp;
}

export const SUPPORTED_LANGUAGES: LanguageConfig[] = [
  {
    name: 'TypeScript',
    extensions: ['.ts', '.tsx'],
    treeSitterLanguage: 'typescript',
    commentPattern: /\/\/|\/\*|\*\/|<!--/,
  },
  {
    name: 'JavaScript',
    extensions: ['.js', '.jsx', '.mjs', '.cjs'],
    treeSitterLanguage: 'javascript',
    commentPattern: /\/\/|\/\*|\*\/|<!--/,
  },
  {
    name: 'Python',
    extensions: ['.py', '.pyw', '.pyi'],
    treeSitterLanguage: 'python',
    commentPattern: /#|"""/,
  },
  {
    name: 'Go',
    extensions: ['.go'],
    treeSitterLanguage: 'go',
    commentPattern: /\/\/|\/\*/,
  },
  {
    name: 'Java',
    extensions: ['.java'],
    treeSitterLanguage: 'java',
    commentPattern: /\/\/|\/\*|\*\/|<!--/,
  },
  {
    name: 'Rust',
    extensions: ['.rs'],
    treeSitterLanguage: 'rust',
    commentPattern: /\/\/|\/\*/,
  },
  {
    name: 'C++',
    extensions: ['.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx', '.c', '.h'],
    treeSitterLanguage: 'cpp',
    commentPattern: /\/\/|\/\*/,
  },
  {
    name: 'C#',
    extensions: ['.cs'],
    treeSitterLanguage: 'c_sharp',
    commentPattern: /\/\/|\/\*|\*\/|<!--/,
  },
];

const EXTENSION_TO_LANGUAGE = new Map<string, LanguageConfig>();
const LANGUAGE_TO_CONFIG = new Map<string, LanguageConfig>();

for (const lang of SUPPORTED_LANGUAGES) {
  for (const ext of lang.extensions) {
    EXTENSION_TO_LANGUAGE.set(ext.toLowerCase(), lang);
  }
  LANGUAGE_TO_CONFIG.set(lang.name.toLowerCase(), lang);
}

export function detectLanguage(filePath: string): LanguageConfig | null {
  const lowerPath = filePath.toLowerCase();
  
  for (const [ext, lang] of EXTENSION_TO_LANGUAGE) {
    if (lowerPath.endsWith(ext)) {
      return lang;
    }
  }
  
  return null;
}

export function getLanguageByName(name: string): LanguageConfig | null {
  return LANGUAGE_TO_CONFIG.get(name.toLowerCase()) || null;
}

export function getAllLanguages(): LanguageConfig[] {
  return [...SUPPORTED_LANGUAGES];
}

export const SKIP_PATTERNS = [
  /node_modules/,
  /\.git/,
  /dist/,
  /build/,
  /\.next/,
  /\.nuxt/,
  /coverage/,
  /\.cache/,
  /__pycache__/,
  /\.pyc/,
  /vendor\/node_modules/,
  /\.venv/,
  /venv/,
  /target/,
  /pkg/,
  /\.idea/,
  /\.vscode/,
  /\.DS_Store/,
  /Thumbs\.db/,
  /\.log$/,
  /\.lock$/,
  /package-lock\.json$/,
  /yarn\.lock$/,
  /pnpm-lock\.yaml$/,
  /\.min\.(js|css)$/,
  /\.bundle\.js$/,
];

export const SKIP_BINARY_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.svg',
  '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
  '.zip', '.tar', '.gz', '.rar', '.7z',
  '.mp3', '.mp4', '.wav', '.avi', '.mov', '.wmv',
  '.ttf', '.otf', '.woff', '.woff2', '.eot',
  '.exe', '.dll', '.so', '.dylib', '.o', '.obj',
  '.env', '.env.local', '.env.production',
]);

export function shouldSkipPath(filePath: string): boolean {
  const lowerPath = filePath.toLowerCase();
  
  for (const pattern of SKIP_PATTERNS) {
    if (pattern.test(lowerPath)) {
      return true;
    }
  }
  
  return false;
}

export function isBinaryFile(filePath: string): boolean {
  const lowerPath = filePath.toLowerCase();
  
  for (const ext of SKIP_BINARY_EXTENSIONS) {
    if (lowerPath.endsWith(ext)) {
      return true;
    }
  }
  
  return false;
}

export function getFileExtension(filePath: string): string {
  const lastDot = filePath.lastIndexOf('.');
  if (lastDot === -1 || lastDot === filePath.length - 1) {
    return '';
  }
  return filePath.slice(lastDot);
}
