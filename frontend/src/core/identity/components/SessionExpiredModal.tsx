// frontend/src/core/identity/components/SessionExpiredModal.tsx
"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { consumeSessionExpired, onSessionExpired } from "@/core/identity/fetcher";

export function SessionExpiredModal() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    return onSessionExpired(() => {
      // Public auth pages (/login, /register) don't need the modal — the user
      // is already on a page that handles unauthenticated state.
      if (
        pathname?.startsWith("/login") ||
        pathname?.startsWith("/register")
      ) {
        consumeSessionExpired();
        return;
      }
      setOpen(true);
    });
  }, [pathname]);

  const nextParam =
    pathname && pathname !== "/login"
      ? `?next=${encodeURIComponent(pathname)}`
      : "";

  function handleGoToSignIn() {
    const target = `/login${nextParam}`;
    consumeSessionExpired();
    setOpen(false);
    window.location.assign(target);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) consumeSessionExpired();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Session expired</DialogTitle>
          <DialogDescription>
            Your session is no longer valid. Please sign in again to continue.
          </DialogDescription>
        </DialogHeader>
        <button
          type="button"
          onClick={handleGoToSignIn}
          className="inline-flex h-9 items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Go to sign-in
        </button>
      </DialogContent>
    </Dialog>
  );
}
