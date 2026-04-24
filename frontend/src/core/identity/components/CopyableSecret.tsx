// frontend/src/core/identity/components/CopyableSecret.tsx
"use client";

import { CopyIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  value: string;
  /** testid for the readonly input carrying the secret. Kept as a prop so existing
   * E2E selectors like `token-plaintext-value` continue to work after extraction. */
  valueTestId?: string;
  /** testid for the copy button. Same rationale. */
  copyTestId?: string;
  copyLabel?: string;
  copiedLabel?: string;
}

/**
 * Readonly input + copy button for one-time plaintext secrets (API tokens,
 * invitation codes, etc). Copy writes to clipboard and flashes a confirmation
 * for 1.5s. This component is purely presentational — dialogs own the
 * "token created" framing and Done/Close affordance.
 */
export function CopyableSecret({
  value,
  valueTestId,
  copyTestId,
  copyLabel = "Copy",
  copiedLabel = "Copied",
}: Props) {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex items-center gap-2">
      <Input
        readOnly
        value={value}
        className="font-mono"
        data-testid={valueTestId}
      />
      <Button
        type="button"
        size="sm"
        onClick={onCopy}
        data-testid={copyTestId}
      >
        <CopyIcon className="size-4" /> {copied ? copiedLabel : copyLabel}
      </Button>
    </div>
  );
}
