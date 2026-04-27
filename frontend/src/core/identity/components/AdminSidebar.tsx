// frontend/src/core/identity/components/AdminSidebar.tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { cn } from "@/lib/utils";

import { useIdentity } from "../hooks";

interface Item {
  href: string;
  labelKey: keyof Translations["admin"]["nav"];
  requires?: string; // permission tag
  platformOnly?: true;
}

const ITEMS: Item[] = [
  { href: "/admin/profile", labelKey: "profile" },
  { href: "/admin/tenants", labelKey: "tenants", platformOnly: true },
  { href: "/admin/users", labelKey: "users", requires: "membership:read" },
  { href: "/admin/roles", labelKey: "roles" }, // any authenticated user
  {
    href: "/admin/workspaces",
    labelKey: "workspaces",
    requires: "workspace:read",
  },
  { href: "/admin/tokens", labelKey: "tokens", requires: "token:read" },
  { href: "/admin/audit", labelKey: "audit", requires: "audit:read" },
  { href: "/admin/org-keys", labelKey: "orgKeys", requires: "membership:read" },
  { href: "/admin/skills", labelKey: "skills", requires: "skill:manage" },
  { href: "/admin/models", labelKey: "models", platformOnly: true },
];

export function AdminSidebar() {
  const { identity } = useIdentity();
  const pathname = usePathname();
  const { t } = useI18n();

  const platformRoles = identity?.roles?.platform ?? [];
  const visible = ITEMS.filter((i) => {
    if (i.platformOnly) return platformRoles.includes("platform_admin");
    if (i.requires)
      return !!identity?.permissions.includes(i.requires);
    return true;
  });

  return (
    <nav aria-label="Admin navigation" className="flex flex-col gap-1 p-2">
      {visible.map((i) => {
        const active =
          pathname === i.href || pathname?.startsWith(i.href + "/");
        return (
          <Link
            key={i.href}
            href={i.href}
            className={cn(
              "rounded-md px-3 py-2 text-sm hover:bg-accent",
              active && "bg-accent font-medium",
            )}
          >
            {t.admin.nav[i.labelKey]}
          </Link>
        );
      })}
    </nav>
  );
}
