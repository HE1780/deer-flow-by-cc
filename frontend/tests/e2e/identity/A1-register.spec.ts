// frontend/tests/e2e/identity/A1-register.spec.ts
import { expect, test, type Route } from "@playwright/test";

import { mockIdentity } from "./fixtures/mock-backend";

test.describe("A1: register page", () => {
  test("happy path: filling form posts /api/auth/register and lands on /", async ({
    page,
  }) => {
    // Unauthenticated /api/me + providers + logout already mocked here.
    await mockIdentity(page, { authenticated: false });

    // Prevent the singleflight refresh attempt from hitting the real gateway.
    await page.route("**/api/auth/refresh", (route: Route) =>
      route.fulfill({ status: 401, body: "" }),
    );

    let registerCalls = 0;
    await page.route("**/api/auth/register", (route: Route) => {
      registerCalls += 1;
      const body = route.request().postDataJSON() as {
        code?: string;
        email?: string;
        password?: string;
      };
      expect(body.code).toBe("test12345abcdef");
      expect(body.email).toBe("new@example.com");
      expect(body.password).toBe("longenoughpw");
      return route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok", email: "new@example.com" }),
      });
    });

    // Mock the post-success destination so we don't trigger real /api/me etc.
    await page.route("**/", (route: Route) => {
      if (route.request().resourceType() !== "document") return route.continue();
      return route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body><h1 id='landed'>landed</h1></body></html>",
      });
    });

    await page.goto("/register?code=test12345abcdef");

    await page.getByLabel(/^email$/i).fill("new@example.com");
    await page.getByLabel(/^password$/i).fill("longenoughpw");
    await page.getByRole("button", { name: /create account/i }).click();

    await page.waitForURL("**/");
    expect(registerCalls).toBe(1);
  });

  test("shows red banner when URL has no code", async ({ page }) => {
    await mockIdentity(page, { authenticated: false });
    await page.route("**/api/auth/refresh", (route: Route) =>
      route.fulfill({ status: 401, body: "" }),
    );
    await page.goto("/register");
    await expect(
      page.getByRole("alert").filter({ hasText: /invalid invitation link/i }),
    ).toBeVisible();
  });
});
