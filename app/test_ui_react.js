// Browser checks for the React frontend under /app/. Run through test_ui.py (fills in __BASE__).
// Selectors are roles and labels, so they survive markup changes. Grows screen by screen with the migration.
async page => {
  const B = "__BASE__";
  const out = [];
  const check = (name, ok, detail = "") => out.push(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  (" + detail + ")" : ""}`);
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/status of 40[0-9]/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  const wait = (ms) => page.waitForTimeout(ms);
  const signIn = page.getByRole("region", { name: "Sign in" });
  const login = async (u, p) => {
    await page.goto(B + "/app/login");
    await signIn.getByLabel("Username").fill(u);
    await signIn.getByLabel("Password").fill(p);
    await signIn.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL((url) => !String(url).endsWith("/login"));
    await wait(300);
  };
  const signOut = async () => { await page.getByRole("button", { name: "Sign out" }).click(); await page.waitForURL(/\/app\/login$/); };
  const heading = () => page.getByRole("heading", { level: 1 }).innerText();
  const path = () => page.url().replace(/^https?:\/\/[^/]+/, "").split("?")[0];  // run-code has no URL global
  const noSideScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

  await page.setViewportSize({ width: 1440, height: 1000 });

  // legacy UI untouched at "/"
  await page.goto(B + "/");
  check("legacy: still served at /", await page.locator("#login").isVisible());

  // signed out
  await page.goto(B + "/app/");
  await page.waitForURL(/\/app\/login$/);
  check("signed out: /app/ goes to sign-in", (await heading()) === "Sign in to SmartOPD");
  check("signed out: demo accounts listed", await page.getByText("Demo accounts:").isVisible());
  const font = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  check("design: Inter from our own origin", font.startsWith('"Inter Variable"') && await page.evaluate(() => document.fonts.check("14px 'Inter Variable'")), font);

  await signIn.getByLabel("Username").fill("patient");
  await signIn.getByLabel("Password").fill("wrong-password");
  await signIn.getByRole("button", { name: "Sign in" }).click();
  await wait(300);
  check("sign in: wrong password rejected", await page.getByText("Wrong username or password.").isVisible());

  await page.getByRole("button", { name: "Forgot password?" }).click();
  const fp = page.getByRole("dialog", { name: "Forgot password" });
  check("forgot password: dialog opens with the username", await fp.isVisible() && (await fp.getByLabel("Username").inputValue()) === "patient");
  await fp.getByRole("button", { name: "Send code" }).click();
  await wait(300);
  check("forgot password: neutral reply", (await fp.getByRole("status").innerText()).includes("If that account"));
  await page.keyboard.press("Escape");
  check("forgot password: Escape closes", !(await fp.isVisible()));

  // every role lands on its own screen; the server's role decides
  for (const [u, p, want, title] of [["dr.rao", "doctor123", "/app/consultation", "Consultation"], ["staff", "staff123", "/app/front-desk", "Front desk"],
    ["admin", "admin123", "/app/admin", "Administration"], ["patient", "patient123", "/app/patient", "Your appointments"],
    ["tester", "tester123", "/app/simulations", "Simulations"]]) {
    await login(u, p);
    check(`${u}: lands on ${want}`, path() === want && (await heading()) === title, page.url());
    await signOut();
  }

  // role guard and deep links
  await login("dr.rao", "doctor123");
  await page.goto(B + "/app/admin");
  await page.waitForURL(/\/app\/consultation$/);
  check("guard: doctor sent away from /app/admin", true);
  await page.reload();
  check("session: survives a reload", (await heading()) === "Consultation");
  await wait(1500);
  check("live: stream connected", (await page.getByText(/^Live updates on/).count()) === 1, await page.locator("main p").last().innerText());
  await signOut();
  await page.goto(B + "/app/front-desk");
  await page.waitForURL(/\/app\/login$/);
  check("guard: signed-out deep link goes to sign-in", true);

  // change password (wrong current, success, sign in with the new one), then put it back
  await login("staff", "staff123");
  await page.getByRole("button", { name: "Change password" }).click();
  const cp = page.getByRole("dialog", { name: "Change password" });
  await cp.getByLabel("Current password").fill("not-it-at-all");
  await cp.getByLabel("New password").fill("staff12345");
  await cp.getByRole("button", { name: "Save password" }).click();
  await wait(300);
  check("password: wrong current rejected", (await cp.getByRole("status").innerText()).includes("current password is wrong"));
  await cp.getByLabel("Current password").fill("staff123");
  await cp.getByRole("button", { name: "Save password" }).click();
  await wait(1600);
  check("password: changed and dialog closed", !(await cp.isVisible()));
  await signOut();
  await login("staff", "staff12345");
  check("password: sign in with the new one", path() === "/app/front-desk");
  await page.evaluate(() => fetch("/api/password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current: "staff12345", new: "staff123" }) }));

  // session ended elsewhere: the next request returns to sign-in with a notice
  await page.evaluate(() => fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }));
  await page.getByRole("button", { name: "Change password" }).click();
  await cp.getByLabel("Current password").fill("staff123");
  await cp.getByLabel("New password").fill("whatever123");
  await cp.getByRole("button", { name: "Save password" }).click();
  await page.waitForURL(/\/app\/login$/);
  check("session: expiry returns to sign-in with a notice", await page.getByText("Your session ended. Please sign in again.").isVisible());

  // register a new patient
  const reg = page.getByRole("region", { name: "New patient? Register" });
  await reg.getByLabel("Full name").fill("React Tester");
  await reg.getByLabel("Phone").fill("+91 90000 12345");
  await reg.getByLabel("Username").fill("react.tester");
  await reg.getByLabel("Password").fill("longenough");
  await reg.getByRole("button", { name: "Register" }).click();
  await page.waitForURL(/\/app\/patient$/);
  check("register: new patient signed in", (await page.getByText("React Tester").count()) === 1);
  await signOut();

  // design system page renders, dialog opens
  await page.goto(B + "/app/design-system");
  await page.getByRole("button", { name: "Open dialog" }).click();
  check("design system: dialog opens", await page.getByRole("dialog", { name: "Pause the queue?" }).isVisible());
  await page.keyboard.press("Escape");

  // phone width
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(B + "/app/login");
  await wait(300);
  check("mobile: sign-in has no sideways scroll", await noSideScroll());

  check("no console or page errors (HTTP 4xx answers excluded)", errors.length === 0, errors.join(" | "));
  return out.join("\n");
}
