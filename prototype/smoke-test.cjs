// Run npm ci, npm run build, npm run serve, then npm test.
// PROTOTYPE_URL and CHROME_PATH can override local defaults.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROME_PATH
      ? { executablePath: process.env.CHROME_PATH }
      : {}),
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const url = process.env.PROTOTYPE_URL || "http://127.0.0.1:8080/prototype/";
    const route = async (path) => {
      await page.goto(url + "#" + path);
      await page.waitForTimeout(60);
    };
    const selectWorld = async (target, id) => {
      if (!(await target.locator(`[data-world="${id}"]`).count())) {
        const before = await target.locator("#balance").innerText();
        await target.locator('.shelf-controls [data-catalog="open"]').click();
        await target.locator(`[data-catalog-select="${id}"]`).click();
        assert.equal(await target.locator("#balance").innerText(), before);
      } else await target.locator(`[data-world="${id}"]`).click();
      assert.equal(
        await target
          .locator(`[data-world="${id}"]`)
          .getAttribute("aria-pressed"),
        "true",
      );
    };
    await route("home");
    await page.locator("#onboarding");
    for (let i = 0; i < 3; i++) await page.locator("[data-tour-next]").click();
    await page.locator('[data-tour-stage="0"]').click();
    assert.equal(await page.locator("#onboarding .citizen").count(), 2);
    await page.locator('[data-tour-stage="4"]').click();
    assert.equal(await page.locator("#onboarding .citizen").count(), 10);
    await page.locator("[data-tour-next]").click();
    assert.equal(await page.locator("#balance").innerText(), "145");
    await route("home");
    assert.ok(await page.locator('[data-unovis="stacked"] svg').count());
    assert.ok(await page.locator('[data-unovis="donut"] svg').count());
    await page.locator('[data-task="math"]').first().click();
    await page.locator("#toggle-timer").click();
    await page.waitForTimeout(1200);
    await page.locator("#toggle-timer").click();
    const first = await page.locator("#timer-value").innerText();
    await page.locator('[data-task="russian"]').click();
    await page.locator("#toggle-timer").click();
    await page.waitForTimeout(1100);
    await page.locator("#toggle-timer").click();
    await page.locator('[data-task="math"]').click();
    assert.equal(await page.locator("#timer-value").innerText(), first);
    await page.reload();
    assert.equal(await page.locator("#timer-value").innerText(), first);
    await page.locator("#save-timer").click();
    assert.equal(await page.locator("#timer-value").innerText(), "00:00:00");
    await page.locator('input[name="minutes"]').fill("25");
    await page.locator("#manual-form button").click();
    assert.ok(await page.getByText("Таймер", { exact: true }).count());
    assert.ok(await page.getByText("Вручную", { exact: true }).count());
    assert.ok(await page.locator('[data-unovis="line"] svg').count());
    await route("home");
    await page.locator('[data-chore="room"]').check();
    await page.reload();
    assert.ok(await page.locator('[data-chore="room"]').isChecked());
    await route("world");
    await page.locator('[data-buy="meadow"]').click();
    assert.equal(await page.locator("#balance").innerText(), "85");
    assert.equal(await page.locator(".world-stage .citizen").count(), 4);
    assert.ok(await page.locator('[data-buy="meadow"]').isDisabled());
    await selectWorld(page, "bricks");
    assert.equal(await page.locator(".world-stage .citizen").count(), 2);
    await page.locator('[data-preview="4"]').first().click();
    assert.equal(await page.locator(".world-stage .citizen").count(), 10);
    assert.equal(await page.locator("#balance").innerText(), "85");
    await page.locator('[data-preview="actual"]').click();
    await page.locator('[data-world="settlers"]').click();
    assert.equal(await page.locator(".world-stage .citizen").count(), 4);
    await page.reload();
    assert.equal(await page.locator(".world-stage .citizen").count(), 4);
    await page.locator('[data-theme-choice="dark"]').click();
    assert.equal(await page.locator("body").getAttribute("data-theme"), "dark");
    await page.locator('[data-theme-choice="system"]').click();
    await page.emulateMedia({ colorScheme: "light" });
    assert.equal(
      await page.locator("body").getAttribute("data-theme"),
      "light",
    );
    await page.emulateMedia({ colorScheme: "dark" });
    await page.waitForTimeout(100);
    assert.equal(await page.locator("body").getAttribute("data-theme"), "dark");
    await page.locator(".profile-trigger").click();
    await page.locator("#profile-form").waitFor({ state: "visible" });
    assert.ok(await page.locator("#profile-form").count());
    assert.equal(await page.locator("#new-task").count(), 0);
    assert.equal(await page.locator('input[type="password"]').count(), 0);
    await page.locator('#profile-form input[name="name"]').fill("Лёша");
    await page.locator("#profile-form button").click();
    assert.equal(await page.locator("#header-name").innerText(), "Лёша");
    await page.locator("#sign-out").click();
    assert.ok(await page.locator("#signed-out").isVisible());
    assert.ok(await page.locator(".app").isHidden());
    await page.reload();
    assert.ok(await page.locator("#signed-out").isVisible());
    await page.locator("#demo-sign-in").click();
    assert.equal(await page.locator("#balance").innerText(), "85");
    await route("settings");
    assert.equal(await page.locator("#profile-form").count(), 0);
    await page.locator('input[name="name"]').fill("Покормить кота");
    await page.locator("#new-task button").click();
    await route("chores");
    assert.ok(await page.getByText("Покормить кота", { exact: true }).count());
    for (const [width, height] of [
      [390, 844],
      [844, 390],
      [768, 1024],
      [1024, 768],
      [1440, 900],
    ]) {
      await page.setViewportSize({ width, height });
      for (const path of [
        "home",
        "task/math",
        "chores",
        "world",
        "rewards",
        "settings",
        "profile",
      ]) {
        await route(path);
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
          `Overflow: ${path} ${width}x${height}`,
        );
      }
    }
    await route("world");
    await page.locator('[data-tour="open"]').first().click();
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(
      await page
        .locator("#onboarding")
        .evaluate((el) => el.scrollWidth > el.clientWidth),
      false,
    );
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#onboarding").count(), 0);
    assert.deepEqual(errors, []);
    if (process.env.SCREENSHOT_DIR) {
      await page.waitForTimeout(3600);
      await page.setViewportSize({ width: 390, height: 844 });
      await route("home");
      await page.screenshot({
        path: process.env.SCREENSHOT_DIR + "/vse-uspeyu-mobile-dark.png",
        fullPage: true,
      });
      await route("settings");
      await page.locator('[data-theme-choice="light"]').click();
      await page.setViewportSize({ width: 1440, height: 1100 });
      await route("home");
      await page.screenshot({
        path: process.env.SCREENSHOT_DIR + "/vse-uspeyu-desktop.png",
        fullPage: true,
      });
      await route("world");
      await page.locator('[data-preview="4"]').first().click();
      await page.waitForTimeout(800);
      await page.screenshot({
        path: process.env.SCREENSHOT_DIR + "/vse-uspeyu-world.png",
        fullPage: true,
      });
      await page.locator('[data-tour="open"]').first().click();
      for (let i = 0; i < 3; i++)
        await page.locator("[data-tour-next]").click();
      await page.waitForTimeout(800);
      await page.screenshot({
        path: process.env.SCREENSHOT_DIR + "/vse-uspeyu-tour.png",
      });
    }
    // Separate fixture: enough test-only currency to exercise every dependency.
    const progression = await browser.newPage();
    const fixtureErrors = [];
    progression.on("pageerror", (error) => fixtureErrors.push(error.message));
    await progression.goto(url);
    await progression.locator("[data-tour-close]").first().click();
    await progression.evaluate(() => {
      const key = "vse-uspeyu-prototype-v1";
      const state = JSON.parse(localStorage.getItem(key));
      state.balance = 10000;
      localStorage.setItem(key, JSON.stringify(state));
    });
    await progression.goto(url + "#world");
    await progression.reload();
    let spent = 0;
    for (const world of ["settlers", "bricks", "voxel", "helpers"]) {
      await selectWorld(progression, world);
      assert.equal(
        await progression
          .locator(".world-stage [data-world-art]")
          .getAttribute("data-world-art"),
        world,
      );
      assert.ok(
        await progression
          .locator(".world-stage")
          .evaluate(
            (el) =>
              el
                .getAnimations({ subtree: true })
                .filter((a) => !a.effect.target.closest(".citizen")).length > 2,
          ),
        "Environment should animate, not just citizens",
      );
      if (process.env.SCREENSHOT_DIR) {
        await progression.waitForTimeout(800);
        await progression
          .locator(".world-stage")
          .screenshot({
            path: process.env.SCREENSHOT_DIR + "/vse-" + world + "-start.png",
          });
      }
      assert.equal(
        await progression.locator(".world-stage .citizen").count(),
        2,
      );
      assert.ok(await progression.locator('[data-buy="beacon"]').isDisabled());
      for (const [index, upgrade] of [
        "meadow",
        "workshop",
        "harbor",
        "beacon",
      ].entries()) {
        await progression.locator(`[data-buy="${upgrade}"]`).click();
        spent += [60, 90, 120, 180][index];
        assert.equal(
          await progression.locator("#balance").innerText(),
          String(10000 - spent),
        );
        assert.equal(
          await progression.locator(".world-stage .citizen").count(),
          4 + index * 2,
        );
        assert.ok(
          await progression.locator(`[data-buy="${upgrade}"]`).isDisabled(),
        );
      }
    }
    assert.ok(
      await progression
        .locator(".world-rail")
        .evaluate((el) => el.scrollWidth > el.clientWidth),
    );
    await progression.locator('.shelf-controls [data-catalog="open"]').click();
    await progression.locator("#catalog-search").fill("Куболесье");
    assert.equal(await progression.locator(".catalog-world").count(), 1);
    await progression.locator("#catalog-search").fill("Нет такого мира");
    assert.equal(await progression.locator(".catalog-world").count(), 0);
    await progression.keyboard.press("Escape");
    assert.equal(await progression.locator("[data-motion]").count(), 0);
    assert.ok(
      await progression
        .locator(".world-stage")
        .evaluate((el) =>
          el
            .getAnimations({ subtree: true })
            .some((a) => a.playState === "running"),
        ),
    );
    await progression.reload();
    assert.equal(
      await progression.locator(".world-stage .citizen").count(),
      10,
    );
    await progression.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(
      await progression
        .locator(".world-stage")
        .evaluate(
          (el) =>
            el
              .getAnimations({ subtree: true })
              .filter((a) => a.playState === "running").length,
        ),
      0,
    );
    await progression.emulateMedia({ reducedMotion: "no-preference" });
    await progression.goto(url + "#home");
    await progression.locator(".living-hero").waitFor();
    assert.equal(
      await progression
        .locator(".island-scene")
        .evaluate(
          (el) =>
            el
              .getAnimations({ subtree: true })
              .filter((a) => a.playState === "running").length,
        ),
      0,
    );
    await progression.goto(url + "#world");
    await progression.locator(".world-stage").waitFor();
    // Migration preserves existing v0.1 purchases without charging again.
    await progression.evaluate(() => {
      const key = "vse-uspeyu-prototype-v1";
      const state = JSON.parse(localStorage.getItem(key));
      delete state.worldVersion;
      delete state.worlds;
      delete state.activeWorld;
      state.bought = ["garden"];
      state.balance = 85;
      state.purchases = [];
      localStorage.setItem(key, JSON.stringify(state));
    });
    await progression.reload();
    assert.equal(await progression.locator(".world-stage .citizen").count(), 4);
    assert.equal(await progression.locator("#balance").innerText(), "85");
    await progression.setViewportSize({ width: 390, height: 844 });
    await progression.locator('#main [data-tour="open"]').click();
    assert.equal(
      await progression.locator("#onboarding").evaluate((el) => el.scrollTop),
      0,
    );
    assert.equal(
      await progression.evaluate(() => document.activeElement.id),
      "tour-title",
    );
    await progression.keyboard.press("Escape");
    // All-time history: widely separated dates connect; repeated dates aggregate.
    await progression.evaluate(() => {
      const key = "vse-uspeyu-prototype-v1";
      const state = JSON.parse(localStorage.getItem(key));
      state.entries = [
        { task: "math", date: "2023-01-03", seconds: 600, source: "Демо" },
        { task: "math", date: "2023-01-03", seconds: 300, source: "Демо" },
        { task: "math", date: "2023-04-17", seconds: 1800, source: "Демо" },
        { task: "math", date: "2025-06-20", seconds: 2400, source: "Демо" },
        { task: "english", date: "2020-02-02", seconds: 60, source: "Демо" },
      ];
      localStorage.setItem(key, JSON.stringify(state));
    });
    await progression.goto(url + "#task/math");
    await progression.reload();
    await progression.locator('[data-unovis="line"] svg').waitFor();
    await progression.locator(".chart-data summary").click();
    const dataRows = progression.locator(".chart-data tbody tr");
    assert.equal(await dataRows.count(), 3);
    assert.equal(await dataRows.first().locator("td").nth(1).innerText(), "15");
    const linePath = await progression
      .locator('[data-unovis="line"] path[class*="linePath"]')
      .first()
      .getAttribute("d");
    assert.equal((linePath.match(/M/g) || []).length, 1);
    assert.equal((linePath.match(/L/g) || []).length, 2);
    assert.equal(await progression.locator(".table-wrap tbody tr").count(), 4);
    await progression.goto(url + "#task/english");
    await progression.locator('[data-unovis="line"] svg').waitFor();
    assert.equal(await progression.locator(".chart-data tbody tr").count(), 1);
    await progression.goto(url + "#task/nature");
    await progression
      .getByText("Пока нет записей за это занятие.", { exact: false })
      .waitFor();
    assert.equal(await progression.locator('[data-unovis="line"]').count(), 0);
    assert.deepEqual(fixtureErrors, []);
    await progression.close();
    console.log(
      "PASS: onboarding, profile/sign out, 3 themes, live worlds, separate progress, previews, Unovis charts, timers, persistence, 35 responsive page checks; no JS errors.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
