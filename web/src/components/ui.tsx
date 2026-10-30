import { useEffect, type ReactNode } from 'react';
import Icon from './Icon';

export function Spinner({ full = false }: { full?: boolean }) {
  return (
    <div className={full ? 'spinner-wrap full' : 'spinner-wrap'}>
      <div className="spinner" aria-label="Loading" />
    </div>
  );
}

export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', listener);
    document.body.classList.add('modal-open');
    return () => {
      document.removeEventListener('keydown', listener);
      document.body.classList.remove('modal-open');
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true">
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <Icon name="close" size={16} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function Badge({ children, tone = 'default' }: { children: ReactNode; tone?: string }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function ErrorBox({ message }: { message: string | null | undefined }) {
  if (!message) return null;
  return <div className="error-box">{message}</div>;
}

export function HelpTip({ text }: { text: string }) {
  return (
    <span className="help-tip">
      <button type="button" aria-label={`Help: ${text}`}>
        ?
      </button>
      <span className="help-tip-content" role="tooltip">
        {text}
      </span>
    </span>
  );
}

export function Field({
  label,
  hint,
  help,
  children,
}: {
  label: string;
  hint?: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {help && <HelpTip text={help} />}
      </span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="progress" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}

export function formatDate(value?: string | null) {
  if (!value) return '—';
  return new Date(value).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatBytes(value?: number | null) {
  if (!value) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}
