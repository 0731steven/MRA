import { expect, test } from "@playwright/test";

test("teacher demo exposes evidence and teaching workflows", async ({ page }) => {
  await page.goto("./login");
  await page.getByRole("button", { name: /进入教师端演示/ }).click();
  await expect(page).toHaveURL(/\/MRA\/dashboard$/);
  await expect(page.getByText("模拟演示").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "打开演示教师的账号菜单" })).toBeVisible();

  await page.goto("./classrooms");
  await expect(page.getByRole("heading", { name: "班级认知雷达" })).toBeVisible();
  await expect(page.getByText("条件方向存在稳定混淆")).toHaveCount(0);
  await expect(page.getByText("前置回补组").first()).toBeVisible();

  await page.goto("./teaching");
  await expect(page.getByRole("heading", { name: "分层教学包工作台" })).toBeVisible();
  await page.locator("button").filter({ hasText: "贝叶斯公式 · 45分钟分层教学包" }).first().click();
  await expect(page.getByRole("heading", { name: "贝叶斯公式 · 45分钟分层教学包" })).toBeVisible();
});

test("student demo covers tasks, learning path, questions, and tutor", async ({ page }) => {
  await page.goto("./login");
  await page.getByRole("button", { name: /进入学生端演示/ }).click();
  await expect(page.getByRole("button", { name: "打开演示学生的账号菜单" })).toBeVisible();

  await page.goto("./tasks");
  await expect(page.getByRole("heading", { name: "我的任务" })).toBeVisible();
  await expect(page.getByText("条件概率课前诊断").first()).toBeVisible();

  await page.goto("./learning-path");
  await expect(page.getByRole("heading", { name: /下一步，先学好/ })).toBeVisible();
  await expect(page.getByText("条件方向存在稳定混淆")).toBeVisible();

  await page.goto("./questions");
  await expect(page.getByRole("heading", { name: "概率统计题库" })).toBeVisible();
  await expect(page.getByText("P000001").first()).toBeVisible();

  await page.goto("./tutor");
  await page.getByLabel("输入问题").fill("如何判断一道题该用贝叶斯公式？");
  await page.getByRole("button", { name: "发送问题" }).click();
  await expect(page.getByText("回答来源：模拟题库演示")).toBeVisible({ timeout: 10_000 });
});

test("demo remains usable on a mobile viewport", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "demo-mobile", "mobile-only regression");
  await page.goto("./login");
  await page.getByRole("button", { name: /进入学生端演示/ }).click();
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  const width = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  expect(width.scroll).toBeLessThanOrEqual(width.client + 1);
});
