import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import UserDetailPage from "@/app/(admin)/admin/users/[id]/page";
import { useI18n } from "@/core/i18n/hooks";
import {
  useAdminSetPassword,
  useAddWorkspaceMember,
  useIdentity,
  usePatchWorkspaceMemberRole,
  useUser,
  useWorkspaceMembers,
  useWorkspaces,
} from "@/core/identity/hooks";

vi.mock("react", async () => {
  const actual = await vi.importActual("react");
  return {
    ...actual,
    use: (value: unknown) => (value instanceof Promise ? { id: "7" } : value),
  };
});

vi.mock("next/link", () => ({
  default: (props: React.ComponentProps<"a">) => <a {...props} />,
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: vi.fn(),
}));

vi.mock("@/core/identity/hooks", () => ({
  useIdentity: vi.fn(),
  useUser: vi.fn(),
  useWorkspaces: vi.fn(),
  useWorkspaceMembers: vi.fn(),
  usePatchWorkspaceMemberRole: vi.fn(),
  useAddWorkspaceMember: vi.fn(),
  useAdminSetPassword: vi.fn(),
}));

const mockUseI18n = vi.mocked(useI18n);
const mockUseIdentity = vi.mocked(useIdentity);
const mockUseUser = vi.mocked(useUser);
const mockUseWorkspaces = vi.mocked(useWorkspaces);
const mockUseWorkspaceMembers = vi.mocked(useWorkspaceMembers);
const mockUsePatchWorkspaceMemberRole = vi.mocked(usePatchWorkspaceMemberRole);
const mockUseAddWorkspaceMember = vi.mocked(useAddWorkspaceMember);
const mockUseAdminSetPassword = vi.mocked(useAdminSetPassword);

/**
 * Creates the minimal translation object required by the user detail page.
 */
function createTranslations() {
  return {
    admin: {
      table: {
        loading: "加载中…",
        backToUsers: "返回用户",
        colRoles: "角色",
        colStatus: "状态",
        colLastLogin: "最后登录",
        statusActive: "正常",
        statusDisabled: "禁用",
      },
    },
  };
}

describe("UserDetailPage", () => {
  it("allows updating workspace role from user detail page", () => {
    const patchMutate = vi.fn();
    const addMutate = vi.fn();

    mockUseI18n.mockReturnValue({
      locale: "zh-CN",
      t: createTranslations() as unknown as ReturnType<typeof useI18n>["t"],
      changeLocale: vi.fn(),
    });
    mockUseIdentity.mockReturnValue({
      identity: {
        active_tenant_id: 1,
        permissions: ["membership:read", "membership:invite"],
      },
    } as never);
    mockUseUser.mockReturnValue({
      data: {
        id: 7,
        email: "user@example.com",
        display_name: "User",
        status: 1,
        last_login_at: null,
        roles: ["member"],
      },
      isLoading: false,
      isError: false,
    } as never);
    mockUseWorkspaces.mockReturnValue({
      data: {
        items: [{ id: 3, name: "Workspace A", slug: "a", tenant_id: 1 }],
      },
      isLoading: false,
    } as never);
    mockUseWorkspaceMembers.mockReturnValue({
      data: {
        items: [{ id: 7, email: "user@example.com", role: "member" }],
      },
    } as never);
    mockUsePatchWorkspaceMemberRole.mockReturnValue({
      mutate: patchMutate,
      isPending: false,
    } as never);
    mockUseAddWorkspaceMember.mockReturnValue({
      mutate: addMutate,
      isPending: false,
    } as never);
    mockUseAdminSetPassword.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as never);

    render(<UserDetailPage params={Promise.resolve({ id: "7" })} />);

    fireEvent.change(screen.getByLabelText("工作区"), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByLabelText("工作区角色"), {
      target: { value: "workspace_admin" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存角色" }));

    expect(patchMutate).toHaveBeenCalledWith({
      userId: 7,
      role: "workspace_admin",
    });
    expect(addMutate).not.toHaveBeenCalled();
  });

  it("allows admin to reset user password from user detail page", () => {
    const resetMutate = vi.fn();

    mockUseI18n.mockReturnValue({
      locale: "zh-CN",
      t: createTranslations() as unknown as ReturnType<typeof useI18n>["t"],
      changeLocale: vi.fn(),
    });
    mockUseIdentity.mockReturnValue({
      identity: {
        active_tenant_id: 1,
        permissions: ["membership:read", "membership:invite"],
      },
    } as never);
    mockUseUser.mockReturnValue({
      data: {
        id: 7,
        email: "user@example.com",
        display_name: "User",
        status: 1,
        last_login_at: null,
        roles: ["member"],
      },
      isLoading: false,
      isError: false,
    } as never);
    mockUseWorkspaces.mockReturnValue({
      data: { items: [] },
      isLoading: false,
    } as never);
    mockUseWorkspaceMembers.mockReturnValue({
      data: { items: [] },
    } as never);
    mockUsePatchWorkspaceMemberRole.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as never);
    mockUseAddWorkspaceMember.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
    } as never);
    mockUseAdminSetPassword.mockReturnValue({
      mutate: resetMutate,
      isPending: false,
    } as never);

    render(<UserDetailPage params={Promise.resolve({ id: "7" })} />);

    fireEvent.change(screen.getAllByLabelText("新密码")[0]!, {
      target: { value: "TempPass!2026" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "重置密码" })[0]!);

    expect(resetMutate).toHaveBeenCalledWith({
      email: "user@example.com",
      password: "TempPass!2026",
    });
  });
});
