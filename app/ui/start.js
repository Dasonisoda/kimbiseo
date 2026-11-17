// 시작 — 설정을 읽고, 처음이면 처음 화면(마법사)부터, 아니면 대화 화면.
"use strict";
(async function boot() {
  document.getElementById("nav-main").onclick = () => show("main");
  document.getElementById("nav-memory").onclick = () => show("memory");
  document.getElementById("nav-settings").onclick = () => show("settings");
  document.getElementById("mem-clear").onclick = () => Memory.clearAll();
  document.getElementById("mem-close").onclick = () => show("main");
  // 테두리 없는 김비서 창일 때만 위 줄의 내리기·끄기 단추를 보인다
  const winApi = () => (window.pywebview && window.pywebview.api) || null;
  const appMode = () => {
    const a = winApi();
    if (a && typeof a.minimize === "function" && typeof a.close === "function") document.body.classList.add("app");
    if (a && typeof a.resize_start === "function") winGrips(a);
  };
  // 창 옮기기: 위쪽 줄(.win-drag)을 누르면 시작, 놓으면 끝만 알린다. 계산은 창 프로그램이 커서·창의 진짜 픽셀 좌표로 한다(app/winbox.py)
  //   — 모니터마다 배율이 달라도 창이 커서에서 떨어지지 않는다. 단추·입력 칸 위에서는 옮기지 않는다.
  document.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !e.target.closest(".win-drag") || e.target.closest("button, input, select, textarea, a, .no-drag")) return;
    const a = winApi();
    if (!a || typeof a.drag_start !== "function") return;
    a.drag_start();
    const up = () => { window.removeEventListener("pointerup", up); window.removeEventListener("pointercancel", up); if (a.drag_end) a.drag_end(); };
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  });
  // 창 크기 조절: 가장자리 여덟 곳(위·아래·왼쪽·오른쪽·네 귀퉁이)에 보이지 않는 손잡이를 둔다
  function winGrips(a) {
    if (document.getElementById("rz-se")) return;
    document.body.classList.add("sizable");
    for (const edge of ["n", "s", "e", "w", "ne", "nw", "se", "sw"]) {
      const d = h("div", {class: "rz rz-" + edge, id: "rz-" + edge, "aria-hidden": "true"});
      const end = () => { if (a.resize_end) a.resize_end(); };
      d.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        try { d.setPointerCapture(e.pointerId); } catch (_) { /* 잡지 못해도 창 프로그램이 단추 뗌을 스스로 앎 */ }
        a.resize_start(edge);
      });
      d.addEventListener("pointerup", end);
      d.addEventListener("pointercancel", end);
      document.body.appendChild(d);
    }
  }
  appMode();
  window.addEventListener("pywebviewready", appMode);
  document.getElementById("win-min").onclick = () => { const a = winApi(); if (a && a.minimize) a.minimize(); };
  document.getElementById("win-close").onclick = async () => {
    const a = winApi();
    if (!a || !a.close) return;
    if (await confirmBox("김비서를 끌까요? 펫도 같이 꺼져요.", "네, 끌게요")) a.close();
  };
  document.getElementById("talk-btn").onclick = () => (Talk.on ? (Talk.stop(), fetch("/api/status")) : Talk.start());
  // 통역 단추: 켜져 있으면 끄고, 꺼져 있으면 켬(말로 대화가 꺼져 있으면 같이 켬 — 마이크로 들어야 통역함)
  document.getElementById("interp-btn").onclick = async () => {
    if (Interp.v && Interp.v["켜짐"]) { await Interp.turn(false); return; }
    await Interp.turn(true);
    if (!Talk.on) Talk.start();
  };
  document.getElementById("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const inp = document.getElementById("chat-text");
    const t = inp.value.trim();
    if (!t) return;
    inp.value = "";
    Talk.sendText(t);
  });
  for (let i = 0; ; i++) {
    try { await loadSettings(); break; } catch (e) {
      setTop("본체를 기다리는 중", "busy");
      if (i > 120) { toast("본체에 연결하지 못했어요. 김비서를 다시 켜 주세요.", 15000); return; }
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  startEvents();
  Update.load();
  Interp.load();          // 통역이 켜져 있으면(화면을 다시 열었을 때) 통역 칸을 보임
  PetRuntime.load();      // 펫 프로그램이 없으면(설치 때 못 받음) 대화 화면 위에 알림
  setTop("준비됨", "on");
  const first = !get(K.cfg, "처음설정.끝", false) || /[?&]wizard=1\b/.test(location.search);
  if (first) Wizard.start(); else show("main");
  document.body.dataset.ready = "1";
})();
