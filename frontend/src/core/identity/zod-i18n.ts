// frontend/src/core/identity/zod-i18n.ts
// Custom zod error map that overrides generic messages with translation-friendly
// equivalents. Install once at app startup via `z.setErrorMap(identityZodErrorMap)`.
import { type ZodErrorMap, ZodIssueCode, ZodParsedType } from "zod";

export const identityZodErrorMap: ZodErrorMap = (issue, ctx) => {
  switch (issue.code) {
    case ZodIssueCode.too_small:
      if (issue.type === "string") {
        return {
          message:
            issue.minimum === 1
              ? "This field is required."
              : `Must be at least ${issue.minimum} characters.`,
        };
      }
      return { message: ctx.defaultError };

    case ZodIssueCode.too_big:
      if (issue.type === "string") {
        return { message: `Must be at most ${issue.maximum} characters.` };
      }
      return { message: ctx.defaultError };

    case ZodIssueCode.invalid_string:
      if (issue.validation === "email") {
        return { message: "Must be a valid email address." };
      }
      if (issue.validation === "regex") {
        return { message: "Invalid format." };
      }
      return { message: ctx.defaultError };

    case ZodIssueCode.invalid_type:
      if (issue.received === ZodParsedType.undefined) {
        return { message: "This field is required." };
      }
      return { message: ctx.defaultError };

    default:
      return { message: ctx.defaultError };
  }
};
