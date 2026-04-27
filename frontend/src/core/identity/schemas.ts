// frontend/src/core/identity/schemas.ts
import { z } from "zod";

const slugSchema = z
  .string()
  .min(2, "Slug must be at least 2 characters")
  .max(64, "Slug must be at most 64 characters")
  .regex(/^[a-z0-9-]+$/, "Slug must contain only lowercase letters, digits, or dashes");

const displayNameSchema = z
  .string()
  .min(1, "Display name is required")
  .max(128, "Display name must be at most 128 characters");

export const createTenantSchema = z.object({
  slug: slugSchema,
  name: displayNameSchema,
});
export type CreateTenantFields = z.infer<typeof createTenantSchema>;

export const renameTenantSchema = z.object({
  name: displayNameSchema,
});
export type RenameTenantFields = z.infer<typeof renameTenantSchema>;

export const createWorkspaceSchema = z.object({
  slug: slugSchema,
  name: displayNameSchema,
});
export type CreateWorkspaceFields = z.infer<typeof createWorkspaceSchema>;

export const renameWorkspaceSchema = z.object({
  name: displayNameSchema,
});
export type RenameWorkspaceFields = z.infer<typeof renameWorkspaceSchema>;

export const createUserSchema = z.object({
  email: z.string().email("Must be a valid email address"),
  display_name: z.string().max(128, "Display name must be at most 128 characters").optional(),
  initial_password: z
    .string()
    .refine((value) => value.length === 0 || value.length >= 8, {
      message: "Initial password must be at least 8 characters",
    })
    .optional(),
});
export type CreateUserFields = z.infer<typeof createUserSchema>;

export const createTenantTokenSchema = z.object({
  name: z.string().min(1, "Name is required").max(64, "Name must be at most 64 characters"),
  scopes: z.string().min(1, "At least one scope is required"),
  workspace_id: z.number().optional(),
});
export type CreateTenantTokenFields = z.infer<typeof createTenantTokenSchema>;

export const addWorkspaceMemberSchema = z.object({
  user_id: z.number({ required_error: "User id is required" }).int().positive("Must be a positive integer"),
  role: z.enum(["workspace_admin", "member", "viewer"]),
});
export type AddWorkspaceMemberFields = z.infer<typeof addWorkspaceMemberSchema>;

export const profileBasicSchema = z.object({
  display_name: displayNameSchema,
});
export type ProfileBasicFields = z.infer<typeof profileBasicSchema>;
