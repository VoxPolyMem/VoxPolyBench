const audioRoot = "../datasets/assets/audio/family-city-break/";
const status = document.getElementById("audio-status");
const sessionsRoot = document.getElementById("audio-sessions");
const questionsRoot = document.getElementById("audio-questions");
const spokenQuestions = document.getElementById("spoken-questions");
let activeSessionTurns = null;

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Could not load ${url}`);
  return response.json();
}

function renderTurns(session, turns) {
  const details = document.createElement("details");
  details.className = "session-turns";
  const summary = document.createElement("summary");
  summary.textContent = `Play all ${turns.length} individual turns`;
  const list = document.createElement("ol");
  list.className = "session-turn-list";
  list.tabIndex = 0;
  list.setAttribute("aria-label", `Session ${session.session_id.slice(1)} dialogue turns`);
  details.append(summary, list);
  details.addEventListener("toggle", () => {
    if (!details.open) {
      list.replaceChildren();
      if (activeSessionTurns === details) activeSessionTurns = null;
      return;
    }
    if (activeSessionTurns && activeSessionTurns !== details) {
      activeSessionTurns.open = false;
      activeSessionTurns.querySelector("ol").replaceChildren();
    }
    activeSessionTurns = details;
    for (const turn of turns) {
      const item = document.createElement("li");
      const heading = document.createElement("div");
      heading.className = "session-turn-heading";
      const speaker = document.createElement("strong");
      speaker.textContent = turn.speaker_name;
      const number = document.createElement("span");
      number.textContent = `TURN ${String(turn.turn_idx + 1).padStart(2, "0")}`;
      heading.append(speaker, number);
      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "none";
      player.src = audioRoot + turn.file;
      player.setAttribute("aria-label", `Play session ${session.session_id.slice(1)} turn ${turn.turn_idx + 1}, ${turn.speaker_name}`);
      item.append(heading, player);
      list.append(item);
    }
  });
  return details;
}

async function loadDemo() {
  try {
    const manifest = await fetchJson(`${audioRoot}demo_manifest.json`);
    if (manifest.case_id !== "family-city-break" || manifest.sessions?.length !== 8 || manifest.questions?.length !== 10) {
      throw new Error("Incomplete case audio");
    }
    if (manifest.sessions.some(item => !/^S[1-8]\.mp3$/.test(item.file)) || manifest.questions.some(item => !/^q\d{2}\.mp3$/.test(item.file))) {
      throw new Error("Invalid audio manifest paths");
    }
    if (manifest.sessions.some(item => {
      const turns = item.turns;
      return !Array.isArray(turns) || turns.length !== item.turn_count ||
        turns.some((turn, index) => turn.turn_idx !== index || !turn.speaker_name ||
          turn.file !== `turns/${item.session_id}/${String(index).padStart(3, "0")}.mp3`);
    })) {
      throw new Error("Incomplete individual turn audio");
    }
    for (const session of manifest.sessions) {
      const row = document.createElement("div");
      row.className = "audio-row";
      const heading = document.createElement("header");
      const title = document.createElement("strong");
      title.textContent = `Session ${session.session_id.replace("S", "")}`;
      const count = document.createElement("span");
      count.textContent = `${session.turn_count} turns`;
      heading.append(title, count);
      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "none";
      player.src = audioRoot + session.file;
      player.setAttribute("aria-label", `Play ${session.session_id} dialogue`);
      row.append(heading, player, renderTurns(session, session.turns));
      sessionsRoot.append(row);
    }
    for (const question of manifest.questions) {
      const row = document.createElement("div");
      row.className = "question-audio";
      const title = document.createElement("p");
      title.textContent = question.question;
      const player = document.createElement("audio");
      player.controls = true;
      player.preload = "none";
      player.src = audioRoot + question.file;
      player.setAttribute("aria-label", `Play personalized question: ${question.question}`);
      row.append(title, player);
      questionsRoot.append(row);
    }
    spokenQuestions.hidden = false;
    status.textContent = "Eight session recordings and 480 individually playable turns are available below.";
  } catch {
    status.textContent = "This demo is temporarily unavailable. The verified questions remain browsable.";
  }
}

loadDemo();
