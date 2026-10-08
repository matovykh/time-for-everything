import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

const ToastContext = createContext<(message: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timeout = useRef<number | undefined>(undefined);
  const show = useCallback((m: string) => {
    setMessage(m);
    window.clearTimeout(timeout.current);
    timeout.current = window.setTimeout(() => setMessage(null), 4000);
  }, []);
  useEffect(() => () => window.clearTimeout(timeout.current), []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div id="toast" role="status" aria-live="polite" style={{ display: message ? "block" : "none" }}>
        {message}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
