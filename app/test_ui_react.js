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
  // inside the app shell, account actions sit in the identity menu; pages outside it show them as buttons
  const account = async (item) => {
    const menu = page.locator("[aria-haspopup=menu]");
    if (await menu.count()) { await menu.click(); await page.getByRole("menuitem", { name: item }).click(); }
    else await page.getByRole("button", { name: item }).click();
  };
  const signOut = async () => { await account("Sign out"); await page.waitForURL(/\/app\/login$/); };
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
  for (const [u, p, want, title] of [["dr.rao", "doctor123", "/app/consultation", "Your OPD, at a glance."], ["staff", "staff123", "/app/front-desk", "Front desk"],
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
  check("session: survives a reload", (await heading()) === "Your OPD, at a glance.");
  await wait(1500);
  check("live: stream connected", (await page.getByText(/^Live updates on/).count()) === 1, await page.locator("main p").last().innerText());
  await signOut();
  await page.goto(B + "/app/front-desk");
  await page.waitForURL(/\/app\/login$/);
  check("guard: signed-out deep link goes to sign-in", true);

  // change password (wrong current, success, sign in with the new one), then put it back
  await login("staff", "staff123");
  await account("Change password");
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
  await account("Change password");
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

  // ---------- doctor consultation workspace ----------
  // test_ui.py prepared Dr. Rao's queue through the API: 001 Asha Verma, 002 Bilal Khan, 003 Chitra Nair checked in,
  // 004 Demo Patient booked and past their grace period, 005 Esha Gill checked in.
  const region = (name) => page.getByRole("region", { name });
  const said = () => page.locator("main p[role=status]").last().innerText();
  const tabs = async () => (await page.getByRole("tablist", { name: "Queue" }).innerText()).replace(/\u00a0/g, " ");
  const firstRow = () => page.getByRole("table", { name: "Waiting patients" }).locator("tbody tr").first().innerText();
  const click = async (name, scope = page) => { await scope.getByRole("button", { name }).first().click(); await wait(700); };
  await page.setViewportSize({ width: 1440, height: 1000 });
  await login("dr.rao", "doctor123");
  const links = page.getByRole("navigation").getByRole("link");
  check("shell: doctor sees only Consultation, marked current", (await links.count()) === 1 && (await links.first().getAttribute("aria-current")) === "page");
  check("shell: department and identity from the server", (await page.getByRole("complementary").innerText()).includes("General Medicine")
    && (await page.getByRole("banner").innerText()).includes("General Medicine · Doctor"));
  check("doctor: ready card shows the next waiting patient", (await region("Ready for the next patient").innerText()).includes("Asha Verma"));
  check("doctor: late patient counted under Skipped / late", (await tabs()).includes("Skipped / late  1"), await tabs());

  await click("Call next patient");
  check("doctor: call next → patient called", (await region("Patient called").innerText()).includes("Asha Verma") && (await said()).includes("Token 001 called"), await said());
  check("doctor: grace not over → Not here offered, not Skip", (await region("Patient called").getByRole("button", { name: "Not here" }).count()) === 1
    && (await region("Patient called").getByRole("button", { name: "Skip / no-show" }).count()) === 0);
  await click("Not here");
  await page.getByRole("dialog", { name: /as not here/ }).getByLabel("Note (optional)").fill("stepped out");
  await click("Mark not here", page.getByRole("dialog", { name: /as not here/ }));
  check("doctor: not here keeps the visit (moves to Skipped / late)", (await tabs()).includes("Skipped / late  2"), await tabs());
  await click("Call next patient");
  check("doctor: server calls the next checked-in patient", (await region("Patient called").innerText()).includes("Bilal Khan"));
  await page.getByRole("button", { name: "Start consultation" }).focus(); await page.keyboard.press("Enter"); await wait(700);
  check("doctor: keyboard Enter starts the consultation", (await region("Active consultation").innerText()).includes("Bilal Khan"));
  check("doctor: availability shows In consultation", (await page.getByRole("button", { name: /^Availability/ }).innerText()).includes("In consultation"));
  await click("Complete consultation");
  check("doctor: complete → ready again, seen today 1", (await region("Ready for the next patient").isVisible())
    && /Seen today\s+1\s/.test(await region("Session pulse").innerText()), await said());

  await click("Review patients →");
  const late = page.getByRole("dialog", { name: "Skipped & late patients" });
  check("doctor: skip offered only where the server allows it", (await late.getByRole("button", { name: "Skip / no-show" }).count()) === 1, await late.innerText());
  await click("Skip / no-show", late);
  const ns = page.getByRole("dialog", { name: /as no-show\?$/ });
  await click("Mark as no-show", ns);
  await page.getByRole("tab", { name: /Skipped/ }).click(); await wait(200);
  check("doctor: no-show recorded and the visit kept", (await page.getByRole("table", { name: "Skipped and late patients" }).innerText()).includes("Demo Patient")
    && (await said()).includes("marked as no-show"), await said());
  await page.getByRole("tab", { name: /Waiting/ }).click();

  await click("Ⅱ  Pause queue");
  await click("Pause queue", page.getByRole("dialog", { name: "Pause the queue?" }));
  check("availability: pause → queue paused, ETAs on hold", (await region("Queue paused").isVisible()) && (await firstRow()).includes("On hold"));
  await click("Resume queue");
  check("availability: resume → ready", await region("Ready for the next patient").isVisible());
  await page.getByRole("button", { name: /^Availability/ }).click();
  const av = page.getByRole("dialog", { name: "Your availability" });
  await av.getByText("Running late").click(); await av.getByLabel("Delay duration").selectOption("20");
  await click("Update & notify", av);
  check("availability: running late 20 min", /Delayed · (19|20) min/.test(await page.getByRole("button", { name: /^Availability/ }).innerText()));
  await page.getByRole("button", { name: /^Availability/ }).click();
  await av.getByText("Available", { exact: true }).click(); await click("Update availability", av);

  // another desk (a separate session: localhost has its own cookies) changes this queue
  const desk = await page.context().newPage();
  const D = B.replace("127.0.0.1", "localhost");
  await desk.goto(D + "/app/login");
  const dpost = (path, body) => desk.evaluate(([p, b]) => fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })
    .then(async (r) => ({ status: r.status, body: await r.json() })), [path, body]);
  await dpost("/api/login", { username: "staff", password: "staff123" });
  const deskQueue = () => desk.evaluate(() => fetch("/api/queue?doctor_id=1").then((r) => r.json()));
  const esha = (await deskQueue()).entries.find((e) => e.patient_name === "Esha Gill");
  check("live: stream connected (sidebar status)", (await page.getByRole("complementary").getByRole("status").innerText()).includes("Live updates on"));
  await dpost("/api/queue/action", { action: "emergency", appointment_id: esha.id, reason: "Acute breathlessness" });
  await wait(1500);
  check("live: emergency from the front desk appears without a reload", (await firstRow()).includes("Esha Gill") && (await firstRow()).includes("Emergency"), await firstRow());
  check("emergency: next in queue is the emergency patient", (await region("Ready for the next patient").innerText()).includes("Esha Gill"));
  await click("Call next patient"); await click("Start consultation");
  check("emergency: urgent consultation shown", (await region("Urgent consultation").innerText()).includes("Esha Gill"));
  await click("Complete urgent consultation");

  // concurrency: with the stream blocked this screen holds an old queue version; the desk changes the queue first
  await page.route("**/api/stream", (r) => r.fulfill({ status: 204 }));  // 204: EventSource stops without logging an error
  await page.reload(); await wait(1000);
  await dpost("/api/staff/walkin", { name: "Farah Iqbal", doctor_id: 1 });
  await click("Call next patient");
  const fail = page.getByRole("dialog", { name: "The queue could not be updated" });
  check("concurrency: a stale action is refused by the server, nothing saved", (await fail.isVisible()) && (await fail.innerText()).includes("The queue changed since you loaded it"), await fail.innerText().catch(() => ""));
  await click("Refresh queue", fail);
  check("concurrency: refresh shows the other desk's change", (await page.getByRole("table", { name: "Waiting patients" }).innerText()).includes("Farah Iqbal"));
  await click("Call next patient");
  check("concurrency: retry with the fresh version succeeds", (await region("Patient called").innerText()).includes("Chitra Nair"));
  const dq = await deskQueue(), chitra = dq.entries.find((e) => e.patient_name === "Chitra Nair");
  const both = await desk.evaluate(([id, v]) => Promise.all([1, 2].map(() => fetch("/api/queue/action", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action: "not_present", appointment_id: id, version: v }) }).then((r) => r.status))), [chitra.id, dq.version]);
  check("concurrency: two simultaneous actions on one version → exactly one applies", [...both].sort().join() === "200,409", String(both));
  await page.unroute("**/api/stream"); await page.reload(); await wait(1000);
  check("concurrency: the doctor's screen shows the applied change", await region("Ready for the next patient").isVisible());
  await desk.close();

  // responsive: 1920 wide, compact navigation 768–1279, one column with a drawer under 768
  await page.setViewportSize({ width: 1920, height: 1080 }); await wait(300);
  check("responsive 1920: consultation and queue side by side", await page.evaluate(() => { const [a, b] = [...document.querySelectorAll("main section[aria-label], main section[aria-labelledby]")].slice(1, 3).map((x) => x.getBoundingClientRect()); return Math.abs(a.top - b.top) < 2 && b.left > a.right; }));
  await page.setViewportSize({ width: 1024, height: 768 }); await wait(300);
  check("responsive 1024: compact navigation, no sideways scroll", (await page.getByRole("complementary").evaluate((x) => x.getBoundingClientRect().width)) === 72 && await noSideScroll());
  await page.setViewportSize({ width: 390, height: 844 }); await wait(300);
  await page.getByRole("button", { name: "Open navigation" }).click(); await wait(300);
  check("responsive 390: drawer navigation, no sideways scroll", (await page.getByRole("link", { name: "Consultation" }).isVisible()) && await noSideScroll());
  await page.keyboard.press("Escape"); await page.mouse.click(380, 400);
  await page.setViewportSize({ width: 1440, height: 1000 });
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
