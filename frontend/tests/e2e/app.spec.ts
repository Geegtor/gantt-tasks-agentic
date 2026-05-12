import path from "path";
import { test, expect } from "@playwright/test";

const sampleXlsx = path.join(__dirname, "../../../demo/sample_tasks.xlsx");

test.describe("Gantt AI smoke", () => {
  test("reset, upload Excel, chat (mock LLM), export", async ({ page, request }) => {
    const reset = await request.post("http://localhost:8000/reset");
    expect(reset.ok()).toBeTruthy();

    await page.goto("/");

    await page.locator('input[type="file"]').setInputFiles(sampleXlsx);
    await expect(page.getByText(/Loaded Excel/i)).toBeVisible({ timeout: 20_000 });

    const textarea = page.locator("textarea");
    await textarea.fill("extend Frontend by 3 days");
    await page.getByRole("button", { name: /send message/i }).click();

    await expect(page.getByText(/Extended/i)).toBeVisible({ timeout: 20_000 });

    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("link", { name: /Export Excel/i }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/\.xlsx$/i);
  });
});
