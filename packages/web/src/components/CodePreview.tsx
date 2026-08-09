import { Highlight, themes } from 'prism-react-renderer';
import { useStore } from '../store';

interface CodePreviewProps {
  code: string;
  language?: string;
  filePath?: string;
}

// 按文件路径后缀推断语言，供未显式传入 language 的调用方使用
const LANG_BY_EXT: Record<string, string> = {
  '.py': 'python',
  '.ts': 'typescript',
  '.tsx': 'tsx',
  '.js': 'javascript',
  '.jsx': 'jsx',
  '.go': 'go',
  '.java': 'java',
  '.rust': 'rust',
  '.rs': 'rust',
  '.cpp': 'cpp',
  '.c': 'c',
  '.h': 'cpp',
  '.hpp': 'cpp',
  '.kt': 'kotlin',
  '.sql': 'sql',
  '.json': 'json',
  '.yaml': 'yaml',
  '.yml': 'yaml',
  '.xml': 'xml',
  '.css': 'css',
  '.scss': 'scss',
  '.html': 'html',
  '.vue': 'markup',
  '.sh': 'bash',
  '.md': 'markdown',
};

const isSupported = (lang: string | undefined): boolean =>
  Boolean(lang && ['js', 'jsx', 'ts', 'tsx', 'go', 'java', 'c', 'cpp', 'rust', 'python', 'json', 'css', 'bash', 'markup', 'yaml', 'sql', 'markdown', 'kotlin', 'csharp', 'php', 'ruby', 'swift'].includes(lang));

const inferLanguage = (filePath?: string): string => {
  if (!filePath) return 'typescript';
  const lower = filePath.toLowerCase();
  for (const [ext, lang] of Object.entries(LANG_BY_EXT)) {
    if (lower.endsWith(ext)) return lang;
  }
  return 'typescript';
};

export const CodePreview = ({ code, language, filePath }: CodePreviewProps) => {
  const { settings } = useStore();
  const isDark = settings.theme === 'dark';

  // 优先使用显式传入的语言；否则按文件后缀推断；
  // prism 不支持的语法一律回落为 text，避免高亮报错
  const resolved = isSupported(language) ? (language as string) : inferLanguage(filePath);
  const prismLang = isSupported(resolved) ? resolved : 'text';

  return (
    <Highlight
      theme={isDark ? themes.nightOwl : themes.github}
      code={code.trim()}
      language={prismLang}
    >
      {({ className, style, tokens, getLineProps, getTokenProps }) => (
        <pre
          className={`${className} p-4 overflow-x-auto text-sm font-mono`}
          style={{ ...style, backgroundColor: 'transparent' }}
        >
          {tokens.map((line, i) => (
            <div key={i} {...getLineProps({ line })} className="table-row">
              <span className="table-cell pr-4 text-slate-400 select-none text-right w-8">
                {i + 1}
              </span>
              <span className="table-cell">
                {line.map((token, key) => (
                  <span key={key} {...getTokenProps({ token })} />
                ))}
              </span>
            </div>
          ))}
        </pre>
      )}
    </Highlight>
  );
};
