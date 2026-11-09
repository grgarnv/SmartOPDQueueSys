// Browser checks for every role. Run through test_ui.py, which starts a throwaway server and fills in __BASE__.
async page => {
  const B = "__BASE__";
  const out = [];
  const check = (name, ok, detail = "") => out.push(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  (" + detail + ")" : ""}`);
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error" && !/status of 40[0-9]/.test(m.text())) errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  const wait = (ms) => page.waitForTimeout(ms);
  // playwright-cli keeps native dialogs open as a "modal state", so the page's confirm/prompt are answered in-page
  const answer = (value) => page.evaluate((v) => { window.confirm = () => true; window.prompt = () => v ?? ""; }, value ?? null);
  const text = (sel) => page.locator(sel).innerText();
  const day = (offset) => new Date(Date.now() + offset * 864e5 - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const post = (path, body) => page.evaluate(([p, b]) => fetch(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) }).then((r) => r.json()), [path, body]);
  const choose = async (sel, label) => {  // select the option whose text contains label, and fire change
    await page.evaluate(([s, l]) => { const el = document.querySelector(s); el.value = [...el.options].find((o) => o.text.includes(l)).value; el.dispatchEvent(new Event("change")); }, [sel, label]);
    await wait(400);
  };
  const login = async (u, p) => {
    if (await page.locator("#logout").isVisible()) await page.click("#logout");
    await page.fill("#lu", u); await page.fill("#lp", p); await page.click("#login button");
    await page.waitForSelector("#logout:visible");
    await wait(500);
  };
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(B);
  await page.waitForSelector("#login");
  check("signed out: Sign out and Change password hidden", !(await page.locator("#logout").isVisible()) && !(await page.locator("#pwbtn").isVisible()));
  await page.click("#forgot");
  check("forgot password: dialog opens", await page.locator("#fpdlg").isVisible());
  await page.fill("#fpu", "patient"); await page.click("#fpf1 button"); await wait(300);
  check("forgot password: neutral reply", (await text("#fpmsg")).includes("If that account"));
  await page.click("#fpcancel");

  // admin: open all day, every tab renders
  await login("admin", "admin123");
  await post("/api/admin/policy", { opd_start: "00:00", opd_end: "23:59", block_after_close: 0 });
  await page.click("[data-tab=doctors]");
  await page.fill("#dn", "Cardiology"); await page.click("#adep button"); await wait(400);
  await page.click("[data-edit]"); await wait(200);
  check("admin: edit doctor has hours and daily limit", await page.locator("#ecap").isVisible() && await page.locator("#est").isVisible());
  for (const t of ["ops", "people", "alerts", "reports"]) { await page.click(`[data-tab=${t}]`); await wait(400); }
  check("admin: reports show analytics and backups", (await text("#tabbody")).includes("Patients seen by hour") || (await text("#analytics")).includes("No visits"));
  check("admin: a nightly backup exists", (await text("#bklist")).includes("daily.db"));

  // patient: book, check in, family member, cancel, reschedule
  await login("patient", "patient123");
  const deps = await page.locator("#dep option").allInnerTexts();
  check("patient: empty department not offered", !deps.includes("Cardiology"), deps.join(", "));
  await page.click("#bookbtn"); await wait(400);
  check("patient: booking succeeds", /Booked\. The token is \d+/.test(await text("#bmsg")));
  await page.click("[data-checkin]"); await wait(400);
  check("patient: check-in succeeds", (await text("#appts")).includes("Checked in"));
  await page.click("text=Family members");
  await page.fill("#famn", "Little One"); await page.click("#famf button"); await wait(1300);
  check("patient: family member appears under For", (await page.locator("#for option").allInnerTexts()).includes("Little One"));
  await page.selectOption("#for", { label: "Little One" }); await page.click("#bookbtn"); await wait(500);
  check("patient: booked for family member", (await text("#appts")).includes("For Little One"));
  await answer(); await page.locator(".appt", { hasText: "For Little One" }).locator("[data-cancel]").click(); await wait(500);
  check("patient: cancel removes the card", !(await text("#appts")).includes("For Little One"));
  await page.selectOption("#for", { label: "Little One" }); await page.fill("#day", day(1)); await page.dispatchEvent("#day", "change"); await wait(500);
  await page.click("#bookbtn"); await wait(500);
  await page.locator(".appt", { hasText: "For Little One" }).locator("[data-move]").click(); await wait(200);
  check("patient: reschedule banner", (await text("#resched")).includes("Changing token"));
  await page.fill("#day", day(2)); await page.dispatchEvent("#day", "change"); await wait(500);
  await page.click("#bookbtn"); await wait(500);
  check("patient: reschedule moves the booking", (await text("#bmsg")).startsWith("Moved") && (await text("#appts")).includes(day(2)), await text("#bmsg"));
  const mine = await page.evaluate(() => fetch("/api/my-appointments").then((r) => r.json()));
  const docName = mine.appointments.find((a) => a.day === day(0)).doctor.name;
  const docUser = { "Dr. Iyer": "dr.iyer", "Dr. Rao": "dr.rao", "Dr. Khan": "dr.khan", "Dr. Sen": "dr.sen" }[docName];

  // doctor: call, keyboard focus survives refreshes, start with Enter, complete
  await login(docUser, "doctor123");
  await page.click("[data-call]"); await wait(400);
  check("doctor: call next", /Called token/.test(await text("#qmsg")));
  await page.focus("[data-act=start]");
  await wait(6000);
  check("doctor: focus kept across refresh", await page.evaluate(() => document.activeElement?.dataset?.act === "start"));
  await page.keyboard.press("Enter"); await wait(400);
  check("doctor: keyboard Enter starts consultation", (await text("#queue")).includes("In consultation"));
  await page.click("[data-act=complete]"); await wait(400);
  check("doctor: complete", (await text("#queue")).includes("Completed"));

  // staff: walk-in, not here, check in again, priority, move, live update, password reset, display screen
  await login("staff", "staff123");
  await choose("#qdoc", docName);
  await page.fill("#wn", "Walk Tester"); await page.fill("#wph", "+91 92222 22222");
  await choose("#wdoc", docName); await page.click("#walk button"); await wait(500);
  check("staff: walk-in gets a token", /Token \d+ with/.test(await text("#wmsg")), await text("#wmsg"));
  await page.click("[data-call]"); await wait(500);
  await answer("stepped out"); await page.locator("#queue tr", { hasText: "Walk Tester" }).locator("[data-act=not_present]").click(); await wait(500);
  check("staff: not here keeps the place, grace starts", (await page.locator("#queue tr", { hasText: "Walk Tester" }).innerText()).includes("Turn missed"));
  await page.locator("#queue tr", { hasText: "Walk Tester" }).locator("[data-checkin]").click(); await wait(400);
  await answer("1"); await page.locator("#queue tr", { hasText: "Walk Tester" }).locator("[data-priority]").click(); await wait(500);
  check("staff: priority category shown", (await page.locator("#queue tr", { hasText: "Walk Tester" }).innerText()).includes("Senior citizen"));
  check("staff: live updates connected", await page.evaluate(() => live));
  await post("/api/staff/walkin", { name: "Live Check", doctor_id: +(await page.inputValue("#qdoc")) });
  await wait(1500);
  check("staff: another desk's change appears without waiting for the timer", (await text("#queue")).includes("Live Check"));
  await answer("1"); await page.locator("#queue tr", { hasText: "Walk Tester" }).locator("[data-move]").click(); await wait(500);
  check("staff: move to a colleague", !(await text("#queue")).includes("Walk Tester"), await text("#qmsg"));
  await page.fill("#lq", "Walk Tester"); await page.click("#look button"); await wait(400);
  await answer("walkin-pass1"); await page.locator("[data-pw]").first().click(); await wait(400);
  check("staff: reset a patient's password", (await text("#lkmsg")).includes("Password set"));
  const pol = await page.evaluate(() => fetch("/api/admin/policy").then((r) => r.json()));
  const board = await page.context().newPage();
  await board.goto(`${B}/?display=${pol.display_key}`); await board.waitForTimeout(800);
  const boardText = await board.locator("#app").innerText();
  check("display: board shows tokens without names", boardText.includes("Now serving") && !boardText.includes("Walk Tester") && !boardText.includes("Demo Patient"));
  await board.close();

  // admin: audit filter and analytics after real visits
  await login("admin", "admin123");
  await page.click("[data-tab=alerts]"); await wait(500);
  await page.selectOption("#aua", "cancelled"); await page.click("#auf button"); await wait(500);
  const actions = await page.locator("#events tbody tr td:nth-child(3)").allInnerTexts();
  check("admin: audit filter by action", actions.length > 0 && actions.every((a) => a === "cancelled"), actions.join(","));
  await page.click("[data-tab=reports]"); await wait(600);
  check("admin: analytics chart drawn", await page.locator(".bars div").count() > 0);

  // tester: report open/closed state survives refreshes
  await login("tester", "tester123");
  await page.fill("#seeds", "2"); await page.click("#simf button"); await wait(3000);
  await page.fill("#seeds", "1"); await page.click("#simf button"); await wait(4000);
  await page.evaluate(() => { const d = document.querySelectorAll("#runs details"); d[0].open = false; d[1].open = true; });
  await wait(6000);
  const st = await page.evaluate(() => [...document.querySelectorAll("#runs details")].map((x) => x.open).join());
  check("tester: details state kept across refresh", st === "false,true", st);

  // change password
  await page.click("#pwbtn");
  await page.fill("#pwc", "wrongpass1"); await page.fill("#pwn", "newtester1"); await page.click("#pwf button:not([type])"); await wait(300);
  check("password: wrong current rejected", (await text("#pwmsg")).includes("wrong"));
  await page.fill("#pwc", "tester123"); await page.click("#pwf button:not([type])"); await wait(1600);
  check("password: changed and dialog closed", !(await page.locator("#pwdlg").isVisible()));
  await login("tester", "newtester1");
  check("password: sign in with new password", await page.locator("#runs").isVisible());

  // phone width
  await page.setViewportSize({ width: 375, height: 800 });
  for (const [u, p] of [["patient", "patient123"], ["staff", "staff123"], ["admin", "admin123"]]) {
    await login(u, p);
    const wide = await page.evaluate(() => [...document.querySelectorAll("body *")].filter((e) => e.getBoundingClientRect().right > innerWidth + 1 && !e.parentElement.closest(".tbl"))
      .slice(0, 4).map((e) => `${e.tagName}#${e.id}.${e.className} ${Math.round(e.getBoundingClientRect().right)}`).join(", "));
    const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]);
    check(`mobile (${u}): no sideways page scroll`, sw <= iw, `${sw} vs ${iw} ${wide}`);
  }

  check("no console or page errors (HTTP 4xx answers excluded)", errors.length === 0, errors.join(" | "));
  return out.join("\n");
}
