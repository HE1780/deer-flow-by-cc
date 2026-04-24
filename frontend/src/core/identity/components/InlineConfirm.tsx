// frontend/src/core/identity/components/InlineConfirm.tsx
"use client";

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

interface Props {
  /** Label shown on the initial trigger button. */
  label: string;
  /** Label shown on the confirm button after the first click. */
  confirmLabel?: string;
  /** Called when the confirm button is clicked. */
  onConfirm: () => void | Promise<void>;
  /** `data-testid` for the initial trigger (before arming). */
  triggerTestId?: string;
  /** `data-testid` for the confirm button (after arming). Callers set both
   * because the existing admin E2E suite uses asymmetric naming like
   * `token-revoke-100` + `token-revoke-confirm-100`. */
  confirmTestId?: string;
  /** Disables the confirm button while a mutation is running. */
  pending?: boolean;
  /** Optional custom trigger — if provided, overrides the default Button. */
  trigger?: ReactNode;
  variant?: "destructive" | "default" | "ghost";
  size?: "sm" | "default" | "lg" | "icon";
}

/**
 * Two-step inline confirm: first click flips to a Confirm/Cancel pair.
 * Matches the existing pattern used on /admin/tokens revoke and
 * /admin/workspaces/[id]/members remove. Extracted so new
 * rename/delete surfaces stay consistent.
 */
export function InlineConfirm({
  label,
  confirmLabel = "Confirm",
  onConfirm,
  triggerTestId,
  confirmTestId,
  pending = false,
  trigger,
  variant = "destructive",
  size = "sm",
}: Props) {
  const [armed, setArmed] = useState(false);

  if (!armed) {
    if (trigger) {
      return (
        <span
          role="button"
          data-testid={triggerTestId}
          onClick={() => setArmed(true)}
        >
          {trigger}
        </span>
      );
    }
    return (
      <Button
        size={size}
        variant="ghost"
        data-testid={triggerTestId}
        onClick={() => setArmed(true)}
      >
        {label}
      </Button>
    );
  }

  return (
    <span className="flex items-center gap-1">
      <Button
        size={size}
        variant={variant}
        onClick={() => onConfirm()}
        disabled={pending}
        data-testid={confirmTestId}
      >
        {confirmLabel}
      </Button>
      <Button size={size} variant="ghost" onClick={() => setArmed(false)}>
        Cancel
      </Button>
    </span>
  );
}
