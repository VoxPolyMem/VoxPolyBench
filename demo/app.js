const audioRoot = "../datasets/assets/audio/family-city-break/";
const status = document.getElementById("audio-status");
const sessionsRoot = document.getElementById("audio-sessions");
const questionsRoot = document.getElementById("audio-questions");
const spokenQuestions = document.getElementById("spoken-questions");

async function loadAudio() {
  try {
    const response = await fetch(`${audioRoot}demo_manifest.json`, { cache: "no-store" });
    if (!response.ok) throw new Error("Audio manifest missing");
    const manifest = await response.json();
    if (manifest.case_id !== "family-city-break" || manifest.sessions?.length !== 8 || manifest.questions?.length !== 10) {
      throw new Error("Incomplete case audio");
    }
    if (manifest.sessions.some(item => !/^S[1-8]\.mp3$/.test(item.file)) || manifest.questions.some(item => !/^q\d{2}\.mp3$/.test(item.file))) {
      throw new Error("Invalid audio manifest paths");
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
      row.append(heading, player);
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
    status.textContent = "The complete family-trip audio example is available below.";
  } catch {
    status.textContent = "Audio is temporarily unavailable. The verified questions remain browsable.";
  }
}

loadAudio();
