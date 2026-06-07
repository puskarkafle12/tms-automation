import React, { useState, useEffect } from 'react';
import './ErrorMessage.css';

type MessageVariant = 'error' | 'success' | 'info';

interface ErrorMessageProps {
  message: string;
  variant?: MessageVariant;
  /** Keep visible until the user dismisses it */
  persistent?: boolean;
  /** @deprecated use variant instead */
  color?: string;
}

const ErrorMessage: React.FC<ErrorMessageProps> = ({ message, variant, persistent, color }) => {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    setIsVisible(true);
    if (persistent) {
      return undefined;
    }
    const timer = setTimeout(() => setIsVisible(false), 8000);
    return () => clearTimeout(timer);
  }, [message, persistent]);

  const resolvedVariant: MessageVariant = variant
    || (color === 'lightgreen' ? 'success' : 'error');

  if (!isVisible) {
    return null;
  }

  return (
    <div className={`toast toast-${resolvedVariant}`} role="alert">
      <div className="toast-body">{message}</div>
      <button type="button" className="toast-close" onClick={() => setIsVisible(false)} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
};

export default ErrorMessage;
