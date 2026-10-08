import { useEffect, useRef, type ReactNode } from "react";

/**
 * Native <dialog> opened with showModal(): focus is trapped by the browser,
 * Escape triggers onClose, and focus returns to the opener on close.
 */
export function Dialog({
  className,
  labelledBy,
  onClose,
  children,
}: {
  className?: string;
  labelledBy: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const opener = document.activeElement as HTMLElement | null;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    else dialog.setAttribute("open", "");
    const onCancel = (e: Event) => {
      e.preventDefault();
      closeRef.current();
    };
    dialog.addEventListener("cancel", onCancel);
    return () => {
      dialog.removeEventListener("cancel", onCancel);
      if (dialog.open && typeof dialog.close === "function") dialog.close();
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog ref={ref} className={className} aria-labelledby={labelledBy}>
      {children}
    </dialog>
  );
}
