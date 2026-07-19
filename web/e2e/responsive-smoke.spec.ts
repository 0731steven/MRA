import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "开发者一键登录" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("mobile routes stay within the viewport and restore scroll", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("mobile"), "mobile regression");
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  const mobileNavigation = page.getByRole("navigation", { name: "主导航" });
  await mobileNavigation.getByRole("button", { name: /题库/ }).click();
  await expect(page.getByRole("heading", { name: "概率统计题库" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  const viewport = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(viewport.scroll).toBeLessThanOrEqual(viewport.client + 1);
  const overflowingCards = await page.locator("article").evaluateAll((cards) => cards.filter(card => card.getBoundingClientRect().right > document.documentElement.clientWidth + 1).length);
  expect(overflowingCards).toBe(0);

  await mobileNavigation.getByRole("button", { name: /答疑/ }).click();
  await expect(page.getByRole("heading", { name: "智能答疑" })).toBeVisible();
  await expect(page.getByRole("button", { name: "设置" })).toBeVisible();
  await page.getByRole("button", { name: "设置" }).click();
  await expect(page.getByText("答疑设置与历史会话")).toBeVisible();
});

test("desktop teacher workspace exposes delivery actions", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("desktop"), "desktop regression");
  await page.goto("/teaching");
  await expect(page.getByRole("heading", { name: "分层教学包工作台" })).toBeVisible();
  expect(await page.locator("main main").count()).toBe(0);
  await page.goto("/classrooms");
  await expect(page.getByRole("heading", { name: "班级认知雷达" })).toBeVisible();
  await expect(page.getByRole("button", { name: "创建班级", exact: true }).first()).toBeVisible();
});
