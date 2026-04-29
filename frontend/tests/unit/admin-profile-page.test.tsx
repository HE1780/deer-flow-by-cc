import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProfilePage from "@/app/(admin)/admin/profile/page";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateMyToken,
  useIdentity,
  useMySessions,
  useMyTokens,
  useRevokeMySession,
  useRevokeMyToken,
  useUpdateMe,
} from "@/core/identity/hooks";

const { mockUseChangePassword } = vi.hoisted(() => ({
  mockUseChangePassword: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: (props: React.ComponentProps<"a">) => <a {...props} />,
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: vi.fn(),
}));

vi.mock("@/core/identity/hooks", () => ({
  useIdentity: vi.fn(),
  useUpdateMe: vi.fn(),
  useMyTokens: vi.fn(),
  useCreateMyToken: vi.fn(),
  useRevokeMyToken: vi.fn(),
  useMySessions: vi.fn(),
  useRevokeMySession: vi.fn(),
  useChangePassword: mockUseChangePassword,
}));

const mockUseI18n = vi.mocked(useI18n);
const mockUseIdentity = vi.mocked(useIdentity);
const mockUseUpdateMe = vi.mocked(useUpdateMe);
const mockUseMyTokens = vi.mocked(useMyTokens);
const mockUseCreateMyToken = vi.mocked(useCreateMyToken);
const mockUseRevokeMyToken = vi.mocked(useRevokeMyToken);
const mockUseMySessions = vi.mocked(useMySessions);
const mockUseRevokeMySession = vi.mocked(useRevokeMySession);

/**
 * Builds minimal i18n payload needed by profile page tests.
 */
function createTranslations() {
  return {
    admin: {
      actions: { signOut: "退出登录" },
      profile: {
        tabBasic: "基本信息",
        tabMyTokens: "我的令牌",
        tabMySessions: "我的会话",
        activeTenant: "当前租户",
        workspaces: "工作区",
        permissions: "权限",
      },
      table: {
        loading: "加载中…",
      },
    },
  };
}

describe("ProfilePage", () => {
  it("submits password change from profile page", () => {
    const changePasswordMutateAsync = vi.fn().mockResolvedValue({ status: "ok" });

    mockUseI18n.mockReturnValue({
      locale: "zh-CN",
      t: createTranslations() as unknown as ReturnType<typeof useI18n>["t"],
      changeLocale: vi.fn(),
    });
    mockUseIdentity.mockReturnValue({
      identity: {
        user_id: 1,
        email: "owner@example.com",
        display_name: "Owner",
        avatar_url: null,
        active_tenant_id: 1,
        tenants: [{ id: 1, slug: "default", name: "Default" }],
        workspaces: [],
        permissions: ["membership:read"],
        roles: { platform: ["platform_admin"] },
      },
      isLoading: false,
    } as never);
    mockUseUpdateMe.mockReturnValue({
      mutateAsync: vi.fn().mockResolvedValue({}),
    } as never);
    mockUseMyTokens.mockReturnValue({ data: [], isLoading: false } as never);
    mockUseCreateMyToken.mockReturnValue({ mutate: vi.fn() } as never);
    mockUseRevokeMyToken.mockReturnValue({ mutate: vi.fn(), isPending: false } as never);
    mockUseMySessions.mockReturnValue({ data: [], isLoading: false } as never);
    mockUseRevokeMySession.mockReturnValue({ mutate: vi.fn(), isPending: false } as never);
    mockUseChangePassword.mockReturnValue({
      mutateAsync: changePasswordMutateAsync,
      isPending: false,
    } as never);

    render(<ProfilePage />);

    fireEvent.change(screen.getByLabelText("当前密码"), {
      target: { value: "OldPass!2026" },
    });
    fireEvent.change(screen.getByLabelText("新密码"), {
      target: { value: "NewPass!2026" },
    });
    fireEvent.click(screen.getByRole("button", { name: "修改密码" }));

    expect(changePasswordMutateAsync).toHaveBeenCalledWith({
      old_password: "OldPass!2026",
      new_password: "NewPass!2026",
    });
  });
});
