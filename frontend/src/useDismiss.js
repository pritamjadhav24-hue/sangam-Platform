import { useEffect, useRef } from 'react';

// Closes an open panel/menu/modal when the citizen clicks outside it or
// presses Escape. The listener is only attached while `isOpen` is true and
// is removed on close/unmount -- never a permanently-mounted global handler.
export function useDismiss(isOpen, onDismiss) {
  const ref = useRef(null);
  useEffect(() => {
    if (!isOpen) return undefined;
    function handlePointerDown(event) {
      if (ref.current && !ref.current.contains(event.target)) onDismiss();
    }
    function handleKeyDown(event) {
      if (event.key === 'Escape') onDismiss();
    }
    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onDismiss]);
  return ref;
}
