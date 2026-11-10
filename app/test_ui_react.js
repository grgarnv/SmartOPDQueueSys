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
  for (const [u, p, want, title] of [["dr.rao", "doctor123", "/app/consultation", "Your OPD, at a glance."], ["staff", "staff123", "/app/front-desk", "A smooth start to every visit."],
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

  // session ended elsewhere: the next request (here the front desk's own live refresh) returns to sign-in with a notice
  await page.evaluate(() => fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }));
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

  // ---------- front desk and queue monitor (staff, admin) ----------
  // test_ui.py prepared Dr. Iyer's queue (doctor 2): 001 Gita Rao, 002 Hari Das checked in; 003 Ira Skipped and
  // 005 Rhea Again skipped; 004 Lal Late booked, turn missed a minute ago (late within grace); 006 Tara Twice booked.
  await login("staff", "staff123");
  const other = await page.context().newPage();  // another desk (localhost: its own cookies)
  await other.goto(D + "/app/login");
  const opost = (p, b) => other.evaluate(([p, b]) => fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) })
    .then(async (r) => ({ status: r.status, body: await r.json() })), [p, b]);
  await opost("/api/login", { username: "staff", password: "staff123" });
  const iyer = () => other.evaluate(() => fetch("/api/queue?doctor_id=2").then((r) => r.json()));
  const entry = async (name) => (await iyer()).entries.find((e) => e.patient_name === name);
  const pol = await other.evaluate(() => fetch("/api/admin/policy").then((r) => r.json()));
  const dialog = (name) => page.getByRole("dialog", { name });
  const lookup = region("Find a patient or appointment");
  const lookFor = async (term) => {
    await lookup.getByLabel("Find a patient or appointment").fill(term);
    await lookup.getByRole("button", { name: "Find appointment" }).click(); await wait(800);
  };
  const wk = region("Walk-in registration");
  // browser-side validation: count queue-action requests, so "refused without a reason" proves nothing was sent
  let actionPosts = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/api/queue/action")) actionPosts++; });
  const pickDoctor = async (scope, name) => scope.getByLabel("Doctor *").selectOption(await scope.getByLabel("Doctor *").locator("option", { hasText: name }).getAttribute("value"));
  const clockOf = (t) => { const [h, m] = t.slice(11, 16).split(":").map(Number); return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`; };
  const overviewOf = async (name) => (await other.evaluate(() => fetch("/api/admin/overview").then((r) => r.json()))).doctors.find((d) => d.name === name);

  const displayLink = page.getByRole("link", { name: "Open waiting room display" });
  check("desk: today's check-in code and the waiting-room link", (await page.locator("main").innerText()).includes(`Check-in code today ${pol.checkin_code}`)
    && (await displayLink.getAttribute("href")) === `/?display=${pol.display_key}` && (await displayLink.getAttribute("target")) === "_blank");
  check("desk: walk-in needs a doctor first", await wk.getByRole("button", { name: "Save & check in" }).isDisabled());
  await wk.getByLabel("Department *").selectOption("General Medicine");
  const offered = await wk.getByLabel("Doctor *").locator("option").allInnerTexts();
  check("desk: only doctors holding OPD in that department are offered", offered.some((o) => o.startsWith("Dr. Iyer")) && offered.some((o) => o.startsWith("Dr. Rao"))
    && !offered.some((o) => o.includes("Khan")), offered.join(" | "));
  await pickDoctor(wk, "Dr. Iyer");
  await wk.getByLabel("Full name *").fill("Walk Tester");
  await wk.getByLabel("Phone for alerts (optional)").fill("12ab");
  await click("Save & check in", wk);
  check("desk: walk-in refusal shows the server's message", (await wk.innerText()).includes("Phone numbers may contain digits, spaces and a leading +."));
  await wk.getByLabel("Phone for alerts (optional)").fill("+91 92222 22222");
  await wk.getByLabel("Full name *").focus(); await page.keyboard.press("Enter"); await wait(900);
  const issuedDlg = dialog("Patient checked in");
  const issuedText = await issuedDlg.innerText().catch(() => "");
  check("desk: keyboard Enter registers a walk-in; token issued with username, no SMS claim", issuedText.includes("007") && issuedText.includes("Walk Tester")
    && /walkin-[0-9a-f]{8}/.test(issuedText) && issuedText.includes("General Medicine · Dr. Iyer") && !issuedText.includes("SMS"), issuedText);
  check("desk: footer says registered and checked in", (await said()).includes("Walk Tester registered and checked in · Token 007"), await said());
  await page.evaluate(() => { window.__printed = 0; window.print = () => { window.__printed++; }; });
  await click("Print token", issuedDlg);
  const slipDlg = dialog("Token print preview");
  await click("Print", slipDlg);
  const slipText = await slipDlg.innerText();
  check("desk: print preview prints a slip with server data only", (await page.evaluate(() => window.__printed)) === 1 && slipText.includes("007")
    && slipText.includes("Walk Tester") && !/UHID|Room|Riverside|SMS link/.test(slipText), slipText);
  await page.keyboard.press("Escape"); await wait(300);
  check("desk: Escape closes the print preview", !(await slipDlg.isVisible()));
  await wait(800);
  const ovIyer = await overviewOf("Dr. Iyer"), sessionText = await region("General Medicine").innerText();
  check("desk: session card for the chosen doctor (server status, waiting count and clears_at)", /Dr\. Iyer · OPD[\s\S]*Available/.test(sessionText)
    && new RegExp(`(^|\\n)${ovIyer.waiting}\\s*\\nwaiting`).test(sessionText)
    && (ovIyer.clears_at ? sessionText.includes(clockOf(ovIyer.clears_at)) : sessionText.includes("no estimate yet")), `${ovIyer.waiting} / ${ovIyer.clears_at} :: ${sessionText}`);
  check("desk: recent check-ins newest first", (await region("Recent check-ins").locator("li").first().innerText()).includes("Walk Tester"));

  // late within grace: checking in keeps the place
  const lalBefore = await entry("Lal Late");
  await lookFor("Lal Late");
  await lookup.getByRole("button", { name: /^Check in Lal Late/ }).click(); await wait(800);
  const found = dialog("Appointment found");
  check("desk: late within grace is told they keep their place", (await found.innerText()).includes("grace period running") && (await found.innerText()).includes("keeps their original place"));
  await click("Check in · keeps their place", found);
  const lalAfter = await entry("Lal Late");
  check("desk: late patient checked in, same place", (await issuedDlg.innerText()).includes("kept their place") && lalAfter.status === "checked_in" && lalAfter.ahead === lalBefore.ahead,
    `${lalBefore.ahead} → ${lalAfter.ahead}`);
  await click("Done", issuedDlg);

  // skipped: checking in puts them at the end (said before and after)
  await lookFor("Ira Skipped");
  const iraBtn = lookup.getByRole("button", { name: /^Check in Ira Skipped/ });
  check("desk: a skipped patient's check-in says end of queue before the click", (await iraBtn.innerText()).includes("end of queue"));
  await iraBtn.click(); await wait(800);
  check("desk: the dialog warns they go to the end of the queue", (await found.innerText()).includes("at the end of Dr. Iyer’s queue"));
  await click("Check in · rejoin at end", found);
  const iq = await iyer(), ira = iq.entries.find((e) => e.patient_name === "Ira Skipped");
  const lastAhead = Math.max(...iq.entries.filter((e) => e.ahead != null).map((e) => e.ahead));
  check("desk: skipped patient rejoined at the end (server) and is told so", (await issuedDlg.innerText()).includes("rejoined at the end of the queue")
    && ira.status === "checked_in" && ira.ahead === lastAhead && (await said()).includes("rejoined at the end"), `${ira.ahead} of ${lastAhead}`);
  await click("Done", issuedDlg);

  // reinsert next: a written reason is required (browser and server)
  await lookFor("Rhea Again");
  await lookup.getByRole("button", { name: /^Check in Rhea Again/ }).click(); await wait(800);
  await click("Reinsert next… (policy exception)", found);
  const rein = dialog("Reinsert token 005 next?");
  let posts = actionPosts;
  await rein.getByRole("button", { name: "Reinsert next" }).click(); await wait(400);
  const sentEmpty = actionPosts !== posts;
  const noReason = await opost("/api/queue/action", { action: "reinsert_front", appointment_id: (await entry("Rhea Again")).id });
  check("reinsert: refused without a written reason (browser sends nothing; server refuses too)", !sentEmpty && (await rein.isVisible()) && (await entry("Rhea Again")).status === "skipped"
    && noReason.status === 400 && noReason.body.error === "Give a reason for this exception.", JSON.stringify(noReason));
  await rein.getByLabel("Reason for the exception *").fill("Was called away to the pharmacy");
  await click("Reinsert next", rein);
  const rhea = await entry("Rhea Again");
  check("reinsert: next among routine patients, labelled a policy exception", rhea.status === "checked_in" && rhea.ahead === 0
    && (await said()).includes("policy exception"), await said());

  // check-in refusal: another desk checked the patient in first (stream blocked so this screen is behind)
  await page.route("**/api/stream", (r) => r.fulfill({ status: 204 }));
  await page.reload(); await wait(1000);
  await lookFor("Tara Twice");
  await lookup.getByRole("button", { name: /^Check in Tara Twice/ }).click(); await wait(700);
  await opost("/api/checkin", { appointment_id: (await entry("Tara Twice")).id });
  await found.getByRole("button", { name: "Check in & issue token" }).click(); await wait(900);
  check("desk: check-in refusal shown verbatim and the dialog re-reads the server", (await found.innerText()).includes("This appointment is already checked in.")
    && (await found.innerText()).includes("Already checked in"), await found.innerText());
  await page.keyboard.press("Escape");
  await page.unroute("**/api/stream"); await page.reload(); await wait(1000);

  await lookFor("Gita Rao");
  check("desk: no check-in for a visit already checked in", (await lookup.getByRole("button", { name: /^Details for Gita Rao/ }).count()) === 1
    && (await lookup.getByRole("button", { name: /^Check in Gita Rao/ }).count()) === 0);
  await lookFor("zzz-nobody");
  check("desk: nobody matches", (await lookup.innerText()).includes("Nobody on today’s list matches."));

  // reset a patient's password; hidden for a family member, who can still get a walk-in token
  await lookFor("Ira Skipped");
  await lookup.getByRole("button", { name: "Reset password for Ira Skipped" }).click();
  const pwd = dialog("Reset password for Ira Skipped");
  await pwd.getByLabel("New password for this patient").fill("short");
  await click("Set password", pwd);
  check("desk: password reset refusal shown in the dialog", (await pwd.innerText()).includes("Password must be at least 8 characters."));
  await pwd.getByLabel("New password for this patient").fill("walkin-pass1");
  await click("Set password", pwd);
  check("desk: reset a patient's password", (await pwd.innerText()).includes("Password set. They sign in as ira.skipped."));
  await page.keyboard.press("Escape");
  await lookFor("Lila");
  check("desk: no password reset for a family member", (await lookup.getByRole("button", { name: "Reset password for Lila Late" }).count()) === 0
    && (await lookup.innerText()).includes("Lal Late"));
  await lookup.getByRole("button", { name: "Walk-in token for Lila Late" }).click();
  const give = dialog("Walk-in token for Lila Late");
  await give.getByLabel("Department *").selectOption("General Medicine");
  check("desk: walk-in token warns first that a skipped visit rejoins at the end", (await give.innerText()).includes("checks them in at the end of the queue"));
  await pickDoctor(give, "Dr. Rao");
  await click("Give token & check in", give);
  check("desk: walk-in token for a family member's account", (await issuedDlg.innerText()).includes("Lila Late") && (await issuedDlg.innerText()).includes("Dr. Rao"),
    await issuedDlg.innerText().catch(() => ""));
  await click("Done", issuedDlg);
  await lookup.getByRole("button", { name: "Walk-in token for Lila Late" }).click();
  await give.getByLabel("Department *").selectOption("General Medicine"); await pickDoctor(give, "Dr. Rao");
  await click("Give token & check in", give);
  check("desk: an existing visit checked in again says a skipped one rejoins at the end", (await issuedDlg.innerText()).includes("If they had been skipped, they have rejoined at the end of the queue"),
    await issuedDlg.innerText().catch(() => ""));
  await click("Done", issuedDlg);
  // Bilal Khan's visit with Dr. Rao was completed in the consultation checks: nothing changes, no check-in claimed
  await lookFor("Bilal Khan");
  await lookup.getByRole("button", { name: "Walk-in token for Bilal Khan" }).click();
  const giveB = dialog("Walk-in token for Bilal Khan");
  await giveB.getByLabel("Department *").selectOption("General Medicine"); await pickDoctor(giveB, "Dr. Rao");
  await click("Give token & check in", giveB);
  const already = dialog("Already on today’s list");
  check("desk: a completed visit is not called a check-in and gets no token slip", (await already.isVisible()) && (await already.innerText()).includes("completed")
    && (await already.getByRole("button", { name: "Print token" }).count()) === 0 && (await issuedDlg.count()) === 0 && (await said()).includes("nothing changed"), await already.innerText().catch(() => ""));
  await click("Done", already);

  check("desk: patient alert log with labels and text status", /Missed turn[\s\S]*(sent|sending|delivered|failed)/.test(await region("Patient alerts").innerText()));
  const board = await page.context().newPage();
  await board.goto(`${B}/?display=${pol.display_key}`); await board.waitForTimeout(800);
  const boardText = await board.locator("#app").innerText();
  check("desk: the display link opens a board with tokens and no names", boardText.includes("Now serving") && !boardText.includes("Walk Tester") && !boardText.includes("Gita Rao"));
  await board.close();

  // open that doctor's queue in the monitor
  await lookFor("Hari Das");
  check("desk: each Open queue link names its row", (await lookup.getByRole("link", { name: "Open queue: Dr. Iyer, token 002" }).count()) === 1);
  await lookup.getByRole("link", { name: "Open queue" }).first().click(); await wait(1200);
  const card = (name) => region("Sessions").getByRole("button", { name: new RegExp(name) });
  check("monitor: Open queue preselects that doctor", path() === "/app/queue-monitor" && (await card("Dr. Iyer").getAttribute("aria-pressed")) === "true"
    && (await region("General Medicine · Live queue").innerText()).includes("Dr. Iyer"));
  check("monitor: one card per doctor, failed alerts and update time shown", (await region("Sessions").getByRole("button").count()) === 4
    && /\d+ failed alerts? today/.test(await region("Monitoring filters").innerText()) && /Last updated \d/.test(await page.locator("main").innerText()));
  await region("Monitoring filters").getByLabel("Department").selectOption("Paediatrics"); await wait(200);
  check("monitor: department filter", (await region("Sessions").getByRole("button").count()) === 1);
  await region("Monitoring filters").getByLabel("Department").selectOption("");
  const live = page.getByRole("table", { name: "Live queue" });
  const rowOf = (name) => live.locator("tbody tr", { hasText: name });
  check("monitor: live queue in server order with position", (await live.locator("tbody tr").first().innerText()).includes("Rhea Again")
    && (await live.locator("tbody tr").first().innerText()).includes("01"));
  const headIyer = (await iyer()).entries.find((e) => e.status === "booked" || e.status === "checked_in"), iyerCard = await card("Dr. Iyer").innerText();
  check("monitor: next call is the server's ETA for the selected doctor's first waiting patient only",
    (headIyer?.eta ? iyerCard.includes(`${clockOf(headIyer.eta)}\nnext call`) : !iyerCard.includes("next call")) && !(await card("Dr. Rao").innerText()).includes("next call"),
    `${headIyer?.eta} :: ${iyerCard}`);

  await click("Call next patient");
  check("monitor: call next", (await said()).includes("Called token 005"), await said());
  const actionsFor = async (tok) => {
    const all = region("General Medicine · Live queue");
    await click("View complete queue", all);
    await click(`Actions for token ${tok}`, dialog("General Medicine · Full queue"));
    return page.getByRole("dialog", { name: new RegExp(`^Token ${tok}`) });
  };
  let acts = await actionsFor("005");
  await click("Not here…", acts);
  const nh = dialog(/as not here/);
  await nh.getByLabel("Note (optional)").fill("stepped out");
  await click("Mark not here", nh);
  const rheaNh = await entry("Rhea Again");
  check("monitor: not here keeps the place, grace starts", rheaNh.status === "booked" && rheaNh.turn_missed && rheaNh.ahead === 0
    && (await rowOf("Rhea Again").innerText()).includes("Late"), await rowOf("Rhea Again").innerText());
  await click("Review skipped patients →");
  const lateDlg = dialog("Skipped & late patients");
  const rheaLate = lateDlg.locator("li", { hasText: "Rhea Again" });
  check("monitor: skipped & late offers check-in, no skip inside grace", (await rheaLate.getByRole("button", { name: "Check in · keeps place" }).count()) === 1
    && (await rheaLate.getByRole("button", { name: "Skip / no-show" }).count()) === 0);
  await click("Check in · keeps place", rheaLate);
  check("monitor: check in again, keeps their place", (await lateDlg.innerText()).includes("keeps their place") && (await entry("Rhea Again")).status === "checked_in");
  await page.keyboard.press("Escape"); await wait(300);

  acts = await actionsFor("005");
  await click("Priority category…", acts);
  const pri = dialog("Priority for token 005");
  check("monitor: priority offers exactly the policy categories", (await pri.getByLabel("Category *").locator("option").allInnerTexts()).join() === "Senior citizen,Pregnant,Disability");
  await pri.getByLabel("Category *").selectOption("Senior citizen");
  await click("Set priority", pri);
  check("monitor: priority category shown", (await rowOf("Rhea Again").innerText()).includes("Senior citizen"));
  acts = await actionsFor("005");
  await click("Remove priority…", acts);
  const rp = dialog("Remove priority from token 005?");
  posts = actionPosts;
  await rp.getByRole("button", { name: "Remove priority" }).click(); await wait(300);
  check("monitor: remove priority needs a reason (nothing sent)", actionPosts === posts && (await rp.isVisible()) && (await entry("Rhea Again")).priority === "Senior citizen");
  await rp.getByLabel("Reason *").fill("Entered by mistake");
  await click("Remove priority", rp);
  check("monitor: priority removed", (await entry("Rhea Again")).priority === null);

  acts = await actionsFor("002");
  await click("Emergency priority…", acts);
  const em = dialog("Give token 002 emergency priority?");
  posts = actionPosts;
  await em.getByRole("button", { name: "Give emergency priority" }).click(); await wait(300);
  check("monitor: emergency needs a reason (nothing sent)", actionPosts === posts && (await em.isVisible()) && !(await entry("Hari Das")).emergency);
  await em.getByLabel("Reason *").fill("Chest pain");
  await click("Give emergency priority", em);
  check("monitor: emergency goes first", (await live.locator("tbody tr").first().innerText()).includes("Hari Das")
    && (await live.locator("tbody tr").first().innerText()).includes("Emergency"));

  await opost("/api/staff/walkin", { name: "Live Check", doctor_id: 2 });
  await wait(1500);
  await click("View complete queue", region("General Medicine · Live queue"));
  check("live: another desk's change appears without waiting for the timer", (await dialog("General Medicine · Full queue").innerText()).includes("Live Check"));
  await page.keyboard.press("Escape"); await wait(200);

  acts = await actionsFor("007");
  await click("Move to a colleague…", acts);
  const mv = dialog("Move token 007 to a colleague?");
  const colleagues = await mv.getByLabel("Move to *").locator("option").allInnerTexts();
  check("monitor: colleagues are same-department doctors holding OPD", colleagues.length === 1 && colleagues[0].startsWith("Dr. Rao"), colleagues.join(" | "));
  await click("Move patient", mv);
  check("monitor: move to a colleague (the patient leaves this queue)", !(await iyer()).entries.some((e) => e.patient_name === "Walk Tester")
    && (await said()).includes("moved to Dr. Rao"), await said());

  acts = await actionsFor("006");
  await click("Cancel visit…", acts);
  await click("Cancel visit", dialog("Cancel token 006?"));
  check("monitor: cancel with an optional reason; the patient is told", (await entry("Tara Twice")).status === "cancelled" && (await said()).includes("The patient is told"));

  await click("Doctor status…");
  const av2 = dialog("Dr. Iyer: availability");
  check("monitor: doctor status disables the current one", await av2.getByRole("radio", { name: /Available/ }).isDisabled());
  await av2.getByText("Unavailable today").click();
  check("monitor: unavailable asks for confirmation that patients are alerted", (await av2.innerText()).includes("Every waiting patient is sent"));
  await av2.getByText("On a break").click(); await av2.getByLabel("Expected return").selectOption("15");
  await click("Update availability", av2);
  check("monitor: break shown on the card and under Needs attention", (await card("Dr. Iyer").innerText()).includes("On a break")
    && (await region("Needs attention").innerText()).includes("on a break"));
  await click("Doctor status…");
  await av2.getByText("Available", { exact: true }).click(); await click("Update availability", av2);

  // concurrency: a stale version is refused, the screen refreshes, the retry applies
  await page.route("**/api/stream", (r) => r.fulfill({ status: 204 }));
  await page.reload(); await wait(1000);
  await opost("/api/staff/walkin", { name: "Stale Check", doctor_id: 2 });
  acts = await actionsFor("001");
  await click("Priority category…", acts);
  await click("Set priority", dialog("Priority for token 001"));
  const stale = dialog("The queue could not be updated");
  check("monitor concurrency: a stale action is refused, nothing saved", (await stale.innerText()).includes("The queue changed since you loaded it") && !(await entry("Gita Rao")).priority);
  await click("Refresh queue", stale);
  acts = await actionsFor("001");
  await click("Priority category…", acts);
  await click("Set priority", dialog("Priority for token 001"));
  check("monitor concurrency: retry with the fresh version succeeds", (await entry("Gita Rao")).priority === "Senior citizen");
  await page.unroute("**/api/stream"); await page.reload(); await wait(1000);

  await click("View today’s exceptions (", region("Needs attention"));
  check("monitor: today's exceptions listed", (await dialog("Today’s exceptions").innerText()).includes("reinsert front"));
  await page.keyboard.press("Escape"); await wait(200);
  const toMove = (await iyer()).entries.filter((e) => e.status === "booked" || e.status === "checked_in").map((e) => e.patient_name);
  await click("Move all waiting…");
  await click("Move all waiting", dialog("Move everyone waiting for Dr. Iyer?"));
  const rao = await other.evaluate(() => fetch("/api/queue?doctor_id=1").then((r) => r.json()));
  check("monitor: move all waiting moves everyone (server) and shows the server's message", toMove.length > 0 && (await said()).includes(`Moved ${toMove.length} waiting patients to Dr. Rao.`)
    && !(await iyer()).entries.some((e) => e.ahead != null) && toMove.every((n) => rao.entries.some((e) => e.patient_name === n && e.ahead != null)), `${toMove.join(", ")} :: ${await said()}`);

  await card("Dr. Khan").focus(); await page.keyboard.press("Enter"); await wait(900);
  check("monitor: keyboard selects a session card", (await card("Dr. Khan").getAttribute("aria-pressed")) === "true" && page.url().includes("doctor=3"));
  // test_ui.py booked Kiran Khan with Dr. Khan, turn passed 11 minutes ago: grace over, so the server allows a skip
  await click("Review skipped patients →");
  const kLate = dialog("Skipped & late patients"), kiran = kLate.locator("li", { hasText: "Kiran Khan" });
  await click("Skip / no-show", kiran);
  await click("Mark as no-show", page.getByRole("dialog", { name: /as no-show\?$/ }));
  const khanQ = () => other.evaluate(() => fetch("/api/queue?doctor_id=3").then((r) => r.json()));
  const kiranNow = async () => (await khanQ()).entries.find((e) => e.patient_name === "Kiran Khan");
  check("monitor: skip / no-show once grace is over (server status skipped)", (await kiranNow()).status === "skipped" && (await said()).includes("skipped"), await said());
  await click("Review skipped patients →");
  await click("Reinsert next…", kLate.locator("li", { hasText: "Kiran Khan" }));
  const reinK = page.getByRole("dialog", { name: /^Reinsert token \d+ next\?$/ });
  posts = actionPosts;
  await reinK.getByRole("button", { name: "Reinsert next" }).click(); await wait(400);
  check("monitor: per-row reinsert next refused without a reason (nothing sent)", actionPosts === posts && (await reinK.isVisible()) && (await kiranNow()).status === "skipped");
  await reinK.getByLabel("Reason for the exception *").fill("Came back from radiology");
  await click("Reinsert next", reinK);
  const kAfter = await kiranNow();
  check("monitor: per-row reinsert next with a reason puts them next", kAfter.status === "checked_in" && kAfter.ahead === 0 && (await said()).includes("policy exception"), await said());
  await page.keyboard.press("Escape"); await wait(200);
  await click("Move all waiting…");
  const mvk = dialog("Move everyone waiting for Dr. Khan?");
  check("monitor: no colleague in the department", (await mvk.innerText()).includes("No other doctor in this department is holding OPD now.")
    && await mvk.getByRole("button", { name: "Move all waiting" }).isDisabled());
  await page.keyboard.press("Escape");

  // responsive: both screens
  const sideBySide = (a, b) => page.evaluate(([a, b]) => { const [x, y] = [a, b].map((n) => [...document.querySelectorAll("main section")]
    .find((s) => s.getAttribute("aria-labelledby") && document.getElementById(s.getAttribute("aria-labelledby"))?.textContent === n).getBoundingClientRect());
    return Math.abs(x.top - y.top) < 2 && y.left > x.right; }, [a, b]);
  for (const [w, h] of [[1920, 1080], [1024, 768], [390, 844]]) {
    await page.setViewportSize({ width: w, height: h }); await wait(300);
    const mon = w === 1920 ? await sideBySide("Paediatrics · Live queue", "Needs attention") : await noSideScroll();
    await page.goto(B + "/app/front-desk"); await wait(900);
    const fd = w === 1920 ? await sideBySide("Walk-in registration", "Session") : await noSideScroll();
    check(`responsive ${w}: queue monitor and front desk lay out without sideways scroll`, mon && fd);
    await page.goto(B + "/app/queue-monitor?doctor=3"); await wait(900);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await other.close();
  await signOut();

  // admin: same screens, without the doctor/staff-only queue actions
  await login("admin", "admin123");
  await page.goto(B + "/app/queue-monitor?doctor=1"); await wait(1200);
  check("admin: queue monitor without Call next", (await heading()) === "Every queue. One clear picture." && (await page.getByRole("button", { name: "Call next patient" }).count()) === 0);
  await page.getByRole("table", { name: "Live queue" }).getByRole("button", { name: /^Actions for token/ }).first().click(); await wait(500);
  const adminDlg = page.getByRole("dialog", { name: /^Token / }), adminActs = await adminDlg.innerText();
  check("admin: no Not here or Skip, desk actions offered", !adminActs.includes("Not here") && !adminActs.includes("Skip")
    && (await adminDlg.getByRole("button", { name: "Move to a colleague…" }).count()) === 1, adminActs);
  await page.keyboard.press("Escape");
  await page.goto(B + "/app/front-desk"); await wait(800);
  check("admin: front desk", (await heading()) === "A smooth start to every visit.");
  await signOut();
  await login("dr.rao", "doctor123");
  await page.goto(B + "/app/queue-monitor");
  await page.waitForURL(/\/app\/consultation$/);
  check("guard: doctor sent away from the queue monitor", true);
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
