import type { ReactNode } from 'react';
import { AlertTriangle, X } from 'lucide-react';
import { LoadingSpinner } from './LoadingSpinner';

interface ConfirmModalProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmText?: string;
  cancelText?: string;
  /** 危险操作：确认按钮用红色高亮，并显示 AlertTriangle 图标 */
  danger?: boolean;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** 波普风格的高危操作确认弹窗（删除等不可逆操作必须经过确认）。 */
export const ConfirmModal = ({
  open,
  title,
  description,
  confirmText = '确认',
  cancelText = '取消',
  danger = false,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-2xl w-full max-w-sm p-6 border-4 border-[#2D2D2D] shadow-[8px_8px_0_rgba(45,45,45,0.4)]">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-black text-[#2D2D2D] flex items-center gap-2">
            {danger && (
              <AlertTriangle className="w-5 h-5 shrink-0" style={{ color: '#ff3d8a' }} />
            )}
            {title}
          </h2>
          <button
            onClick={onCancel}
            disabled={loading}
            className="p-1.5 rounded-lg border-2 border-transparent hover:border-[#2D2D2D] hover:bg-[#F5F5F0] transition-colors disabled:opacity-40"
          >
            <X className="w-5 h-5 text-[#2D2D2D]" />
          </button>
        </div>

        {description && (
          <div className="text-sm text-[#666] leading-relaxed mb-6">{description}</div>
        )}

        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={loading}
            className="px-4 py-2 text-[#666] hover:bg-[#F5F5F0] rounded-lg font-bold transition-colors disabled:opacity-40"
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={clsxButton(danger)}
          >
            {loading ? <LoadingSpinner size="sm" /> : null}
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
};

function clsxButton(danger: boolean): string {
  const base =
    'flex items-center gap-2 px-5 py-2 rounded-lg font-bold border-2 border-[#2D2D2D] shadow-[3px_3px_0_#2D2D2D] transition-all duration-200 hover:translate-y-[-2px] hover:shadow-[5px_5px_0_#2D2D2D] disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-[3px_3px_0_#2D2D2D]';
  return danger
    ? `${base} bg-[#ff3d8a] hover:bg-[#ff5c9d] text-white`
    : `${base} bg-[#2ad4ff] hover:bg-[#4adee0] text-[#2D2D2D]`;
}
