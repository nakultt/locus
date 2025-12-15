import React from "react";

export type ToastVariant = "success" | "error" | "info";

export interface Toast {
  id: string;
  message: string;
  variant: ToastVariant;
}

interface NotificationToastProps {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}

export const NotificationToast: React.FC<NotificationToastProps> = ({
  toasts,
  onDismiss,
}) => {
  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex flex-col items-center gap-2 px-4 sm:items-end sm:px-6">
      {toasts.map((toast) => {
        const base =
          "pointer-events-auto flex items-start gap-3 rounded-xl border px-4 py-3 text-xs shadow-lg backdrop-blur-sm max-w-sm w-full sm:w-auto";

        const variantClasses =
          toast.variant === "success"
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
            : toast.variant === "error"
            ? "border-red-500/40 bg-red-500/10 text-red-100"
            : "border-sky-500/40 bg-sky-500/10 text-sky-100";

        return (
          <div
            key={toast.id}
            className={`${base} ${variantClasses} animate-slide-up-fade`}
          >
            <div className="mt-0.5 h-2 w-2 flex-shrink-0 rounded-full bg-current" />
            <p className="flex-1">{toast.message}</p>
            <button
              type="button"
              onClick={() => onDismiss(toast.id)}
              className="ml-2 text-[10px] uppercase tracking-[0.14em] text-slate-200/70 hover:text-slate-50"
            >
              Dismiss
            </button>
          </div>
        );
      })}
    </div>
  );
};

export default NotificationToast;


