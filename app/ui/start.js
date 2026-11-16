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
  const appMode = () => { const a = winApi(); if (a && typeof a.minimize === "function" && typeof a.close === "function") document.body.classList.add("app"); };
  appMode();
  window.addEventListener("pywebviewready", appMode);
  document.getElementById("win-min").onclick = () => { const a = winApi(); if (a && a.minimize) a.minimize(); };
  document.getElementById("win-close").onclick = async () => {
    const a = winApi();
    if (!a || !a.close) return;
    if (await confirmBox("김비서를 끌까요? 펫도 같이 꺼져요.", "네, 끌게요")) a.close();
  };
  document.getElementById("talk-btn").onclick = () => (Talk.on ? (Talk.stop(), fetch("/api/status")) : Talk.start());
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
  PetRuntime.load();      // 펫 프로그램이 없으면(설치 때 못 받음) 대화 화면 위에 알림
  setTop("준비됨", "on");
  const first = !get(K.cfg, "처음설정.끝", false) || /[?&]wizard=1\b/.test(location.search);
  if (first) Wizard.start(); else show("main");
  document.body.dataset.ready = "1";
})();
