import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RolesPage from "@/app/(admin)/admin/roles/page";
import { useI18n } from "@/core/i18n/hooks";
import { useRoles } from "@/core/identity/hooks";

vi.mock("@/core/identity/hooks", () => ({
  useRoles: vi.fn(),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: vi.fn(),
}));

const mockUseRoles = vi.mocked(useRoles);
const mockUseI18n = vi.mocked(useI18n);

/**
 * Builds the minimum translation shape used by the roles page.
 */
function createTranslations() {
  return {
    admin: {
      pages: {
        rolesTitle: "角色",
        rolesScopePlatform: "平台",
        rolesScopeTenant: "租户",
        rolesScopeWorkspace: "工作区",
        rolesBuiltinTag: "内置",
      },
      table: {
        loading: "加载中…",
      },
    },
  };
}

describe("RolesPage", () => {
  beforeEach(() => {
    mockUseI18n.mockReturnValue({
      locale: "zh-CN",
      t: createTranslations() as unknown as ReturnType<typeof useI18n>["t"],
      changeLocale: vi.fn(),
    });
  });

  it("renders translated loading text", () => {
    mockUseRoles.mockReturnValue({
      data: undefined,
      isLoading: true,
    } as never);

    render(<RolesPage />);

    expect(screen.getByText("加载中…")).toBeTruthy();
  });

  it("renders translated page title", () => {
    mockUseRoles.mockReturnValue({
      data: {
        roles: [],
      },
      isLoading: false,
    } as never);

    render(<RolesPage />);

    expect(screen.getByRole("heading", { name: "角色" })).toBeTruthy();
  });

  it("translates known role labels and descriptions to Chinese", () => {
    mockUseRoles.mockReturnValue({
      data: {
        roles: [
          {
            role_key: "platform_admin",
            scope: "platform",
            display_name: "Platform Admin",
            description: "Full platform access",
            is_builtin: true,
          },
        ],
      },
      isLoading: false,
    } as never);

    render(<RolesPage />);

    expect(screen.getByText("平台管理员")).toBeTruthy();
    expect(screen.getByText("拥有平台全部管理权限。")).toBeTruthy();
    expect(screen.getByText("· 内置")).toBeTruthy();
  });
});
